"""
malla.py — Seguidor de Malla Curricular (Derechos Básicos de Aprendizaje, MEN).

Un docente elige una asignatura para su grupo; el sistema propone cómo
distribuir los DBA de esa asignatura/grado entre los períodos académicos
(Ruta A: generada por IA) y el docente marca cuáles ya cubrió. Los DBA son
metas ANUALES sin orden prescrito — la distribución es una sugerencia, el
docente la ajusta libremente marcando/desmarcando seguimiento.

Ruta B (el docente sube su propia malla en Excel/Word) queda fuera de este
sprint — ver nota en el sprint doc.
"""
from __future__ import annotations

import json as _json
import re
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auth import verify_trial_active
from database import get_db
from models import DBA, Docente, Grupo, MallaCurricular, MallaItem, SeguimientoDBA

router = APIRouter(prefix="/api/malla", tags=["malla"])

_PERIODOS_DEFAULT = 4


# ═══════════════════════════════════════════════════════════════
# SCHEMAS
# ═══════════════════════════════════════════════════════════════

class GenerarMallaRequest(BaseModel):
    id_grupo: str
    asignatura: str
    periodos: int = _PERIODOS_DEFAULT


class SeguimientoRequest(BaseModel):
    id_grupo: str
    id_dba: str
    periodo: int
    cubierto: bool = True
    referencia: Optional[str] = None


# ═══════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════

def _grupo_del_docente(db: Session, id_grupo: str, docente: Docente) -> Grupo:
    grupo = db.query(Grupo).filter(
        Grupo.id_grupo == id_grupo,
        Grupo.id_docente == docente.id_docente,
    ).first()
    if not grupo:
        raise HTTPException(status_code=404, detail="Grupo no encontrado")
    return grupo


async def _distribuir_dbas_con_ia(dbas: List[DBA], asignatura: str, grado: str, periodos: int) -> dict:
    """
    Le pide al proveedor de IA activo (Claude/Gemini, vía llm.py) que
    distribuya los DBA entre los períodos. Fallback determinístico
    (reparto parejo en el orden del catálogo) si la IA falla o responde
    algo que no se puede parsear — nunca dejamos al docente sin malla.

    Retorna: {"1": [numero, ...], "2": [...], ...} (claves como string
    porque así las vamos a guardar/leer del JSON de todos modos).
    """
    dba_list = [{"numero": d.numero, "enunciado": d.enunciado[:150]} for d in dbas]
    instruccion = (
        f"Eres un experto en currículo colombiano. Distribuye los siguientes "
        f"{len(dba_list)} Derechos Básicos de Aprendizaje (DBA) de {asignatura} "
        f"grado {grado} en {periodos} períodos académicos del año escolar colombiano.\n\n"
        "REGLAS:\n"
        "- Los DBA son metas anuales del MEN, no tienen orden obligatorio.\n"
        f"- Distribuye de forma balanceada (aprox {max(1, len(dba_list) // periodos)} por período).\n"
        "- Considerá progresión pedagógica: conceptos fundantes primero, aplicación después.\n"
        "- Respondé SOLO con JSON válido, sin texto antes ni después, sin ```json.\n\n"
        f"DBAs disponibles:\n{_json.dumps(dba_list, ensure_ascii=False)}\n\n"
        "Respondé con este formato exacto:\n"
        '{"distribucion": [{"periodo": 1, "dba_numeros": [1, 2, 3]}, {"periodo": 2, "dba_numeros": [4, 5]}]}'
    )

    try:
        import llm
        raw = (await llm.respuesta_completa(
            "Sos un asistente experto en currículo escolar colombiano.",
            [{"role": "user", "content": instruccion}],
            max_tokens=1000,
        )).strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)
        parsed = _json.loads(raw)
        distribucion = {
            str(p["periodo"]): [int(n) for n in p["dba_numeros"]]
            for p in parsed["distribucion"]
        }
        if distribucion:
            return distribucion
    except Exception:
        pass  # cae al fallback determinístico

    # Fallback: reparto parejo en el orden del catálogo (por número de DBA)
    distribucion: dict = {str(p): [] for p in range(1, periodos + 1)}
    por_periodo = max(1, len(dbas) // periodos)
    for i, d in enumerate(dbas):
        p = min(i // por_periodo + 1, periodos)
        distribucion[str(p)].append(d.numero)
    return distribucion


# ═══════════════════════════════════════════════════════════════
# ENDPOINTS
# ═══════════════════════════════════════════════════════════════

@router.get("/asignaturas")
def get_asignaturas(
    db: Session = Depends(get_db),
    docente: Docente = Depends(verify_trial_active),
):
    """Asignaturas y grados disponibles en el catálogo de DBA."""
    filas = db.query(DBA.asignatura, DBA.grado).distinct().order_by(DBA.asignatura, DBA.grado).all()
    result: dict = {}
    for asignatura, grado in filas:
        result.setdefault(asignatura, []).append(grado)
    return result


@router.get("/dbas")
def get_dbas(
    asignatura: str,
    grado: str,
    db: Session = Depends(get_db),
    docente: Docente = Depends(verify_trial_active),
):
    dbas = db.query(DBA).filter_by(asignatura=asignatura, grado=grado).order_by(DBA.numero).all()
    return [
        {"id_dba": d.id_dba, "numero": d.numero, "enunciado": d.enunciado, "evidencias": d.evidencias}
        for d in dbas
    ]


@router.get("/grupo/{id_grupo}")
def get_malla_grupo(
    id_grupo: str,
    asignatura: str,
    db: Session = Depends(get_db),
    docente: Docente = Depends(verify_trial_active),
):
    _grupo_del_docente(db, id_grupo, docente)

    malla = db.query(MallaCurricular).filter_by(id_grupo=id_grupo, asignatura=asignatura).first()
    if not malla:
        return {"malla": None, "items": []}

    items = []
    for item in malla.items:
        seguimiento = db.query(SeguimientoDBA).filter_by(
            id_grupo=id_grupo, id_dba=item.id_dba, periodo=item.periodo,
        ).first()
        items.append({
            "periodo": item.periodo,
            "dba": {"id_dba": item.dba.id_dba, "numero": item.dba.numero, "enunciado": item.dba.enunciado},
            "cubierto": seguimiento.cubierto if seguimiento else False,
        })
    items.sort(key=lambda x: (x["periodo"], x["dba"]["numero"]))

    return {
        "malla": {
            "id_malla": malla.id_malla, "asignatura": malla.asignatura,
            "grado": malla.grado, "tipo": malla.tipo, "periodos": malla.periodos,
        },
        "items": items,
    }


@router.post("/generar")
async def generar_malla(
    body: GenerarMallaRequest,
    db: Session = Depends(get_db),
    docente: Docente = Depends(verify_trial_active),
):
    """Ruta A: la IA propone la distribución de los DBA entre períodos."""
    grupo = _grupo_del_docente(db, body.id_grupo, docente)

    dbas = db.query(DBA).filter_by(
        asignatura=body.asignatura, grado=grupo.grado,
    ).order_by(DBA.numero).all()
    if not dbas:
        raise HTTPException(
            status_code=404,
            detail=f"No hay DBAs en el catálogo para {body.asignatura} grado {grupo.grado}",
        )

    distribucion = await _distribuir_dbas_con_ia(dbas, body.asignatura, grupo.grado, body.periodos)

    # Reemplaza la malla existente para esta (grupo, asignatura) — un solo
    # malla activa por combinación, consistente con el UniqueConstraint.
    existente = db.query(MallaCurricular).filter_by(
        id_grupo=body.id_grupo, asignatura=body.asignatura,
    ).first()
    if existente:
        db.delete(existente)
        db.flush()

    malla = MallaCurricular(
        id_grupo=body.id_grupo, asignatura=body.asignatura, grado=grupo.grado,
        periodos=body.periodos, tipo="generada",
    )
    db.add(malla)
    db.flush()

    dba_por_numero = {d.numero: d.id_dba for d in dbas}
    for periodo_str, numeros in distribucion.items():
        for numero in numeros:
            id_dba = dba_por_numero.get(numero)
            if id_dba:
                db.add(MallaItem(id_malla=malla.id_malla, id_dba=id_dba, periodo=int(periodo_str)))

    db.commit()
    return {"mensaje": "Malla generada", "id_malla": malla.id_malla, "total_dbas": len(dbas)}


@router.post("/seguimiento")
def marcar_dba(
    body: SeguimientoRequest,
    db: Session = Depends(get_db),
    docente: Docente = Depends(verify_trial_active),
):
    _grupo_del_docente(db, body.id_grupo, docente)

    seguimiento = db.query(SeguimientoDBA).filter_by(
        id_grupo=body.id_grupo, id_dba=body.id_dba, periodo=body.periodo,
    ).first()
    if seguimiento:
        seguimiento.cubierto = body.cubierto
        seguimiento.fecha_cubierto = datetime.utcnow() if body.cubierto else None
        seguimiento.plan_clase_referencia = body.referencia
    else:
        seguimiento = SeguimientoDBA(
            id_grupo=body.id_grupo, id_dba=body.id_dba, periodo=body.periodo,
            cubierto=body.cubierto,
            fecha_cubierto=datetime.utcnow() if body.cubierto else None,
            plan_clase_referencia=body.referencia,
        )
        db.add(seguimiento)
    db.commit()
    return {"ok": True}


@router.get("/progreso/{id_grupo}")
def get_progreso(
    id_grupo: str,
    asignatura: str,
    periodo: Optional[int] = None,
    db: Session = Depends(get_db),
    docente: Docente = Depends(verify_trial_active),
):
    _grupo_del_docente(db, id_grupo, docente)

    malla = db.query(MallaCurricular).filter_by(id_grupo=id_grupo, asignatura=asignatura).first()
    if not malla:
        return {"total": 0, "cubiertos": 0, "porcentaje": 0, "items": []}

    q = db.query(MallaItem).filter_by(id_malla=malla.id_malla)
    if periodo is not None:
        q = q.filter_by(periodo=periodo)
    items = q.all()

    resultado = []
    for item in items:
        seguimiento = db.query(SeguimientoDBA).filter_by(
            id_grupo=id_grupo, id_dba=item.id_dba, periodo=item.periodo,
        ).first()
        resultado.append({
            "periodo": item.periodo,
            "dba_numero": item.dba.numero,
            "enunciado": item.dba.enunciado[:100],
            "cubierto": seguimiento.cubierto if seguimiento else False,
        })

    total = len(resultado)
    cubiertos = sum(1 for r in resultado if r["cubierto"])
    return {
        "total": total,
        "cubiertos": cubiertos,
        "porcentaje": round(cubiertos / total * 100) if total else 0,
        "items": resultado,
    }
