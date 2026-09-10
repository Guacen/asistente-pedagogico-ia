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

import asyncio
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
from database import SessionLocal, get_db
from models import Docente, Grupo, Presentacion, RespuestaPresentacion, SesionPresentacion
from rate_limiter import limiter
from security_utils import sanitizar_texto

router = APIRouter(prefix="/api/presentaciones", tags=["presentaciones"])
logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# VALIDACIÓN DE DIAPOSITIVAS
# ═══════════════════════════════════════════════════════════════

TIPOS_INTERACCION = frozenset({"multiple", "poll", "nube", "verdadero_falso"})
TIPOS_VALIDOS = frozenset({"contenido"}) | TIPOS_INTERACCION

# "Preguntas" (SPRINT 2) = interacciones con respuesta correcta que cuentan
# para el conteo n_preguntas que el docente configura. "poll"/"nube" siguen
# soportados (presentaciones viejas ya guardadas pueden tenerlos) pero el
# prompt de generación ya no los pide — sólo se estructura de datos queda
# preparada para sumar "respuesta_corta"/"ordenar_emparejar" más adelante,
# sin implementarlos todavía.
TIPOS_PREGUNTA_SOPORTADOS = frozenset({"multiple", "verdadero_falso"})

# Catálogo cerrado de diagramas SVG (SPRINT 2, Parte C) — la IA elige uno
# de estos tipos para una diapositiva de contenido; cualquier otro valor
# (o datos con forma inesperada) se descarta sin romper la diapositiva.
CATALOGO_DIAGRAMAS = frozenset({
    "fuerzas", "ciclo", "linea_tiempo", "comparacion", "jerarquia", "proceso",
})
_DIRECCIONES_FUERZA = frozenset({"arriba", "abajo", "izquierda", "derecha"})


def _texto_seguro(valor, max_len: int) -> str:
    """
    Coerciona cualquier valor a un string sanitizado de una sola línea/
    párrafo (título, pregunta, instrucción, notas). Si el LLM devuelve una
    lista donde se esperaba texto plano, la une con espacios en vez de
    dejar que str(lista) produzca literalmente "['a', 'b']" en pantalla
    (bug reportado en clase real — corchetes y comillas visibles).
    """
    if isinstance(valor, list):
        valor = " ".join(str(v) for v in valor if v is not None)
    return sanitizar_texto(str(valor or "").strip(), max_len) or ""


def _texto_o_lista(valor, max_len_item: int, max_items: int = 8):
    """
    Normaliza un campo que el LLM a veces devuelve como string y a veces
    como lista de strings (viñetas) — el prompt pide "cuerpo: explicación
    en máx 4 puntos concisos", lo cual empuja al modelo a responder con
    un array en vez de un párrafo. Sin esto, str(lista) guardaba
    literalmente "['a', 'b']" en la DB (bug reportado en clase real: el
    docente veía corchetes y comillas en la diapositiva proyectada).

    Devuelve una lista de strings sanitizados si `valor` ya es lista, o
    si es un string que en realidad serializa un array JSON válido
    (defensa extra por si el LLM anida el array como string); o un
    string sanitizado en cualquier otro caso. El frontend decide cómo
    renderizar según el tipo (viñetas vs párrafo).
    """
    if isinstance(valor, str):
        texto = valor.strip()
        if texto.startswith("[") and texto.endswith("]"):
            try:
                parseado = json.loads(texto)
            except Exception:
                parseado = None
            if isinstance(parseado, list):
                valor = parseado

    if isinstance(valor, list):
        items = [sanitizar_texto(str(v), max_len_item) or "" for v in valor if v is not None]
        return [i for i in items if i][:max_items]
    return sanitizar_texto(str(valor or "").strip(), max_len_item) or ""


def _validar_diagrama(raw) -> Optional[dict]:
    """
    Valida el diagrama SVG opcional de una diapositiva de contenido
    (SPRINT 2, Parte C) contra el catálogo cerrado. Nunca levanta
    excepción — cualquier forma inesperada (tipo desconocido, datos
    incompletos, tipos de dato incorrectos) devuelve None y la
    diapositiva simplemente se muestra sin gráfico. La IA nunca debe
    poder romper la presentación por proponer un diagrama malformado.
    """
    try:
        if not isinstance(raw, dict):
            return None
        tipo = raw.get("tipo")
        if tipo not in CATALOGO_DIAGRAMAS:
            return None
        datos = raw.get("datos")
        if not isinstance(datos, dict):
            return None

        if tipo == "fuerzas":
            objeto = _texto_seguro(datos.get("objeto"), 100)
            fuerzas_raw = datos.get("fuerzas")
            if not objeto or not isinstance(fuerzas_raw, list):
                return None
            fuerzas = []
            for f in fuerzas_raw:
                if not isinstance(f, dict):
                    continue
                nombre = _texto_seguro(f.get("nombre"), 50)
                direccion = f.get("direccion")
                if not nombre or direccion not in _DIRECCIONES_FUERZA:
                    continue
                magnitud = f.get("magnitud")
                magnitud = int(magnitud) if isinstance(magnitud, (int, float)) else 3
                magnitud = max(1, min(5, magnitud))
                fuerzas.append({"nombre": nombre, "direccion": direccion, "magnitud": magnitud})
            if not fuerzas:
                return None
            return {"tipo": "fuerzas", "datos": {"objeto": objeto, "fuerzas": fuerzas[:6]}}

        if tipo == "ciclo":
            pasos = [p for p in (_texto_seguro(p, 80) for p in (datos.get("pasos") or []) if p is not None) if p][:6]
            if len(pasos) < 3:
                return None
            return {"tipo": "ciclo", "datos": {"pasos": pasos}}

        if tipo == "linea_tiempo":
            eventos_raw = datos.get("eventos")
            if not isinstance(eventos_raw, list):
                return None
            eventos = []
            for e in eventos_raw:
                if not isinstance(e, dict):
                    continue
                etiqueta = _texto_seguro(e.get("etiqueta"), 40)
                texto = _texto_seguro(e.get("texto"), 120)
                if not etiqueta or not texto:
                    continue
                eventos.append({"etiqueta": etiqueta, "texto": texto})
            if len(eventos) < 2:
                return None
            return {"tipo": "linea_tiempo", "datos": {"eventos": eventos[:6]}}

        if tipo == "comparacion":
            titulo_izq = _texto_seguro(datos.get("titulo_izquierda"), 60)
            titulo_der = _texto_seguro(datos.get("titulo_derecha"), 60)
            items_izq = [i for i in (_texto_seguro(i, 100) for i in (datos.get("items_izquierda") or []) if i is not None) if i][:5]
            items_der = [i for i in (_texto_seguro(i, 100) for i in (datos.get("items_derecha") or []) if i is not None) if i][:5]
            if not titulo_izq or not titulo_der or not items_izq or not items_der:
                return None
            return {
                "tipo": "comparacion",
                "datos": {
                    "titulo_izquierda": titulo_izq, "items_izquierda": items_izq,
                    "titulo_derecha": titulo_der, "items_derecha": items_der,
                },
            }

        if tipo == "jerarquia":
            raiz = _texto_seguro(datos.get("raiz"), 80)
            hijos = [h for h in (_texto_seguro(h, 60) for h in (datos.get("hijos") or []) if h is not None) if h][:6]
            if not raiz or len(hijos) < 2:
                return None
            return {"tipo": "jerarquia", "datos": {"raiz": raiz, "hijos": hijos}}

        if tipo == "proceso":
            pasos = [p for p in (_texto_seguro(p, 80) for p in (datos.get("pasos") or []) if p is not None) if p][:6]
            if len(pasos) < 2:
                return None
            return {"tipo": "proceso", "datos": {"pasos": pasos}}
    except Exception:
        logger.warning("Error inesperado validando diagrama — se descarta.", exc_info=True)
        return None

    return None


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
            titulo = _texto_seguro(item.get("titulo"), 200)
            cuerpo = _texto_o_lista(item.get("cuerpo"), 400, 8)
            if not titulo or not cuerpo:
                continue
            slide = {
                "tipo": "contenido",
                "titulo": titulo,
                "cuerpo": cuerpo,
                "notas_docente": _texto_seguro(item.get("notas_docente"), 1000),
            }
            diagrama = _validar_diagrama(item.get("diagrama"))
            if diagrama is not None:
                slide["diagrama"] = diagrama
            limpias.append(slide)

        elif tipo == "verdadero_falso":
            pregunta = _texto_seguro(item.get("pregunta"), 500)
            if not pregunta:
                continue
            correcta = item.get("correcta")
            if not isinstance(correcta, int) or correcta not in (0, 1):
                correcta = 0
            tiempo_s = item.get("tiempo_s")
            tiempo_s = int(tiempo_s) if isinstance(tiempo_s, (int, float)) and tiempo_s > 0 else 15
            puntos = item.get("puntos")
            puntos = int(puntos) if isinstance(puntos, (int, float)) and puntos > 0 else 100
            limpias.append({
                "tipo": "verdadero_falso",
                "pregunta": pregunta,
                # Fijo a propósito — nunca confiar en que la IA mande
                # exactamente estas dos opciones en el orden correcto.
                "opciones": ["Verdadero", "Falso"],
                "correcta": correcta,
                "tiempo_s": tiempo_s,
                "puntos": puntos,
            })

        elif tipo == "multiple":
            pregunta = _texto_seguro(item.get("pregunta"), 500)
            opciones_raw = item.get("opciones")
            if not pregunta or not isinstance(opciones_raw, list) or len(opciones_raw) < 2:
                continue
            opciones = [_texto_seguro(o, 200) for o in opciones_raw][:6]
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
            pregunta = _texto_seguro(item.get("pregunta"), 500)
            opciones_raw = item.get("opciones")
            if not pregunta or not isinstance(opciones_raw, list) or len(opciones_raw) < 2:
                continue
            limpias.append({
                "tipo": "poll",
                "pregunta": pregunta,
                "opciones": [_texto_seguro(o, 200) for o in opciones_raw][:6],
            })

        elif tipo == "nube":
            instruccion = _texto_seguro(item.get("instruccion"), 500)
            if not instruccion:
                continue
            limpias.append({"tipo": "nube", "instruccion": instruccion})

    return limpias


# ═══════════════════════════════════════════════════════════════
# GENERACIÓN CON IA
# ═══════════════════════════════════════════════════════════════

_CATALOGO_DIAGRAMAS_DESC = """- "fuerzas": {"objeto": "nombre del objeto", "fuerzas": [{"nombre": str, "direccion": "arriba"|"abajo"|"izquierda"|"derecha", "magnitud": 1-5}, ...]} (2 a 6 fuerzas)
- "ciclo": {"pasos": [str, ...]} (3 a 6 pasos en un ciclo circular)
- "linea_tiempo": {"eventos": [{"etiqueta": str, "texto": str}, ...]} (2 a 6 eventos)
- "comparacion": {"titulo_izquierda": str, "items_izquierda": [str, ...], "titulo_derecha": str, "items_derecha": [str, ...]} (2 a 5 items por lado)
- "jerarquia": {"raiz": str, "hijos": [str, ...]} (2 a 6 hijos)
- "proceso": {"pasos": [str, ...]} (2 a 6 pasos en secuencia lineal, no circular)"""

_TIPOS_PREGUNTA_DESC = {
    "multiple": '- "multiple": "opciones" con 4 alternativas, "correcta" = índice (0-3) de la correcta, "tiempo_s" 15-25, "puntos" (usualmente 100)',
    "verdadero_falso": '- "verdadero_falso": "correcta" = 0 (verdadero) o 1 (falso) — NO incluyas "opciones", se generan automáticamente. "tiempo_s" 10-15, "puntos" (usualmente 100)',
}

_PROMPT_TEMPLATE = """Eres un experto en pedagogía colombiana. Crea una presentación interactiva para:
- Docente: {asignatura}, grado {grado}
- Tema: {tema}
- Estudiantes: {n_estudiantes} estudiantes

Genera EXACTAMENTE {n_slides_contenido} diapositivas de tipo "contenido" y EXACTAMENTE {n_preguntas} diapositivas de pregunta, para un total de {n_total} diapositivas. Estas cantidades son un requisito estricto, no una sugerencia.
Intercala las preguntas de manera pareja a lo largo de toda la presentación — no las agrupes todas al inicio ni al final.

Para cada diapositiva de tipo "contenido" incluye:
- titulo: título claro (máx 8 palabras)
- cuerpo: explicación en máx 4 puntos concisos (array de strings, uno por punto)
- notas_docente: qué decir al proyectar (2-3 líneas)
- diagrama (OPCIONAL — inclúyelo sólo si de verdad ayuda a entender el tema, no todas las diapositivas necesitan uno): un objeto {{"tipo": "...", "datos": {{...}}}} eligiendo UNO de este catálogo cerrado (no inventes otros tipos ni otros campos):
{catalogo_diagramas}

Para cada diapositiva de PREGUNTA, usa ÚNICAMENTE estos tipos (no uses ningún otro):
{tipos_pregunta_desc}
Cada pregunta debe incluir "pregunta" (el enunciado) además de lo indicado arriba.

Responde SOLO con un array JSON válido de diapositivas, sin texto adicional."""


def _construir_prompt(
    grupo: Grupo, tema: str, n_slides_contenido: int, n_preguntas: int, tipos_pregunta: list[str],
) -> str:
    tipos_desc = "\n".join(
        _TIPOS_PREGUNTA_DESC[t] for t in tipos_pregunta if t in _TIPOS_PREGUNTA_DESC
    ) or _TIPOS_PREGUNTA_DESC["multiple"]
    return _PROMPT_TEMPLATE.format(
        asignatura=grupo.asignatura,
        grado=grupo.grado,
        tema=tema,
        n_estudiantes=grupo.cantidad_estudiantes,
        n_slides_contenido=n_slides_contenido,
        n_preguntas=n_preguntas,
        n_total=n_slides_contenido + n_preguntas,
        catalogo_diagramas=_CATALOGO_DIAGRAMAS_DESC,
        tipos_pregunta_desc=tipos_desc,
    )


def _conteo_coincide(diapositivas: list[dict], n_slides_contenido: int, n_preguntas: int) -> bool:
    if not diapositivas:
        return False
    n_contenido_real = sum(1 for d in diapositivas if d.get("tipo") == "contenido")
    n_preguntas_real = sum(1 for d in diapositivas if d.get("tipo") in TIPOS_PREGUNTA_SOPORTADOS)
    return n_contenido_real == n_slides_contenido and n_preguntas_real == n_preguntas


# SPRINT 4, Parte D — límites defensivos.
# max_tokens: con hasta 25 diapositivas + diagramas, 4096 tokens (el
# límite original, pensado para 4 diapositivas) puede truncar el JSON a
# mitad de una diapositiva — eso es "respuesta malformada" tanto como
# un error de red. 8192 da margen real sin ser excesivo.
# timeout_s: límite explícito para la llamada HTTP — sin esto, una
# generación grande podía tardar más que el timeout de proxy de
# Cloudflare (~100s) y el origen ni siquiera se enteraba de que la
# conexión ya se había cortado del otro lado.
_MAX_TOKENS_GENERACION = 8192
_TIMEOUT_GENERACION_S = 60.0


async def _un_intento_generacion_ia(
    grupo: Grupo, tema: str, n_slides_contenido: int, n_preguntas: int, tipos_pregunta: list[str],
) -> list[dict]:
    """Un único llamado al LLM + parseo + validación. _generar_diapositivas_ia
    (abajo) lo envuelve con el reintento por conteo incorrecto (que
    también cubre el caso de respuesta malformada — un JSON que no
    parsea o que valida a 0 diapositivas jamás "coincide" con el conteo
    pedido, así que dispara el mismo reintento)."""
    prompt = _construir_prompt(grupo, tema, n_slides_contenido, n_preguntas, tipos_pregunta)

    import llm
    raw = (await llm.respuesta_completa(
        system_prompt=prompt,
        messages=[{"role": "user", "content": "Generá la presentación ahora."}],
        max_tokens=_MAX_TOKENS_GENERACION,
        timeout_s=_TIMEOUT_GENERACION_S,
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


async def _generar_diapositivas_ia(
    grupo: Grupo,
    tema: str,
    n_slides_contenido: int,
    n_preguntas: int = 4,
    tipos_pregunta: Optional[list[str]] = None,
) -> list[dict]:
    """
    Llama al proveedor de IA activo (Claude/Gemini vía llm.py) y devuelve
    las diapositivas ya validadas. Nombre y firma pensados para ser
    monkeypatcheados en tests (mismo patrón que
    piar._sintetizar_conversacion_a_json) — nunca se llama a Claude real
    en la suite.

    Valida que el conteo de diapositivas de contenido/pregunta coincida
    EXACTO con lo pedido; si no, reintenta una vez (un docente que pidió
    8 diapositivas de contenido y 4 preguntas espera exactamente eso, no
    "lo que la IA decidió mandar"). Si tras el reintento el conteo sigue
    sin coincidir, devuelve [] — el endpoint lo trata como fallo (502)
    en vez de aceptar una presentación incompleta en silencio.
    """
    tipos_pregunta = tipos_pregunta or ["multiple", "verdadero_falso"]
    diapositivas: list[dict] = []
    for intento in (1, 2):
        diapositivas = await _un_intento_generacion_ia(
            grupo, tema, n_slides_contenido, n_preguntas, tipos_pregunta,
        )
        if _conteo_coincide(diapositivas, n_slides_contenido, n_preguntas):
            return diapositivas
        logger.warning(
            "Intento %d/2: conteo de diapositivas no coincide con lo pedido "
            "(grupo=%s, tema=%r, pedido=%d contenido/%d preguntas, "
            "obtenido=%d contenido/%d preguntas)",
            intento, grupo.id_grupo, tema, n_slides_contenido, n_preguntas,
            sum(1 for d in diapositivas if d.get("tipo") == "contenido"),
            sum(1 for d in diapositivas if d.get("tipo") in TIPOS_PREGUNTA_SOPORTADOS),
        )
    return []


# ═══════════════════════════════════════════════════════════════
# GENERACIÓN EN BACKGROUND (SPRINT 4)
#
# POST /generar respondía 502 desde Cloudflare con generaciones grandes
# (hasta 25 diapositivas + hasta 2 llamadas a la IA por el reintento de
# conteo) — el origen tardaba más que el timeout de proxy porque
# esperaba a Claude DENTRO del request HTTP. La fila se crea con
# estado='generando' y se responde 202 de inmediato; la generación real
# corre en background y deja la fila en 'lista' o 'error'.
#
# asyncio.create_task (no FastAPI BackgroundTasks) a propósito:
# BackgroundTasks sigue ejecutándose como parte del mismo ciclo de
# Starlette antes de que la conexión quede libre — no evita el problema
# real. create_task programa la corutina en el event loop y retorna de
# inmediato; Cloudflare recibe el 202 sin esperar nada de esto.
# ═══════════════════════════════════════════════════════════════

# Referencias vivas a las tasks en curso — sin esto, asyncio puede
# recolectar la task a mitad de ejecución (ver docs de asyncio: "Save a
# reference to the result of this function, to avoid a task disappearing
# mid-execution").
_tareas_generacion_en_curso: set = set()


def _lanzar_generacion_en_background(
    presentacion_id: str,
    grupo_id: str,
    tema: str,
    n_slides_contenido: int,
    n_preguntas: int,
    tipos_pregunta: List[str],
    docente_id: str,
) -> None:
    task = asyncio.create_task(_ejecutar_generacion_en_background(
        presentacion_id, grupo_id, tema, n_slides_contenido, n_preguntas,
        tipos_pregunta, docente_id,
    ))
    _tareas_generacion_en_curso.add(task)
    task.add_done_callback(_tareas_generacion_en_curso.discard)


async def _ejecutar_generacion_en_background(
    presentacion_id: str,
    grupo_id: str,
    tema: str,
    n_slides_contenido: int,
    n_preguntas: int,
    tipos_pregunta: List[str],
    docente_id: str,
) -> None:
    """
    Corre fuera del ciclo request/response — abre su propia sesión de DB
    (la del request original ya se cerró para cuando esto se ejecuta,
    mismo patrón que los handlers de Socket.io en presentacion_events.py).

    Contrato: SIEMPRE deja la fila en estado='lista' (con diapositivas)
    o estado='error' (con error_generacion con un mensaje real) — nunca
    la deja colgada en 'generando' para siempre, ni aunque algo explote
    de forma completamente inesperada (por eso el try/except amplio).
    """
    from socket_events import sio  # import diferido — evita ciclo de imports a nivel de módulo

    db = SessionLocal()
    try:
        grupo = db.query(Grupo).filter(Grupo.id_grupo == grupo_id).first()
        if not grupo:
            logger.error(
                "Generación en background abortada — el grupo ya no existe "
                "(presentacion_id=%s, grupo_id=%s)", presentacion_id, grupo_id,
            )
            diapositivas: list[dict] = []
            error_msg = "El grupo ya no existe."
        else:
            try:
                diapositivas = await _generar_diapositivas_ia(
                    grupo, tema, n_slides_contenido, n_preguntas, tipos_pregunta,
                )
                error_msg = None if diapositivas else (
                    "La IA no devolvió una presentación válida después de "
                    "reintentar. Intenta de nuevo."
                )
            except Exception as exc:
                logger.exception(
                    "Error inesperado en generación en background "
                    "(presentacion_id=%s, grupo=%s, tema=%r)",
                    presentacion_id, grupo_id, tema,
                )
                diapositivas = []
                error_msg = f"Error generando la presentación: {exc}"

        presentacion = db.query(Presentacion).filter(
            Presentacion.id_presentacion == presentacion_id,
        ).first()
        if not presentacion:
            logger.warning(
                "Generación en background terminó pero la presentación ya "
                "no existe (presentacion_id=%s) — probablemente se borró "
                "mientras generaba.", presentacion_id,
            )
            return

        if diapositivas:
            presentacion.diapositivas = diapositivas
            presentacion.estado = "lista"
            presentacion.error_generacion = None
        else:
            presentacion.estado = "error"
            presentacion.error_generacion = error_msg
        db.commit()

        try:
            await sio.emit(
                "presentacion:generada",
                {
                    "id_presentacion": presentacion_id,
                    "estado": presentacion.estado,
                    "error": presentacion.error_generacion,
                },
                room=f"docente_{docente_id}",
            )
        except Exception:
            # El docente igual puede enterarse vía GET /{id}/estado — no
            # queremos que un fallo de socket.io tumbe la generación ya
            # persistida.
            logger.exception(
                "No se pudo emitir presentacion:generada (presentacion_id=%s, docente=%s)",
                presentacion_id, docente_id,
            )
    finally:
        db.close()


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
    if slide.get("tipo") in TIPOS_PREGUNTA_SOPORTADOS:
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
    Conteos por opción (multiple/verdadero_falso/poll) o por palabra
    (nube) del slide ACTUAL, más un ranking acumulado de toda la sesión
    (sólo cuenta puntos de slides "pregunta" — TIPOS_PREGUNTA_SOPORTADOS
    — igual que Kahoot; "poll"/"nube" no tienen respuesta correcta).
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

    if tipo in TIPOS_PREGUNTA_SOPORTADOS or tipo == "poll":
        opciones = slide.get("opciones") or []
        conteos = {str(i): 0 for i in range(len(opciones))}
        for r in respuestas_slide:
            if r.respuesta in conteos:
                conteos[r.respuesta] += 1
        if tipo in TIPOS_PREGUNTA_SOPORTADOS:
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
        if s.get("tipo") not in TIPOS_PREGUNTA_SOPORTADOS:
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
    n_slides_contenido: int = Field(default=8, ge=4, le=15)
    n_preguntas: int = Field(default=4, ge=2, le=10)
    tipos_pregunta: List[str] = Field(default_factory=lambda: ["multiple", "verdadero_falso"])

    @field_validator("tema")
    @classmethod
    def _sanitizar_tema(cls, v: str) -> str:
        limpio = sanitizar_texto(v, 500) or ""
        if not limpio:
            raise ValueError("El tema no puede estar vacío.")
        return limpio

    @field_validator("tipos_pregunta")
    @classmethod
    def _validar_tipos_pregunta(cls, v: List[str]) -> List[str]:
        vistos: List[str] = []
        for t in v:
            if t in TIPOS_PREGUNTA_SOPORTADOS and t not in vistos:
                vistos.append(t)
        if not vistos:
            raise ValueError(
                "Debes habilitar al menos un tipo de pregunta soportado "
                "(multiple, verdadero_falso)."
            )
        return vistos


class PresentacionOut(BaseModel):
    id_presentacion: str
    id_docente: str
    id_grupo: str
    titulo: str
    tema: str
    diapositivas: list
    estado: str
    error_generacion: Optional[str] = None
    creado_en: datetime

    model_config = {"from_attributes": True}


class PresentacionEstadoOut(BaseModel):
    """Respuesta liviana para el polling de respaldo (GET /{id}/estado)
    — no trae diapositivas, sólo lo necesario para saber si ya terminó."""
    id_presentacion: str
    estado: str
    error_generacion: Optional[str] = None

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
    estado: str
    error_generacion: Optional[str] = None
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

@router.post("/generar", response_model=PresentacionOut, status_code=202)
async def generar_presentacion(
    body: GenerarPresentacionRequest,
    docente: Docente = Depends(verify_trial_active),
    db: Session = Depends(get_db),
):
    """
    SPRINT 4: responde 202 de inmediato con estado='generando' — NUNCA
    espera a la IA dentro del request HTTP. Generaciones grandes (hasta
    25 diapositivas + hasta 2 llamadas a la IA por el reintento de
    conteo) tardaban más que el timeout de proxy de Cloudflare, que
    devolvía 502 aunque el servidor siguiera vivo.

    La generación real corre en background (ver
    _ejecutar_generacion_en_background) y dejará esta misma fila en
    estado='lista' o 'error', emitiendo presentacion:generada por
    socket.io al docente. GET /{id}/estado sirve de respaldo si el
    socket no llega.
    """
    grupo = _grupo_del_docente_o_404(body.grupo_id, docente.id_docente, db)

    presentacion = Presentacion(
        id_docente=docente.id_docente,
        id_grupo=grupo.id_grupo,
        titulo=body.tema[:200],
        tema=body.tema,
        diapositivas=[],
        estado="generando",
    )
    db.add(presentacion)
    db.commit()
    db.refresh(presentacion)

    _lanzar_generacion_en_background(
        presentacion.id_presentacion,
        grupo.id_grupo,
        body.tema,
        body.n_slides_contenido,
        body.n_preguntas,
        body.tipos_pregunta,
        docente.id_docente,
    )
    return presentacion


@router.get("/{presentacion_id}/estado", response_model=PresentacionEstadoOut)
def obtener_estado_presentacion(
    presentacion_id: str,
    docente: Docente = Depends(verify_trial_active),
    db: Session = Depends(get_db),
):
    """
    Respaldo de polling para cuando el evento presentacion:generada no
    llega por socket (pestaña en background, reconexión, etc.) — el
    frontend puede consultar esto mientras estado == 'generando'.
    """
    return _presentacion_del_docente_o_404(presentacion_id, docente.id_docente, db)


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
            estado=p.estado,
            error_generacion=p.error_generacion,
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
