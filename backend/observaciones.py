"""
observaciones.py — Observador del Alumno + seguimiento (Ley 1620 de 2013,
Decreto 1965 de 2013, Ley 1098 de 2006 Art. 44, Decreto 1421 de 2017).

A diferencia del PIAR, una Observación es un registro de un solo turno:
el docente narra la situación en texto libre y este módulo hace UNA
llamada al proveedor de IA (Claude/Gemini) para redactar la versión
profesional, clasificarla según la Ruta de Atención Integral de la
Ley 1620 y sugerir acciones concretas. No requiere conversación previa
en el chat (aunque el modo "observaciones" también existe en el chat
multi-modo para exploración conversacional antes de crear el registro
formal — ver prompts.py y socket_events.py).

Rate limiting: exento a propósito, tanto del contador diario por modo
(prompts.LIMITES_DIARIOS[MODO_OBSERVACIONES] = 999999) como del tope
mensual del plan free (bypaseado en socket_events.py). Las situaciones
que motivan una observación son urgentes — no deben esperar a mañana ni
quedar detrás de un paywall.
"""
from __future__ import annotations

import json as _json
import re
from datetime import date, datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from auth import get_current_docente
from database import get_db
from documento import _docx_bytes
from models import Docente, Estudiante, Grupo, Observacion
from prompts import PROMPT_BASE, PROMPT_MODO_OBSERVACIONES

router = APIRouter(prefix="/api/observaciones", tags=["observaciones"])

TIPOS_VALIDOS = frozenset({
    "academica", "convivencia", "familiar", "salud",
    "asistencia", "piar", "logro",
})
NIVELES_ESCALACION_VALIDOS = frozenset({
    "docente", "coordinador", "orientador", "externo", "icbf",
})
ESTADOS_VALIDOS = frozenset({"abierta", "en_seguimiento", "cerrada"})

_NIVEL_DEFAULT = "docente"


# ═══════════════════════════════════════════════════════════════
# SCHEMAS
# ═══════════════════════════════════════════════════════════════

class ObservacionCreate(BaseModel):
    id_grupo: str
    id_estudiante: Optional[str] = None  # nullable — puede ser grupal
    tipo: str
    situacion_descrita: str = Field(min_length=1)


class ObservacionUpdate(BaseModel):
    estado: Optional[str] = None
    fecha_seguimiento: Optional[date] = None


class ObservacionOut(BaseModel):
    id_observacion: str
    id_estudiante: Optional[str]
    id_docente: str
    id_grupo: str
    tipo: str
    situacion_descrita: str
    observacion_generada: Optional[str]
    nivel_escalacion: str
    acciones_recomendadas: Optional[List[str]]
    requiere_seguimiento: bool
    fecha_seguimiento: Optional[date]
    estado: str
    creado_en: datetime

    model_config = {"from_attributes": True}


# ═══════════════════════════════════════════════════════════════
# GENERACIÓN CON IA
# ═══════════════════════════════════════════════════════════════

def _contexto_estudiante(estudiante: Optional[Estudiante]) -> str:
    if not estudiante:
        return "\n• Esta observación es GRUPAL — no apunta a un estudiante específico.\n"
    ctx = f"\n• Estudiante: {estudiante.codigo_estudiante}"
    if estudiante.tiene_piar:
        ctx += (
            f"\n• Tiene PIAR activo — diagnóstico: {estudiante.diagnostico or 'no especificado'}"
            f"\n• Ajustes PIAR vigentes: {estudiante.ajustes or 'no especificados'}"
            "\n• Recordá: esta observación es insumo obligatorio para la próxima "
            "actualización de su PIAR (Decreto 1421)."
        )
    return ctx + "\n"


async def _generar_observacion_ia(
    docente: Docente,
    grupo: Grupo,
    estudiante: Optional[Estudiante],
    tipo: str,
    situacion_descrita: str,
) -> dict:
    """
    Llamada única al proveedor de IA activo. Devuelve un dict con
    `observacion_generada` (Markdown, formato del Observador del Alumno),
    `nivel_escalacion` (uno de NIVELES_ESCALACION_VALIDOS) y
    `acciones_recomendadas` (lista de strings).

    Nombre de la función preservado explícito (no inline) para que los
    tests puedan monkeypatchearla sin llamar al proveedor real — mismo
    patrón que piar._sintetizar_conversacion_a_json.
    """
    system_prompt = (
        PROMPT_BASE
        + "\n\n" + PROMPT_MODO_OBSERVACIONES
        + f"""
═══════════════════════════════════════════
CONTEXTO
═══════════════════════════════════════════
• Grupo: {grupo.nombre_grupo} · {grupo.grado} · {grupo.asignatura}
• Fecha de hoy: {date.today().strftime('%d/%m/%Y')}
• Docente: {docente.nombre_completo}
• Tipo de situación indicado por el docente: {tipo}
"""
        + _contexto_estudiante(estudiante)
    )

    instruccion = (
        "El docente narró la siguiente situación:\n\n"
        f'"{situacion_descrita}"\n\n'
        "Generá el registro formal. Devolvé SOLO un JSON con exactamente "
        "estas 3 claves, sin texto antes ni después, sin ```json:\n\n"
        "{\n"
        '  "observacion_generada": "...",\n'
        '  "nivel_escalacion": "docente|coordinador|orientador|externo|icbf",\n'
        '  "acciones_recomendadas": ["...", "..."]\n'
        "}\n\n"
        "Reglas:\n"
        "- `observacion_generada`: Markdown completo siguiendo EXACTO el "
        "formato de salida indicado arriba (## Observación en el "
        "Observador del Alumno, con todas las secciones).\n"
        "- `nivel_escalacion`: tu clasificación según la Ley 1620 — "
        "uno solo de los 5 valores listados, en minúsculas, sin texto extra.\n"
        "- `acciones_recomendadas`: 2 a 5 acciones concretas y accionables, "
        "cada una un string corto (no un párrafo).\n"
        "- Si la situación es Tipo III (presunto delito), `nivel_escalacion` "
        "debe ser \"icbf\" y `observacion_generada` debe citar el Art. 44 "
        "de la Ley 1098 de 2006 y mencionar explícitamente ICBF."
    )

    import llm
    try:
        raw = (await llm.respuesta_completa(
            system_prompt,
            [{"role": "user", "content": instruccion}],
            max_tokens=2048,
        )).strip()
    except Exception as exc:
        raise RuntimeError(f"Error llamando al proveedor de IA: {exc}") from exc

    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)

    try:
        parsed = _json.loads(raw)
    except Exception:
        parsed = {}
    if not isinstance(parsed, dict):
        parsed = {}

    nivel = str(parsed.get("nivel_escalacion", "")).strip().lower()
    if nivel not in NIVELES_ESCALACION_VALIDOS:
        nivel = _NIVEL_DEFAULT

    acciones = parsed.get("acciones_recomendadas")
    if not isinstance(acciones, list):
        acciones = []
    acciones = [str(a).strip() for a in acciones if str(a).strip()]

    observacion_generada = parsed.get("observacion_generada")
    if not isinstance(observacion_generada, str) or not observacion_generada.strip():
        observacion_generada = (
            "## Observación en el Observador del Alumno\n\n"
            "_[PENDIENTE — el asistente no pudo generar el texto. "
            "Redactalo manualmente a partir de la situación descrita.]_"
        )

    return {
        "observacion_generada": observacion_generada,
        "nivel_escalacion": nivel,
        "acciones_recomendadas": acciones,
    }


# ═══════════════════════════════════════════════════════════════
# ENDPOINTS
# ═══════════════════════════════════════════════════════════════

@router.post("", response_model=ObservacionOut, status_code=201)
async def crear_observacion(
    body: ObservacionCreate,
    docente: Docente = Depends(get_current_docente),
    db: Session = Depends(get_db),
):
    tipo = body.tipo.strip().lower()
    if tipo not in TIPOS_VALIDOS:
        raise HTTPException(
            status_code=400,
            detail=f"tipo inválido. Valores aceptados: {', '.join(sorted(TIPOS_VALIDOS))}",
        )

    grupo = db.query(Grupo).filter(
        Grupo.id_grupo == body.id_grupo,
        Grupo.id_docente == docente.id_docente,
    ).first()
    if not grupo:
        raise HTTPException(status_code=404, detail="Grupo no encontrado")

    estudiante = None
    if body.id_estudiante:
        estudiante = db.query(Estudiante).filter(
            Estudiante.id_estudiante == body.id_estudiante,
            Estudiante.id_grupo == grupo.id_grupo,
        ).first()
        if not estudiante:
            raise HTTPException(status_code=404, detail="Estudiante no pertenece a este grupo")

    generado = await _generar_observacion_ia(
        docente, grupo, estudiante, tipo, body.situacion_descrita,
    )

    observacion = Observacion(
        id_estudiante=estudiante.id_estudiante if estudiante else None,
        id_docente=docente.id_docente,
        id_grupo=grupo.id_grupo,
        tipo=tipo,
        situacion_descrita=body.situacion_descrita,
        observacion_generada=generado["observacion_generada"],
        nivel_escalacion=generado["nivel_escalacion"],
        acciones_recomendadas=generado["acciones_recomendadas"],
        requiere_seguimiento=True,
        estado="abierta",
    )
    db.add(observacion)
    db.commit()
    db.refresh(observacion)
    return observacion


@router.get("/seguimientos-pendientes", response_model=List[ObservacionOut])
def seguimientos_pendientes(
    docente: Docente = Depends(get_current_docente),
    db: Session = Depends(get_db),
):
    """
    Observaciones del docente con fecha_seguimiento vencida (hoy o antes)
    y todavía no cerradas — para el badge de alertas del dashboard.
    """
    hoy = date.today()
    q = (
        db.query(Observacion)
        .filter(
            Observacion.id_docente == docente.id_docente,
            Observacion.fecha_seguimiento.isnot(None),
            Observacion.fecha_seguimiento <= hoy,
            Observacion.estado != "cerrada",
        )
        .order_by(Observacion.fecha_seguimiento.asc())
    )
    return q.all()


@router.get("", response_model=List[ObservacionOut])
def listar_observaciones(
    id_estudiante: Optional[str] = Query(default=None),
    id_grupo: Optional[str] = Query(default=None),
    docente: Docente = Depends(get_current_docente),
    db: Session = Depends(get_db),
):
    q = db.query(Observacion).filter(Observacion.id_docente == docente.id_docente)
    if id_estudiante:
        q = q.filter(Observacion.id_estudiante == id_estudiante)
    if id_grupo:
        q = q.filter(Observacion.id_grupo == id_grupo)
    return q.order_by(Observacion.creado_en.desc()).all()


@router.get("/{observacion_id}", response_model=ObservacionOut)
def detalle_observacion(
    observacion_id: str,
    docente: Docente = Depends(get_current_docente),
    db: Session = Depends(get_db),
):
    obs = db.query(Observacion).filter(
        Observacion.id_observacion == observacion_id,
        Observacion.id_docente == docente.id_docente,
    ).first()
    if not obs:
        raise HTTPException(status_code=404, detail="Observación no encontrada")
    return obs


@router.patch("/{observacion_id}", response_model=ObservacionOut)
def actualizar_observacion(
    observacion_id: str,
    body: ObservacionUpdate,
    docente: Docente = Depends(get_current_docente),
    db: Session = Depends(get_db),
):
    obs = db.query(Observacion).filter(
        Observacion.id_observacion == observacion_id,
        Observacion.id_docente == docente.id_docente,
    ).first()
    if not obs:
        raise HTTPException(status_code=404, detail="Observación no encontrada")

    if body.estado is not None:
        if body.estado not in ESTADOS_VALIDOS:
            raise HTTPException(
                status_code=400,
                detail=f"estado inválido. Valores aceptados: {', '.join(sorted(ESTADOS_VALIDOS))}",
            )
        obs.estado = body.estado
        if body.estado == "cerrada":
            obs.requiere_seguimiento = False

    if body.fecha_seguimiento is not None:
        obs.fecha_seguimiento = body.fecha_seguimiento

    db.commit()
    db.refresh(obs)
    return obs


@router.post("/{observacion_id}/exportar")
def exportar_observacion(
    observacion_id: str,
    docente: Docente = Depends(get_current_docente),
    db: Session = Depends(get_db),
):
    obs = db.query(Observacion).filter(
        Observacion.id_observacion == observacion_id,
        Observacion.id_docente == docente.id_docente,
    ).first()
    if not obs:
        raise HTTPException(status_code=404, detail="Observación no encontrada")

    grupo = db.query(Grupo).filter(Grupo.id_grupo == obs.id_grupo).first()
    if not grupo:
        raise HTTPException(status_code=404, detail="Grupo no encontrado")

    md = obs.observacion_generada or "## Observación en el Observador del Alumno\n\n_Sin contenido generado._"

    try:
        docx_bytes = _docx_bytes(
            md=md,
            titulo="Observacion",
            docente=docente,
            grupo=grupo,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generando DOCX: {e}")

    filename = f"observacion_{obs.id_observacion[:8]}.docx"
    import io
    return StreamingResponse(
        io.BytesIO(docx_bytes),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
