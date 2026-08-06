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

from auth import verify_trial_active
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
    "Información del estudiante",
    "Contexto escolar y familiar",
    "Fortalezas e intereses",
    "Barreras para el aprendizaje y la participación",
    "Ajustes razonables y estrategias DUA",
    "Evaluación flexible",
    "Apoyos requeridos",
    "Metas del período",
    "Acuerdos y compromisos",
    "Seguimiento",
)

# Backfill 2 niveles: PIARs guardados con schemas anteriores se mapean
# al nuevo al RENDERIZAR el DOCX (no destructivo — la DB conserva las
# keys originales). Nivel 1 = schema super-legacy (pre markdown-docx).
# Nivel 2 = schema intermedio (6 secciones post markdown-docx).

_SUPER_LEGACY_TO_NUEVO = {
    # Pre-sprint markdown-docx (JSON con snake_case)
    "caracterizacion":     "Información del estudiante",
    "barreras":            "Barreras para el aprendizaje y la participación",
    "ajustes_razonables":  "Ajustes razonables y estrategias DUA",
    # `apoyos` snake_case → "Apoyos requeridos" (nueva sección propia).
    "apoyos":              "Apoyos requeridos",
    "metas":               "Metas del período",
    "seguimiento":         "Seguimiento",
}

_INTERMEDIO_TO_NUEVO = {
    # Post-sprint markdown-docx (6 secciones nombradas)
    "Datos del estudiante":                              "Información del estudiante",
    "Descripción del contexto escolar":                  "Contexto escolar y familiar",
    "Barreras para el aprendizaje y la participación":   "Barreras para el aprendizaje y la participación",
    "Ajustes razonables y apoyos":                       "Ajustes razonables y estrategias DUA",
    "Estrategias de evaluación flexible":                "Evaluación flexible",
    "Seguimiento y compromisos":                         "Seguimiento",
}


def _normalizar_a_esquema_nuevo(contenido: dict) -> dict:
    """
    Devuelve un dict con las 10 keys nuevas de SECCIONES_PIAR.

    Cadena de decisión:
    1. Si `contenido` tiene alguna key del schema NUEVO → completar
       con "" las faltantes y devolver.
    2. Si tiene keys del schema INTERMEDIO (6 títulos post markdown-docx)
       → mapear cada una a su equivalente nuevo.
    3. Si tiene keys del schema SUPER-LEGACY (snake_case pre-markdown)
       → mapear via _SUPER_LEGACY_TO_NUEVO.
    4. Si es dict vacío o no reconocido → todas las secciones en "".

    "Fortalezas e intereses", "Acuerdos y compromisos" son secciones
    NUEVAS que no existían en ningún schema anterior — quedan "" en
    PIARs migrados (el DOCX renderiza [PENDIENTE — sin información]).
    """
    if not isinstance(contenido, dict):
        return {s: "" for s in SECCIONES_PIAR}

    # (1) Ya está en esquema nuevo
    if any(k in contenido for k in SECCIONES_PIAR):
        return {s: str(contenido.get(s, "")).strip() for s in SECCIONES_PIAR}

    out = {s: "" for s in SECCIONES_PIAR}

    # (2) Intermedio (6 secciones post markdown-docx)
    if any(k in contenido for k in _INTERMEDIO_TO_NUEVO):
        for viejo, nuevo in _INTERMEDIO_TO_NUEVO.items():
            v = contenido.get(viejo)
            if isinstance(v, str) and v.strip():
                out[nuevo] = v.strip()
        return out

    # (3) Super-legacy (snake_case)
    for viejo, nuevo in _SUPER_LEGACY_TO_NUEVO.items():
        v = contenido.get(viejo)
        if isinstance(v, str) and v.strip():
            out[nuevo] = v.strip()
    return out


# ═══════════════════════════════════════════════════════════════
# SCHEMA JSON FIJO (sprint piar-fixed-format)
# ═══════════════════════════════════════════════════════════════
#
# En el schema fijo el LLM devuelve JSON con 14 claves snake_case,
# nosotros rellenamos un template Markdown estático (piar_template.md)
# y el DOCX se genera de eso. Ventajas: 100% determinístico en formato,
# validación estricta, sub-campos que antes se agrupaban (compromisos
# separados institución/docente/familia) quedan explícitos.

from pathlib import Path

# Path al template — se calcula una vez y se cachea.
_PIAR_TEMPLATE_PATH = Path(__file__).resolve().parent / "templates" / "piar_template.md"
_piar_template_cache: Optional[str] = None

# Las 14 claves que el LLM debe devolver. NO incluyen los 5 metadatos
# del estudiante (nombre, grado, docente, diagnostico, fecha) porque
# esos vienen del backend, no del LLM.
CLAVES_JSON_PIAR = (
    "contexto_escolar_familiar",
    "fortalezas_intereses",
    "barreras_bap",
    "dua_representacion",
    "dua_expresion",
    "dua_motivacion",
    "evaluacion_flexible",
    "apoyos_requeridos",
    "metas_periodo",
    "compromisos_institucion",
    "compromisos_docente",
    "compromisos_familia",
    "fecha_revision",
    "observaciones_seguimiento",
)


def _cargar_template_piar() -> str:
    """Lee el template una vez y lo cachea en memoria."""
    global _piar_template_cache
    if _piar_template_cache is None:
        _piar_template_cache = _PIAR_TEMPLATE_PATH.read_text(encoding="utf-8")
    return _piar_template_cache


def _es_esquema_json_14_claves(contenido: dict) -> bool:
    """
    True si el dict corresponde al schema del sprint piar-fixed-format.
    Detección: al menos una key esperada del snake_case Y ninguna key
    del schema de 10-secciones (para no confundir con super-legacy que
    también tiene snake_case pero con otras keys).
    """
    if not isinstance(contenido, dict) or not contenido:
        return False
    tiene_nuevas = any(k in contenido for k in CLAVES_JSON_PIAR)
    tiene_secciones_nombradas = any(k in contenido for k in SECCIONES_PIAR)
    return tiene_nuevas and not tiene_secciones_nombradas


def _sanitizar_json_14_claves(bruto: dict) -> dict:
    """
    Garantiza las 14 keys en el dict + string clean. Missing keys → "".
    NO agrega defaults semánticos ("PENDIENTE") acá; eso queda para el
    rendering final donde el markdown_parser detecta strings vacíos.
    """
    if not isinstance(bruto, dict):
        return {k: "" for k in CLAVES_JSON_PIAR}
    out = {}
    for k in CLAVES_JSON_PIAR:
        v = bruto.get(k, "")
        out[k] = v.strip() if isinstance(v, str) else ""
    return out


def _rellenar_template_markdown(json_llm: dict, datos_estudiante: dict) -> str:
    """
    Combina los 14 campos del LLM + 5 metadatos del estudiante en el
    template piar_template.md y retorna el Markdown final listo para
    parsear.

    Validación: si al JSON del LLM le faltan claves, se levanta
    ValueError con la lista de faltantes — la política es "fallar
    rápido y explícito" en vez de generar un PIAR malformado.

    Datos del estudiante que el template espera:
        nombre, grado, docente, diagnostico, fecha
    Si alguno no viene en datos_estudiante, se rellena con "—".
    """
    if not isinstance(json_llm, dict):
        raise ValueError("json_llm debe ser un dict con las 14 claves del PIAR")
    faltantes = [k for k in CLAVES_JSON_PIAR if k not in json_llm]
    if faltantes:
        raise ValueError(
            f"PIAR incompleto — el LLM no devolvió estas claves: {faltantes}"
        )

    # Rellenar campos vacíos con marcador de pendiente para preservar
    # el layout uniforme del documento.
    json_saneado = {
        k: (json_llm.get(k, "") or "").strip() or "[PENDIENTE — sin información]"
        for k in CLAVES_JSON_PIAR
    }

    # Metadatos del estudiante con defaults defensivos.
    meta_defaults = {
        "nombre":      "—",
        "grado":       "—",
        "docente":     "—",
        "diagnostico": "—",
        "fecha":       datetime.utcnow().strftime("%d/%m/%Y"),
    }
    meta = {**meta_defaults, **{k: v for k, v in (datos_estudiante or {}).items() if v}}

    template = _cargar_template_piar()
    return template.format_map({**meta, **json_saneado})


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
    Sprint piar-fixed-format: el LLM devuelve JSON con las 14 claves
    fijas de CLAVES_JSON_PIAR (snake_case). Se persiste ese dict en
    PIAR.contenido; al renderizar el DOCX se combina con el template
    piar_template.md para garantizar formato 100% determinístico.

    Nombre de la función preservado por retro-compat con tests que
    mockean este helper.

    Si el JSON no parsea (modelo devolvió otra cosa), fallback a un
    skeleton con las 14 keys vacías — el generador DOCX pondrá
    "[PENDIENTE — sin información]" en cada campo.
    """
    import json as _json
    from ia import _bloque_contexto_grupo, _bloque_piar
    from prompts import PROMPT_BASE, PROMPT_MODO_PIAR

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

    # Turno final de consolidación: pide JSON con las 14 claves EXACTAS.
    claves_bullet = "\n".join(f'  "{k}": "..."' for k in CLAVES_JSON_PIAR)
    instruccion_final = (
        "TURNO DE CONSOLIDACIÓN — Sintetizá TODA la conversación anterior "
        "en JSON estructurado. Devolvé SOLO el JSON con exactamente estas "
        "14 claves, sin texto antes ni después, sin ```json:\n\n"
        "{\n" + claves_bullet + "\n}\n\n"
        "Reglas:\n"
        "- Cada valor es texto Markdown en registro formal, apto para "
        "documento legal que la familia pueda leer.\n"
        "- fortalezas_intereses SIEMPRE antes que barreras_bap en la "
        "conversación previa; escribí ambas con el mismo cuidado.\n"
        "- barreras_bap describe el CONTEXTO (metodología uniforme, "
        "material inaccesible, evaluación no diversificada, etc.), NO al "
        "estudiante. Usá 'el contexto presenta barreras de tipo…'.\n"
        "- dua_representacion / dua_expresion / dua_motivacion: cada uno "
        "con al menos 2 estrategias concretas aplicables en el aula.\n"
        "- evaluacion_flexible: enumerar AL MENOS 3 alternativas concretas "
        "(oral, portafolio, proyecto, rúbrica adaptada, etc.).\n"
        "- apoyos_requeridos: citá el Decreto 1421 al menos una vez.\n"
        "- compromisos_institucion / compromisos_docente / compromisos_"
        "familia: acciones concretas, medibles.\n"
        "- fecha_revision: formato DD/MM/YYYY o descripción textual "
        "(ej: 'Final del período académico').\n"
        "- Prohibido: 'sufre', 'padece', 'déficit', 'trastorno'.\n"
        "- Si algún campo no se cubrió, dejá string vacío (\"\") — el "
        "generador lo marcará como pendiente.\n"
    )
    if messages and messages[-1]["role"] == "user":
        messages[-1]["content"] += "\n\n" + instruccion_final
    else:
        messages.append({"role": "user", "content": instruccion_final})

    # Llamada al proveedor activo (Claude / Gemini).
    import llm
    try:
        raw = (await llm.respuesta_completa(
            system_prompt, messages, max_tokens=4096,
        )).strip()
    except Exception as exc:
        raise RuntimeError(f"Error llamando al proveedor de IA para síntesis: {exc}") from exc

    # Robustez: si el modelo envuelve el JSON en ```json ... ```
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)

    # Fallback tolerante: si no parsea, devolvemos las 14 keys vacías —
    # es mejor un PIAR con secciones pendientes que un 500 al usuario.
    try:
        parsed = _json.loads(raw)
    except Exception:
        return _sanitizar_json_14_claves({})
    return _sanitizar_json_14_claves(parsed if isinstance(parsed, dict) else {})


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
    Genera el DOCX del PIAR con formato 100% determinístico.

    Router 3-schemas (post sprint piar-fixed-format):
    - Schema NUEVO (JSON de 14 claves snake_case): se rellena
      piar_template.md con format_map y se parsea a secciones. El LLM
      no controla los títulos ni el orden — solo el contenido.
    - Schema anterior (10 secciones nombradas / intermedio / super-legacy):
      _normalizar_a_esquema_nuevo mapea y se renderiza directo. PIARs
      guardados antes de este sprint siguen abriéndose bien.

    El sello BORRADOR/APROBADO se inyecta como "sección virtual" al
    inicio en ambos casos, sin acoplar el template al modelo PIAR.
    """
    from templates.maestria_template import generar_piar_docx
    from markdown_parser import parse_markdown_sections

    # Datos de portada — comunes a ambos schemas.
    inst = (getattr(docente, "institucion", None) or "").strip()
    ciudad = (getattr(docente, "ciudad", None) or "").strip()
    grado_display = f"{grupo.grado} · {grupo.asignatura} · {grupo.nombre_grupo}"
    if inst:
        grado_display += f" ({inst}{' — ' + ciudad if ciudad else ''})"

    datos_docx = {
        "nombre": estudiante.codigo_estudiante,
        "grado":  grado_display,
        "docente": docente.nombre_completo,
        "fecha":  datetime.now().strftime("%d/%m/%Y"),
    }

    # Sello BORRADOR/APROBADO — misma lógica en ambos schemas.
    if piar.estado == "aprobado":
        fecha_aprob = piar.aprobado_en.strftime("%d/%m/%Y") if piar.aprobado_en else "—"
        sello_md = f"**APROBADO — {fecha_aprob}**"
    else:
        sello_md = "**BORRADOR — Sujeto a revisión**"
    version_line = f"Versión v{piar.version} · Periodo {piar.periodo} · Año {piar.anio}"
    sello_seccion = {"Estado del documento": f"{sello_md}\n\n{version_line}"}

    contenido = piar.contenido or {}

    if _es_esquema_json_14_claves(contenido):
        # ── Path NUEVO: template estático + JSON del LLM ──
        # Datos del estudiante que van INTO el template piar_template.md.
        # `diagnostico` viene de estudiante (campo legacy en la ficha).
        datos_template = {
            "nombre":      estudiante.codigo_estudiante,
            "grado":       grado_display,
            "docente":     docente.nombre_completo,
            "diagnostico": (getattr(estudiante, "diagnostico", "") or "—").strip(),
            "fecha":       datetime.now().strftime("%d/%m/%Y"),
        }
        markdown_final = _rellenar_template_markdown(contenido, datos_template)
        # parse_markdown_sections divide por `## `, preservando cada
        # bloque en orden. El template garantiza que aparezcan las 10
        # secciones canónicas siempre en el mismo orden y con los
        # mismos nombres — el LLM no puede cambiarlo.
        secciones_parseadas = parse_markdown_sections(markdown_final)
        secciones = {**sello_seccion, **secciones_parseadas}
    else:
        # ── Path RETRO-COMPAT: mapear al schema de 10 secciones ──
        contenido_dict = _normalizar_a_esquema_nuevo(contenido)
        secciones = dict(sello_seccion)
        for k in SECCIONES_PIAR:
            secciones[k] = contenido_dict.get(k, "")

    buf = generar_piar_docx(secciones, datos_docx)
    return buf.read()


# ═══════════════════════════════════════════════════════════════
# ENDPOINTS
# ═══════════════════════════════════════════════════════════════

@router.post("/", response_model=PIAROut, status_code=201)
async def crear_piar(
    body: PIARCreateRequest,
    docente: Docente = Depends(verify_trial_active),
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
    docente: Docente = Depends(verify_trial_active),
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
    docente: Docente = Depends(verify_trial_active),
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
    docente: Docente = Depends(verify_trial_active),
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
