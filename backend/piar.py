"""
Endpoints REST del generador de PIAR (Plan Individual de Ajustes Razonables).

Contrato:
- POST /api/piar/                      → crear borrador desde conversación (síntesis vía Claude)
- GET  /api/piar/estudiante/{eid}      → listar todas las versiones del estudiante
- PUT  /api/piar/{piar_id}/aprobar     → aprobar (borrador → aprobado, inmutable)
- GET  /api/piar/{piar_id}/docx        → descargar DOCX on-demand (marca BORRADOR si aplica)

Todos los endpoints validan que el PIAR pertenezca al docente autenticado.

Nota de diseño (aprobada por el owner):
- Denormalización de id_grupo e id_docente en la tabla PIAR (derivables
  desde id_estudiante) — asumida para queries frecuentes sin JOINs.
- Sin docx_bytes: el DOCX se regenera on-demand desde `contenido` cada vez
  que se pide. Permite cambiar el template sin migrar datos.
"""
from __future__ import annotations

import io  # noqa: F401 — reservado por si algún endpoint futuro devuelve BytesIO manual
import re
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from auth import get_current_docente
from database import get_db
from ia import client as anthropic_client
from config import settings
from models import Docente, Estudiante, Grupo, Mensaje, PIAR
from prompts import MODO_PIAR

router = APIRouter(prefix="/api/piar", tags=["piar"])


# ═══════════════════════════════════════════════════════════════
# SCHEMAS
# ═══════════════════════════════════════════════════════════════

SECCIONES_PIAR = (
    "Datos del estudiante",
    "Descripción del contexto escolar",
    "Barreras para el aprendizaje y la participación",
    "Ajustes razonables y apoyos",
    "Estrategias de evaluación flexible",
    "Seguimiento y compromisos",
)

# Mapeo de keys legacy → nuevos títulos. Se usa al RENDERIZAR PIARs
# guardados con el schema anterior (best-effort). No es destructivo:
# los PIARs viejos se preservan en DB con sus keys originales.
_LEGACY_TO_NUEVO = {
    "caracterizacion":     "Datos del estudiante",
    "barreras":            "Barreras para el aprendizaje y la participación",
    "ajustes_razonables":  "Ajustes razonables y apoyos",
    # `apoyos` legacy se concatena al final de "Ajustes razonables y apoyos"
    # dentro de _normalizar_a_esquema_nuevo() — no tiene destino propio.
    "metas":               "Estrategias de evaluación flexible",
    "seguimiento":         "Seguimiento y compromisos",
}


def _normalizar_a_esquema_nuevo(contenido: dict) -> dict:
    """
    Devuelve un dict con las 6 keys nuevas de SECCIONES_PIAR.

    - Si `contenido` ya tiene el esquema nuevo (alguna key en SECCIONES_PIAR),
      se completa con "" las que falten y se devuelve tal cual.
    - Si tiene el esquema legacy (keys en _LEGACY_TO_NUEVO), se mapea.
      El campo legacy `apoyos` se concatena al final de "Ajustes razonables
      y apoyos" bajo un sub-heading. "Descripción del contexto escolar"
      no existía en el esquema legacy y queda con string vacío.
    - Si es dict vacío o no reconocido, se devuelven todas las secciones
      con string vacío (el generador DOCX pinta "[PENDIENTE — sin
      información]" en cada una).
    """
    if not isinstance(contenido, dict):
        return {s: "" for s in SECCIONES_PIAR}

    # ¿Ya está en esquema nuevo?
    if any(k in contenido for k in SECCIONES_PIAR):
        return {s: str(contenido.get(s, "")).strip() for s in SECCIONES_PIAR}

    # Esquema legacy → mapear
    out = {s: "" for s in SECCIONES_PIAR}
    for legacy_key, nueva_key in _LEGACY_TO_NUEVO.items():
        v = contenido.get(legacy_key)
        if isinstance(v, str) and v.strip():
            out[nueva_key] = v.strip()
    apoyos_legacy = contenido.get("apoyos")
    if isinstance(apoyos_legacy, str) and apoyos_legacy.strip():
        base = out["Ajustes razonables y apoyos"]
        sub = "\n\n### Apoyos requeridos\n\n" + apoyos_legacy.strip()
        out["Ajustes razonables y apoyos"] = (base + sub) if base else apoyos_legacy.strip()
    return out


class PIARCreateRequest(BaseModel):
    id_estudiante: str
    periodo: int = Field(ge=1, le=4)
    anio: Optional[int] = None  # si no se pasa, se toma grupo.anio_lectivo


class PIAROut(BaseModel):
    id_piar: str
    id_estudiante: str
    id_grupo: str
    id_docente: str
    periodo: int
    anio: int
    version: int
    contenido: dict
    estado: str
    creado_en: datetime
    aprobado_en: Optional[datetime]

    model_config = {"from_attributes": True}


class PIARResumenOut(BaseModel):
    """
    Vista liviana para listados en fichas de estudiante. Sin el JSON
    de `contenido` — el docente lo materializa al pedir el DOCX.
    """
    id_piar: str
    id_estudiante: str
    id_grupo: str
    id_docente: str
    periodo: int
    anio: int
    version: int
    estado: str
    creado_en: datetime
    aprobado_en: Optional[datetime]

    model_config = {"from_attributes": True}


# ═══════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════

def _piar_del_docente_o_404(piar_id: str, docente_id: str, db: Session) -> PIAR:
    p = db.query(PIAR).filter(
        PIAR.id_piar == piar_id,
        PIAR.id_docente == docente_id,
    ).first()
    if not p:
        raise HTTPException(status_code=404, detail="PIAR no encontrado")
    return p


def _next_version(db: Session, id_estudiante: str, id_grupo: str,
                  periodo: int, anio: int) -> int:
    """
    Devuelve version+1 para el tuple (estudiante, grupo, periodo, anio),
    o 1 si no hay versiones previas. Race condition posible pero muy baja
    (un solo docente por grupo). El UNIQUE constraint de la tabla protege
    ante colisiones — en caso de choque, el POST fallará con IntegrityError.
    """
    maxv = (
        db.query(PIAR.version)
        .filter(
            PIAR.id_estudiante == id_estudiante,
            PIAR.id_grupo == id_grupo,
            PIAR.periodo == periodo,
            PIAR.anio == anio,
        )
        .order_by(PIAR.version.desc())
        .limit(1)
        .scalar()
    )
    return (maxv or 0) + 1


_PENDIENTE_MARKER = "[PENDIENTE — sin información]"


def _skeleton_pendiente() -> dict:
    """Contenido default cuando la síntesis IA falla o no hay conversación."""
    return {s: _PENDIENTE_MARKER for s in SECCIONES_PIAR}


def _sanitizar_contenido(bruto: dict) -> dict:
    """
    Recibe el dict crudo del parser Markdown y asegura las 6 secciones
    esperadas. Secciones extra se descartan; ausentes se marcan pendientes.
    Los valores se coercen a string. Retro-compat: si viene con keys
    legacy se normaliza al esquema nuevo primero.
    """
    if not isinstance(bruto, dict):
        return _skeleton_pendiente()
    normalizado = _normalizar_a_esquema_nuevo(bruto)
    out = {}
    for s in SECCIONES_PIAR:
        v = normalizado.get(s, "")
        v = v.strip() if isinstance(v, str) else ""
        out[s] = v if v else _PENDIENTE_MARKER
    return out


async def _sintetizar_conversacion_a_json(
    docente: Docente,
    grupo: Grupo,
    estudiante: Estudiante,
    historial: List[Mensaje],
) -> dict:
    """
    Envía la conversación PIAR completa al proveedor de IA y espera que
    devuelva SOLO el documento en Markdown con las 6 secciones fijas de
    SECCIONES_PIAR (títulos como `## `). El Markdown se parsea con
    markdown_parser.parse_markdown_sections y se retorna como dict
    {título: contenido_md}.

    El nombre de la función se preserva por retro-compat con tests que
    mockean este helper — internamente ya no hay JSON, sólo Markdown.

    Si la respuesta del modelo no contiene los headings esperados, el
    parser rellena con "" y `_sanitizar_contenido` completa con el
    marker de pendiente en vez de crashear.
    """
    from ia import _bloque_contexto_grupo, _bloque_piar
    from prompts import PROMPT_BASE, PROMPT_MODO_PIAR
    from markdown_parser import parse_markdown_sections

    system_prompt = (
        PROMPT_BASE
        + "\n\n" + PROMPT_MODO_PIAR
        + _bloque_contexto_grupo(grupo, [estudiante])
        + _bloque_piar(estudiante)
    )

    # Turnos de la conversación previa (últimos 40 para no romper contexto)
    messages = []
    for msg in historial[-40:]:
        role = "user" if msg.remitente == "docente" else "assistant"
        if messages and messages[-1]["role"] == role:
            messages[-1]["content"] += "\n\n" + msg.contenido
        else:
            messages.append({"role": role, "content": msg.contenido})

    # Turno final de consolidación (pide Markdown, no JSON).
    instruccion_final = (
        "TURNO DE CONSOLIDACIÓN — Sintetizá TODA la conversación anterior en el "
        "documento completo del PIAR siguiendo el formato Markdown obligatorio "
        "descripto arriba en el system prompt. Devolvé EXACTAMENTE las 6 secciones "
        f"con `## ` y estos nombres exactos: {', '.join(SECCIONES_PIAR)}. "
        "Cada sección en registro formal, vocabulario del Decreto 1421 (BAP, "
        "ajustes razonables, apoyos), sin patologizar. Secciones no cubiertas "
        f"→ `{_PENDIENTE_MARKER}`. Sin texto adicional antes ni después."
    )
    if messages and messages[-1]["role"] == "user":
        messages[-1]["content"] += "\n\n" + instruccion_final
    else:
        messages.append({"role": "user", "content": instruccion_final})

    # Llamada sin streaming — respuesta de una sola vez para parseo.
    # Delega en el proveedor activo (Claude / Gemini). El endpoint captura
    # el RuntimeError o el ProveedorNoConfiguradoError y decide el status.
    import llm
    try:
        raw = (await llm.respuesta_completa(
            system_prompt, messages, max_tokens=4096,
        )).strip()
    except Exception as exc:
        raise RuntimeError(f"Error llamando al proveedor de IA para síntesis: {exc}") from exc

    # Robustez: si el modelo envuelve la respuesta en ```markdown ... ```
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:markdown|md)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)

    parsed = parse_markdown_sections(raw, esperadas=list(SECCIONES_PIAR))
    return _sanitizar_contenido(parsed)


# ═══════════════════════════════════════════════════════════════
# DOCX GENERATOR — wrapper sobre templates/maestria_template
# ═══════════════════════════════════════════════════════════════
#
# El pipeline pre-refactor construía el DOCX párrafo por párrafo acá
# (~150 líneas). Ahora el layout de marca (header, portada, secciones,
# footer con página) vive en backend/templates/maestria_template.py.
# Este helper solo prepara los `datos` de portada y el sello
# BORRADOR/APROBADO, y delega el render al template.

def _construir_piar_docx(
    docente: Docente,
    grupo: Grupo,
    estudiante: Estudiante,
    piar: PIAR,
) -> bytes:
    """
    Genera el DOCX del PIAR usando el template Maestr.ia. El sello
    BORRADOR/APROBADO se inyecta como una "sección virtual" al comienzo
    del cuerpo, antes de las 6 secciones canónicas de SECCIONES_PIAR.

    Retro-compat: si `piar.contenido` viene con las keys legacy (PIARs
    guardados antes del sprint markdown-docx), `_normalizar_a_esquema_nuevo`
    las mapea a los 6 títulos actuales antes de renderizar.
    """
    from templates.maestria_template import generar_piar_docx

    # Normalizamos el contenido al esquema nuevo (retro-compat para PIARs
    # guardados con keys viejas: caracterizacion, ajustes_razonables, etc.)
    contenido_dict = _normalizar_a_esquema_nuevo(piar.contenido or {})

    # Sello BORRADOR/APROBADO como primera sección — así aparece arriba
    # del PIAR sin acoplar el template al modelo PIAR.
    if piar.estado == "aprobado":
        fecha_aprob = piar.aprobado_en.strftime("%d/%m/%Y") if piar.aprobado_en else "—"
        sello_md = f"**APROBADO — {fecha_aprob}**"
    else:
        sello_md = "**BORRADOR — Sujeto a revisión**"
    version_line = f"Versión v{piar.version} · Periodo {piar.periodo} · Año {piar.anio}"

    secciones: dict[str, str] = {"Estado del documento": f"{sello_md}\n\n{version_line}"}
    for k in SECCIONES_PIAR:
        secciones[k] = contenido_dict.get(k, "")

    # Datos de portada — usan campos legacy que ya viven en el modelo.
    inst = (getattr(docente, "institucion", None) or "").strip()
    ciudad = (getattr(docente, "ciudad", None) or "").strip()
    grado_display = f"{grupo.grado} · {grupo.asignatura} · {grupo.nombre_grupo}"
    if inst:
        grado_display += f" ({inst}{' — ' + ciudad if ciudad else ''})"

    datos = {
        "nombre": estudiante.codigo_estudiante,
        "grado":  grado_display,
        "docente": docente.nombre_completo,
        "fecha":  datetime.now().strftime("%d/%m/%Y"),
    }

    buf = generar_piar_docx(secciones, datos)
    return buf.read()


# ═══════════════════════════════════════════════════════════════
# ENDPOINTS
# ═══════════════════════════════════════════════════════════════

@router.post("/", response_model=PIAROut, status_code=201)
async def crear_piar(
    body: PIARCreateRequest,
    docente: Docente = Depends(get_current_docente),
    db: Session = Depends(get_db),
):
    """
    Crea un borrador de PIAR sintetizando la conversación PIAR existente
    entre el docente y el asistente para el estudiante indicado.

    Requiere que exista al menos un mensaje previo en modo PIAR para ese
    (grupo, estudiante). Si no hay conversación, devuelve 400.

    Consume 1 llamada al modelo (síntesis) — NO se contabiliza contra el
    rate limit diario aquí porque el rate limit se aplica en el socket
    handler para el chat, y esta síntesis es un turno diferenciado. Se
    documenta como decisión de MVP; en el próximo sprint puede integrarse
    al mismo contador si el owner lo pide.
    """
    # 1. Estudiante debe existir y pertenecer a un grupo del docente
    estudiante = db.query(Estudiante).filter(
        Estudiante.id_estudiante == body.id_estudiante,
    ).first()
    if not estudiante:
        raise HTTPException(status_code=404, detail="Estudiante no encontrado")
    grupo = db.query(Grupo).filter(
        Grupo.id_grupo == estudiante.id_grupo,
        Grupo.id_docente == docente.id_docente,
    ).first()
    if not grupo:
        raise HTTPException(status_code=404, detail="Estudiante no pertenece a un grupo tuyo")
    if not estudiante.tiene_piar:
        raise HTTPException(
            status_code=400,
            detail="El estudiante no tiene PIAR activo. Actívalo en la ficha del estudiante primero.",
        )

    # 2. Debe haber conversación previa en modo PIAR para este estudiante
    historial = (
        db.query(Mensaje)
        .filter(
            Mensaje.id_grupo == grupo.id_grupo,
            Mensaje.modo == MODO_PIAR,
            Mensaje.id_estudiante == estudiante.id_estudiante,
        )
        .order_by(Mensaje.timestamp.asc())
        .all()
    )
    if len(historial) == 0:
        raise HTTPException(
            status_code=400,
            detail=(
                "No hay conversación de PIAR aún para este estudiante. "
                "Iniciá el chat en modo PIAR antes de generar el borrador."
            ),
        )

    # 3. Sintetizar con Claude (o skeleton si falla)
    try:
        contenido = await _sintetizar_conversacion_a_json(
            docente, grupo, estudiante, historial,
        )
    except RuntimeError as exc:
        # Fallo del modelo — devolvemos skeleton + status distinto para debug
        raise HTTPException(status_code=502, detail=str(exc))

    # 4. Calcular versión y persistir
    anio = body.anio or grupo.anio_lectivo
    version = _next_version(db, estudiante.id_estudiante, grupo.id_grupo,
                            body.periodo, anio)
    piar = PIAR(
        id_estudiante=estudiante.id_estudiante,
        id_grupo=grupo.id_grupo,
        id_docente=docente.id_docente,
        periodo=body.periodo,
        anio=anio,
        version=version,
        contenido=contenido,
        estado="borrador",
    )
    db.add(piar)
    db.commit()
    db.refresh(piar)
    return piar


@router.get("/estudiante/{id_estudiante}", response_model=List[PIARResumenOut])
def listar_por_estudiante(
    id_estudiante: str,
    docente: Docente = Depends(get_current_docente),
    db: Session = Depends(get_db),
):
    """
    Lista todos los PIARs (todas las versiones) del estudiante, ordenados
    del más reciente al más antiguo.

    Permisos (Issue #5 · multi-institución):
    - Docente dueño del grupo del estudiante → siempre ve.
    - Coordinador o rector con plan institucional activo → ve los PIARs
      de estudiantes cuyos docentes-dueños pertenezcan a su institución.
    - Cualquier otro → 404 (contrato: no revelar existencia).

    Retorna [] si no hay PIARs para ese estudiante (200, no 404). Ese
    caso ocurre en la ficha de un estudiante recién marcado con PIAR.
    """
    from permisos import es_admin_institucion, ids_docentes_institucion

    est = db.query(Estudiante).filter(
        Estudiante.id_estudiante == id_estudiante,
    ).first()
    if not est:
        raise HTTPException(status_code=404, detail="Estudiante no encontrado")

    grupo = db.query(Grupo).filter(Grupo.id_grupo == est.id_grupo).first()
    if not grupo:
        raise HTTPException(status_code=404, detail="Estudiante no encontrado")

    puede_ver = grupo.id_docente == docente.id_docente
    if not puede_ver and es_admin_institucion(docente) and docente.id_institucion:
        docentes_inst = set(ids_docentes_institucion(docente.id_institucion, db))
        puede_ver = grupo.id_docente in docentes_inst

    if not puede_ver:
        raise HTTPException(status_code=404, detail="Estudiante no encontrado")

    piars = (
        db.query(PIAR)
        .filter(PIAR.id_estudiante == id_estudiante)
        .order_by(PIAR.anio.desc(), PIAR.periodo.desc(), PIAR.version.desc())
        .all()
    )
    return piars


@router.put("/{piar_id}/aprobar", response_model=PIAROut)
def aprobar_piar(
    piar_id: str,
    docente: Docente = Depends(get_current_docente),
    db: Session = Depends(get_db),
):
    """
    Aprueba el PIAR: transición borrador → aprobado. Es inmutable después:
    reaprobar el mismo PIAR devuelve 409.

    Una vez aprobado, para hacer cambios el docente debe crear una nueva
    versión (POST /piar/ genera v+1 automáticamente).
    """
    piar = _piar_del_docente_o_404(piar_id, docente.id_docente, db)

    if piar.estado == "aprobado":
        raise HTTPException(
            status_code=409,
            detail=(
                "Este PIAR ya está aprobado. Para hacer cambios, generá una "
                "nueva versión desde el chat en modo PIAR."
            ),
        )

    piar.estado = "aprobado"
    piar.aprobado_en = datetime.utcnow()
    db.commit()
    db.refresh(piar)
    return piar


@router.get("/{piar_id}/docx")
def descargar_docx(
    piar_id: str,
    docente: Docente = Depends(get_current_docente),
    db: Session = Depends(get_db),
):
    """
    Genera el DOCX del PIAR on-demand y lo devuelve como attachment.
    Incluye marca 'BORRADOR — Sujeto a revisión' si el estado es borrador,
    o 'APROBADO — fecha' si ya fue aprobado.
    """
    piar = _piar_del_docente_o_404(piar_id, docente.id_docente, db)
    estudiante = db.query(Estudiante).filter(
        Estudiante.id_estudiante == piar.id_estudiante,
    ).first()
    grupo = db.query(Grupo).filter(Grupo.id_grupo == piar.id_grupo).first()
    if not estudiante or not grupo:
        raise HTTPException(status_code=500, detail="Estudiante o grupo del PIAR no encontrado (datos inconsistentes)")

    try:
        docx_bytes = _construir_piar_docx(docente, grupo, estudiante, piar)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error generando DOCX del PIAR: {exc}")

    safe = re.sub(r"[^\w\s-]", "", estudiante.codigo_estudiante).strip().replace(" ", "_")[:40]
    filename = f"PIAR_{safe or 'estudiante'}_P{piar.periodo}_v{piar.version}.docx"

    return StreamingResponse(
        io.BytesIO(docx_bytes),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
