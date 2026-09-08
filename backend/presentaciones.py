"""
presentaciones.py — Presentaciones Interactivas tipo Kahoot (sprint
presentaciones-interactivas).

Contrato:
- POST /api/presentaciones/generar         → genera diapositivas vía IA y las guarda
- GET  /api/presentaciones/                → lista presentaciones del docente + sus sesiones
- POST /api/presentaciones/{id}/iniciar    → crea una sesión en vivo (código de 6 chars)
- GET  /api/presentaciones/join/{codigo}   → datos públicos de la sesión (SIN auth)

Los eventos de Socket.io (presentacion_events.py) reusan las funciones
puras de este módulo (iniciar_slide, cerrar_slide, finalizar_sesion,
registrar_respuesta, calcular_resultado) — todas reciben una sesión de
DB ya abierta y no dependen de una conexión de socket, así que son
testeables directo con el fixture `db_session` (mismo criterio que
`_consumir_rate_limit` en socket_events.py).
"""
from __future__ import annotations

import json
import logging
import re
import secrets
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from auth import verify_trial_active
from database import get_db
from models import Docente, Grupo, Presentacion, RespuestaPresentacion, SesionPresentacion
from rate_limiter import limiter
from security_utils import sanitizar_texto

router = APIRouter(prefix="/api/presentaciones", tags=["presentaciones"])
logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# VALIDACIÓN DE DIAPOSITIVAS
# ═══════════════════════════════════════════════════════════════

TIPOS_INTERACCION = frozenset({"multiple", "poll", "nube"})
TIPOS_VALIDOS = frozenset({"contenido"}) | TIPOS_INTERACCION


def _validar_diapositivas(bruto) -> list[dict]:
    """
    Filtra y normaliza el array crudo devuelto por el LLM. Descarta
    elementos malformados en vez de fallar toda la generación — mejor
    una presentación con menos slides que un 502 al docente (mismo
    criterio que _sanitizar_json_14_claves en piar.py). Sanitiza todo
    texto libre con bleach antes de guardarlo (defensa en profundidad:
    aunque el LLM no debería devolver HTML, no confiamos ciegamente en
    su output).
    """
    if not isinstance(bruto, list):
        return []

    limpias: list[dict] = []
    for item in bruto:
        if not isinstance(item, dict):
            continue
        tipo = item.get("tipo")
        if tipo not in TIPOS_VALIDOS:
            continue

        if tipo == "contenido":
            titulo = sanitizar_texto(str(item.get("titulo") or "").strip(), 200)
            cuerpo = sanitizar_texto(str(item.get("cuerpo") or "").strip(), 2000)
            if not titulo or not cuerpo:
                continue
            limpias.append({
                "tipo": "contenido",
                "titulo": titulo,
                "cuerpo": cuerpo,
                "notas_docente": sanitizar_texto(str(item.get("notas_docente") or "").strip(), 1000) or "",
            })

        elif tipo == "multiple":
            pregunta = sanitizar_texto(str(item.get("pregunta") or "").strip(), 500)
            opciones_raw = item.get("opciones")
            if not pregunta or not isinstance(opciones_raw, list) or len(opciones_raw) < 2:
                continue
            opciones = [sanitizar_texto(str(o), 200) or "" for o in opciones_raw][:6]
            correcta = item.get("correcta")
            if not isinstance(correcta, int) or not (0 <= correcta < len(opciones)):
                correcta = 0
            tiempo_s = item.get("tiempo_s")
            tiempo_s = int(tiempo_s) if isinstance(tiempo_s, (int, float)) and tiempo_s > 0 else 20
            puntos = item.get("puntos")
            puntos = int(puntos) if isinstance(puntos, (int, float)) and puntos > 0 else 100
            limpias.append({
                "tipo": "multiple",
                "pregunta": pregunta,
                "opciones": opciones,
                "correcta": correcta,
                "tiempo_s": tiempo_s,
                "puntos": puntos,
            })

        elif tipo == "poll":
            pregunta = sanitizar_texto(str(item.get("pregunta") or "").strip(), 500)
            opciones_raw = item.get("opciones")
            if not pregunta or not isinstance(opciones_raw, list) or len(opciones_raw) < 2:
                continue
            limpias.append({
                "tipo": "poll",
                "pregunta": pregunta,
                "opciones": [sanitizar_texto(str(o), 200) or "" for o in opciones_raw][:6],
            })

        elif tipo == "nube":
            instruccion = sanitizar_texto(str(item.get("instruccion") or "").strip(), 500)
            if not instruccion:
                continue
            limpias.append({"tipo": "nube", "instruccion": instruccion})

    return limpias


# ═══════════════════════════════════════════════════════════════
# GENERACIÓN CON IA
# ═══════════════════════════════════════════════════════════════

_PROMPT_TEMPLATE = """Eres un experto en pedagogía colombiana. Crea una presentación interactiva para:
- Docente: {asignatura}, grado {grado}
- Tema: {tema}
- Estudiantes: {n_estudiantes} estudiantes

Genera exactamente {n_slides} diapositivas de contenido, cada una seguida de UNA pregunta/interacción.
Alterna: contenido → interacción → contenido → interacción...

Para cada diapositiva de CONTENIDO incluye:
- titulo: título claro (máx 8 palabras)
- cuerpo: explicación en máx 4 puntos concisos
- notas_docente: qué decir al proyectar (2-3 líneas)

Para cada INTERACCIÓN, elige el tipo más pedagógico:
- "multiple": 4 opciones, marca cuál es correcta (índice 0-3), tiempo 15-25s
- "poll": opinión sin respuesta correcta, 2-4 opciones
- "nube": palabra libre asociada al concepto

Responde SOLO con un array JSON válido de diapositivas, sin texto adicional."""


async def _generar_diapositivas_ia(grupo: Grupo, tema: str, n_slides_contenido: int) -> list[dict]:
    """
    Llama al proveedor de IA activo (Claude/Gemini vía llm.py) y devuelve
    las diapositivas ya validadas. Nombre y firma pensados para ser
    monkeypatcheados en tests (mismo patrón que
    piar._sintetizar_conversacion_a_json) — nunca se llama a Claude real
    en la suite.
    """
    prompt = _PROMPT_TEMPLATE.format(
        asignatura=grupo.asignatura,
        grado=grupo.grado,
        tema=tema,
        n_estudiantes=grupo.cantidad_estudiantes,
        n_slides=n_slides_contenido,
    )

    import llm
    raw = (await llm.respuesta_completa(
        system_prompt=prompt,
        messages=[{"role": "user", "content": "Generá la presentación ahora."}],
        max_tokens=4096,
    )).strip()

    # Robustez: si el modelo envuelve el JSON en ```json ... ```
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)

    try:
        bruto = json.loads(raw)
    except Exception:
        logger.error(
            "LLM devolvió una respuesta no parseable como JSON al generar "
            "presentación (grupo=%s, tema=%r). Primeros 500 chars: %r",
            grupo.id_grupo, tema, raw[:500],
        )
        bruto = []

    diapositivas = _validar_diapositivas(bruto)
    if bruto and not diapositivas:
        logger.error(
            "El LLM devolvió JSON válido pero _validar_diapositivas rechazó "
            "todos los elementos al generar presentación (grupo=%s, tema=%r). "
            "bruto=%r",
            grupo.id_grupo, tema, bruto,
        )
    return diapositivas


# ═══════════════════════════════════════════════════════════════
# CÓDIGO DE SESIÓN
# ═══════════════════════════════════════════════════════════════

# Sin 0/O, 1/I/L — evita confusión al escribir el código a mano en un celular.
_ALFABETO_CODIGO = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def _generar_codigo_unico(db: Session) -> str:
    for _ in range(20):
        codigo = "".join(secrets.choice(_ALFABETO_CODIGO) for _ in range(6))
        existe = db.query(SesionPresentacion).filter(SesionPresentacion.codigo == codigo).first()
        if not existe:
            return codigo
    raise RuntimeError("No se pudo generar un código de sesión único tras 20 intentos")


# ═══════════════════════════════════════════════════════════════
# LÓGICA DE SESIÓN EN VIVO — funciones puras (usadas por Socket.io y tests)
# ═══════════════════════════════════════════════════════════════

def iniciar_slide(db: Session, sesion: SesionPresentacion, slide_index: int) -> None:
    """Abre un slide para recibir respuestas."""
    sesion.estado = "activa"
    sesion.slide_actual = slide_index
    sesion.slide_abierto = True
    if sesion.iniciado_en is None:
        sesion.iniciado_en = datetime.utcnow()
    db.commit()


def cerrar_slide(db: Session, sesion: SesionPresentacion) -> None:
    """Cierra el slide actual — deja de aceptar respuestas nuevas."""
    sesion.slide_abierto = False
    db.commit()


def finalizar_sesion(db: Session, sesion: SesionPresentacion) -> None:
    sesion.estado = "finalizada"
    sesion.slide_abierto = False
    sesion.finalizado_en = datetime.utcnow()
    db.commit()


def registrar_respuesta(
    db: Session,
    sesion: SesionPresentacion,
    presentacion: Presentacion,
    slide_index: int,
    nombre_estudiante: str,
    respuesta_raw: str,
    tiempo_respuesta_ms: Optional[int],
) -> Optional[RespuestaPresentacion]:
    """
    Devuelve None (sin persistir nada) si el slide ya está cerrado, si
    el estudiante responde a un slide que ya no es el actual (cliente
    desincronizado), o si el índice no existe. Es idempotente por
    (sesión, slide, nombre): una segunda respuesta del mismo estudiante
    al mismo slide devuelve la primera en vez de duplicar el conteo.
    """
    if not sesion.slide_abierto or sesion.slide_actual != slide_index:
        return None
    if slide_index < 0 or slide_index >= len(presentacion.diapositivas or []):
        return None

    nombre_limpio = sanitizar_texto(nombre_estudiante, 100) or "Anónimo"
    respuesta_limpia = sanitizar_texto(respuesta_raw, 500) or ""

    existente = db.query(RespuestaPresentacion).filter(
        RespuestaPresentacion.id_sesion == sesion.id_sesion,
        RespuestaPresentacion.slide_index == slide_index,
        RespuestaPresentacion.nombre_estudiante == nombre_limpio,
    ).first()
    if existente:
        return existente

    slide = presentacion.diapositivas[slide_index]
    es_correcta = None
    if slide.get("tipo") == "multiple":
        es_correcta = respuesta_limpia == str(slide.get("correcta"))

    respuesta = RespuestaPresentacion(
        id_sesion=sesion.id_sesion,
        slide_index=slide_index,
        nombre_estudiante=nombre_limpio,
        respuesta=respuesta_limpia,
        es_correcta=es_correcta,
        tiempo_respuesta_ms=tiempo_respuesta_ms,
    )
    db.add(respuesta)
    db.commit()
    db.refresh(respuesta)
    return respuesta


def _puntos_por_respuesta(slide: dict, es_correcta: Optional[bool], tiempo_ms: Optional[int]) -> int:
    """
    Puntaje estilo Kahoot: 0 si es incorrecta; si es correcta, entre el
    50% y el 100% de los puntos del slide según qué tan rápido respondió
    dentro de la ventana de tiempo permitida.
    """
    if not es_correcta:
        return 0
    puntos_base = int(slide.get("puntos") or 100)
    if not tiempo_ms:
        return puntos_base
    tiempo_s = slide.get("tiempo_s") or 20
    fraccion_transcurrida = min(1.0, max(0.0, tiempo_ms / (tiempo_s * 1000)))
    factor = 1 - fraccion_transcurrida * 0.5
    return round(puntos_base * factor)


def calcular_resultado(db: Session, sesion: SesionPresentacion, presentacion: Presentacion) -> dict:
    """
    Conteos por opción (multiple/poll) o por palabra (nube) del slide
    ACTUAL, más un ranking acumulado de toda la sesión (sólo cuenta
    puntos de slides tipo "multiple", igual que Kahoot).
    """
    diapositivas = presentacion.diapositivas or []
    if sesion.slide_actual < 0 or sesion.slide_actual >= len(diapositivas):
        return {"conteos": {}, "correcta": None, "total_respuestas": 0, "ranking_top5": []}

    slide = diapositivas[sesion.slide_actual]
    respuestas_slide = db.query(RespuestaPresentacion).filter(
        RespuestaPresentacion.id_sesion == sesion.id_sesion,
        RespuestaPresentacion.slide_index == sesion.slide_actual,
    ).all()

    tipo = slide.get("tipo")
    conteos: dict = {}
    correcta = None

    if tipo in ("multiple", "poll"):
        opciones = slide.get("opciones") or []
        conteos = {str(i): 0 for i in range(len(opciones))}
        for r in respuestas_slide:
            if r.respuesta in conteos:
                conteos[r.respuesta] += 1
        if tipo == "multiple":
            correcta = slide.get("correcta")
    elif tipo == "nube":
        for r in respuestas_slide:
            palabra = (r.respuesta or "").strip().lower()
            if palabra:
                conteos[palabra] = conteos.get(palabra, 0) + 1

    todas = db.query(RespuestaPresentacion).filter(
        RespuestaPresentacion.id_sesion == sesion.id_sesion,
    ).all()
    puntos_por_nombre: dict[str, int] = {}
    for r in todas:
        if r.slide_index < 0 or r.slide_index >= len(diapositivas):
            continue
        s = diapositivas[r.slide_index]
        if s.get("tipo") != "multiple":
            continue
        puntos_por_nombre[r.nombre_estudiante] = (
            puntos_por_nombre.get(r.nombre_estudiante, 0)
            + _puntos_por_respuesta(s, r.es_correcta, r.tiempo_respuesta_ms)
        )

    ranking_top5 = sorted(
        ({"nombre": n, "puntos": p} for n, p in puntos_por_nombre.items()),
        key=lambda x: x["puntos"],
        reverse=True,
    )[:5]

    return {
        "conteos": conteos,
        "correcta": correcta,
        "total_respuestas": len(respuestas_slide),
        "ranking_top5": ranking_top5,
    }


# ═══════════════════════════════════════════════════════════════
# SCHEMAS
# ═══════════════════════════════════════════════════════════════

class GenerarPresentacionRequest(BaseModel):
    grupo_id: str
    tema: str = Field(min_length=1, max_length=500)
    n_slides_contenido: int = Field(default=4, ge=1, le=10)

    @field_validator("tema")
    @classmethod
    def _sanitizar_tema(cls, v: str) -> str:
        limpio = sanitizar_texto(v, 500) or ""
        if not limpio:
            raise ValueError("El tema no puede estar vacío.")
        return limpio


class PresentacionOut(BaseModel):
    id_presentacion: str
    id_docente: str
    id_grupo: str
    titulo: str
    tema: str
    diapositivas: list
    creado_en: datetime

    model_config = {"from_attributes": True}


class SesionResumenOut(BaseModel):
    id_sesion: str
    codigo: str
    estado: str
    creado_en: datetime

    model_config = {"from_attributes": True}


class PresentacionListItemOut(BaseModel):
    id_presentacion: str
    titulo: str
    tema: str
    id_grupo: str
    creado_en: datetime
    n_slides: int
    sesiones: List[SesionResumenOut]


class IniciarSesionOut(BaseModel):
    sesion_id: str
    codigo: str
    url_estudiante: str


class SesionPublicaOut(BaseModel):
    sesion_id: str
    codigo: str
    estado: str
    titulo: str
    grado: str
    asignatura: str


# ═══════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════

def _grupo_del_docente_o_404(grupo_id: str, docente_id: str, db: Session) -> Grupo:
    grupo = db.query(Grupo).filter(
        Grupo.id_grupo == grupo_id, Grupo.id_docente == docente_id,
    ).first()
    if not grupo:
        raise HTTPException(status_code=404, detail="Grupo no encontrado")
    return grupo


def _presentacion_del_docente_o_404(presentacion_id: str, docente_id: str, db: Session) -> Presentacion:
    p = db.query(Presentacion).filter(
        Presentacion.id_presentacion == presentacion_id,
        Presentacion.id_docente == docente_id,
    ).first()
    if not p:
        raise HTTPException(status_code=404, detail="Presentación no encontrada")
    return p


# ═══════════════════════════════════════════════════════════════
# ENDPOINTS
# ═══════════════════════════════════════════════════════════════

@router.post("/generar", response_model=PresentacionOut, status_code=201)
async def generar_presentacion(
    body: GenerarPresentacionRequest,
    docente: Docente = Depends(verify_trial_active),
    db: Session = Depends(get_db),
):
    """
    Genera una presentación completa vía IA (diapositivas de contenido
    intercaladas con interacciones) para el grupo y tema indicados, y la
    persiste. El docente todavía no la está proyectando — eso ocurre en
    POST /{id}/iniciar.
    """
    grupo = _grupo_del_docente_o_404(body.grupo_id, docente.id_docente, db)

    try:
        diapositivas = await _generar_diapositivas_ia(grupo, body.tema, body.n_slides_contenido)
    except Exception:
        logger.exception(
            "Error generando presentación IA (docente=%s, grupo=%s, tema=%r)",
            docente.id_docente, grupo.id_grupo, body.tema,
        )
        diapositivas = []
    if not diapositivas:
        raise HTTPException(
            status_code=502,
            detail="No se pudo generar la presentación — intenta de nuevo.",
        )

    presentacion = Presentacion(
        id_docente=docente.id_docente,
        id_grupo=grupo.id_grupo,
        titulo=body.tema[:200],
        tema=body.tema,
        diapositivas=diapositivas,
    )
    db.add(presentacion)
    db.commit()
    db.refresh(presentacion)
    return presentacion


@router.get("/", response_model=List[PresentacionListItemOut])
def listar_presentaciones(
    docente: Docente = Depends(verify_trial_active),
    db: Session = Depends(get_db),
):
    presentaciones = (
        db.query(Presentacion)
        .filter(Presentacion.id_docente == docente.id_docente)
        .order_by(Presentacion.creado_en.desc())
        .all()
    )
    return [
        PresentacionListItemOut(
            id_presentacion=p.id_presentacion,
            titulo=p.titulo,
            tema=p.tema,
            id_grupo=p.id_grupo,
            creado_en=p.creado_en,
            n_slides=len(p.diapositivas or []),
            sesiones=[SesionResumenOut.model_validate(s) for s in p.sesiones],
        )
        for p in presentaciones
    ]


@router.get("/{presentacion_id}", response_model=PresentacionOut)
def obtener_presentacion(
    presentacion_id: str,
    docente: Docente = Depends(verify_trial_active),
    db: Session = Depends(get_db),
):
    """
    Detalle completo (con `diapositivas`) — lo usa
    presentacion-docente.html para proyectar. Deliberadamente separado
    del listado (que no trae `diapositivas`, sólo `n_slides`) para que
    la lista de presentaciones del docente sea liviana.
    """
    return _presentacion_del_docente_o_404(presentacion_id, docente.id_docente, db)


@router.post("/{presentacion_id}/iniciar", response_model=IniciarSesionOut, status_code=201)
def iniciar_sesion(
    presentacion_id: str,
    docente: Docente = Depends(verify_trial_active),
    db: Session = Depends(get_db),
):
    presentacion = _presentacion_del_docente_o_404(presentacion_id, docente.id_docente, db)
    codigo = _generar_codigo_unico(db)
    sesion = SesionPresentacion(
        id_presentacion=presentacion.id_presentacion,
        codigo=codigo,
        estado="esperando",
    )
    db.add(sesion)
    db.commit()
    db.refresh(sesion)
    return IniciarSesionOut(
        sesion_id=sesion.id_sesion,
        codigo=sesion.codigo,
        url_estudiante=f"https://usemaestria.co/join/{sesion.codigo}",
    )


@router.get("/join/{codigo}", response_model=SesionPublicaOut)
@limiter.limit("20/minute")
def obtener_sesion_publica(
    codigo: str, request: Request, response: Response, db: Session = Depends(get_db),
):
    """
    SIN autenticación — la usa join.html para mostrarle al estudiante a
    qué sesión se va a unir antes de pedirle el nombre. Rate-limiteado
    porque es la única superficie pública de este módulo (códigos de
    6 caracteres son adivinables por fuerza bruta sin este límite).
    """
    codigo_norm = (codigo or "").strip().upper()
    sesion = db.query(SesionPresentacion).filter(SesionPresentacion.codigo == codigo_norm).first()
    if not sesion:
        raise HTTPException(status_code=404, detail="Código de sesión no encontrado")
    presentacion = sesion.presentacion
    grupo = presentacion.grupo
    return SesionPublicaOut(
        sesion_id=sesion.id_sesion,
        codigo=sesion.codigo,
        estado=sesion.estado,
        titulo=presentacion.titulo,
        grado=grupo.grado,
        asignatura=grupo.asignatura,
    )
