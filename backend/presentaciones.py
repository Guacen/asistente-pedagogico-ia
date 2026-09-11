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
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy.orm import Session

from auth import verify_trial_active
from config import settings
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
    Filtra y normaliza un array crudo de diapositivas ya generadas (todas
    a la vez, con el "tipo" final ya decidido). Descarta elementos
    malformados en vez de fallar toda la lista.

    NOTA (SPRINT 5): la generación con IA ya no llama a esta función —
    desde la generación en dos fases (ver _generar_esqueleto_ia /
    _generar_relleno_contenido_ia / _generar_relleno_pregunta_ia), cada
    diapositiva se valida individualmente a medida que llega. Esta
    función queda como utilidad de validación de un array completo
    (p.ej. para una futura importación manual de diapositivas) y sigue
    cubierta por tests — comparte los mismos helpers (_texto_seguro,
    _texto_o_lista, _validar_diagrama) que usa la generación en dos
    fases, así que su comportamiento de normalización sigue siendo
    representativo.
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
# GENERACIÓN CON IA — EN DOS FASES (SPRINT 5)
#
# La generación de una sola vez (Sprint 2/4) pedía TODAS las diapositivas
# en una única llamada — con hasta 25 diapositivas + diagramas eso
# produce payloads grandes que tardan y que, si el JSON se trunca a
# mitad de una diapositiva, invalidan la respuesta COMPLETA. Fase 1
# ("esqueleto") pide sólo tipo+título por posición — barato y rápido, y
# le muestra el índice al docente de inmediato. Fase 2 ("relleno") hace
# UNA llamada corta por diapositiva, en paralelo con un límite de
# concurrencia — si una falla, sólo esa se reintenta/marca con error;
# las demás no se ven afectadas.
# ═══════════════════════════════════════════════════════════════

_CATALOGO_DIAGRAMAS_DESC = """- "fuerzas": {"objeto": "nombre del objeto", "fuerzas": [{"nombre": str, "direccion": "arriba"|"abajo"|"izquierda"|"derecha", "magnitud": 1-5}, ...]} (2 a 6 fuerzas)
- "ciclo": {"pasos": [str, ...]} (3 a 6 pasos en un ciclo circular)
- "linea_tiempo": {"eventos": [{"etiqueta": str, "texto": str}, ...]} (2 a 6 eventos)
- "comparacion": {"titulo_izquierda": str, "items_izquierda": [str, ...], "titulo_derecha": str, "items_derecha": [str, ...]} (2 a 5 items por lado)
- "jerarquia": {"raiz": str, "hijos": [str, ...]} (2 a 6 hijos)
- "proceso": {"pasos": [str, ...]} (2 a 6 pasos en secuencia lineal, no circular)"""

# Nombres de tipo de pregunta que la IA puede elegir en fase 2 — la
# descripción es deliberadamente corta (Parte E: disciplina de payload,
# el contrato con la IA usa claves cortas y nada de relleno).
_TIPOS_PREGUNTA_DESC = {
    "multiple": '- "multiple": 4 opciones en "op", "co" = índice (0-3) de la correcta',
    "verdadero_falso": '- "verdadero_falso": "co" = 0 (verdadero) o 1 (falso), sin "op"',
}

# SPRINT 4/5, límites defensivos (Parte D/E):
# - timeout_s explícito en toda llamada — sin esto, una llamada podía
#   tardar más que el timeout de proxy de Cloudflare (~100s) y el
#   origen ni se enteraba de que la conexión ya se había cortado.
# - max_tokens dimensionado por tipo de llamada: el esqueleto es sólo
#   tipo+título por posición (barato); cada relleno es UNA diapositiva
#   (más barato todavía que la generación de una sola vez de antes).
_TIMEOUT_GENERACION_S = 60.0
_MAX_TOKENS_ESQUELETO = 2048
_MAX_TOKENS_RELLENO_CONTENIDO = 700
_MAX_TOKENS_RELLENO_PREGUNTA = 350

# Máximo de diapositivas rellenándose en simultáneo en fase 2 (Parte B) —
# evita saturar al proveedor de IA con 25 llamadas a la vez si el
# docente pide el máximo de diapositivas.
_CONCURRENCIA_MAXIMA_RELLENO = 5


def _limpiar_fences_json(raw: str) -> str:
    """El modelo a veces envuelve el JSON en ```json ... ``` pese a que
    el prompt pide 'sin texto adicional' — se lo quitamos antes de
    json.loads en vez de fallar por eso."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    return raw


# ─── FASE 1: ESQUELETO (sólo tipo + título por posición) ───────────

_PROMPT_ESQUELETO_TEMPLATE = """Eres un experto en pedagogía colombiana. Vas a planear el ÍNDICE (sin contenido todavía) de una presentación interactiva para:
- Docente: {asignatura}, grado {grado}
- Tema: {tema}
- Estudiantes: {n_estudiantes} estudiantes
{otros_temas_bloque}
Planea EXACTAMENTE {n_slides_contenido} posiciones de tipo "c" (contenido) y EXACTAMENTE {n_preguntas} posiciones de tipo "p" (pregunta), total {n_total}. Estas cantidades son un requisito estricto. Intercala las preguntas de forma pareja a lo largo de toda la secuencia — no las agrupes al inicio ni al final.

Para cada posición da SOLO su tipo y un título corto (máx 8 palabras) — nada de contenido, nada de opciones, eso se genera después.

Responde SOLO con un array JSON compacto, un objeto por posición, con claves cortas:
[{{"t": "c"|"p", "ti": "título corto"}}, ...]
Sin texto adicional."""

# SPRINT 7, Parte A: esta sección es UNA de varias secciones (temas) de
# la MISMA presentación, para el MISMO grupo (mismo grado/asignatura,
# porque una presentación tiene un solo grupo) — sin este bloque, dos
# secciones sobre temas relacionados (ej. "Fracciones" y "Decimales")
# tienden a repetir el mismo contenido introductorio.
_OTROS_TEMAS_BLOQUE_TEMPLATE = """
Esta es UNA de varias secciones de la misma presentación, para el mismo grupo. Las OTRAS secciones ya cubren estos temas — evita repetir contenido introductorio o ejemplos que probablemente ya usaron ahí:
{lista_otros_temas}
"""


def _construir_prompt_esqueleto(
    grupo: Grupo, tema: str, n_slides_contenido: int, n_preguntas: int,
    otros_temas: Optional[list[str]] = None,
) -> str:
    otros_temas_bloque = ""
    if otros_temas:
        lista = "\n".join(f"- {t}" for t in otros_temas)
        otros_temas_bloque = _OTROS_TEMAS_BLOQUE_TEMPLATE.format(lista_otros_temas=lista)
    return _PROMPT_ESQUELETO_TEMPLATE.format(
        asignatura=grupo.asignatura,
        grado=grupo.grado,
        tema=tema,
        n_estudiantes=grupo.cantidad_estudiantes,
        n_slides_contenido=n_slides_contenido,
        n_preguntas=n_preguntas,
        n_total=n_slides_contenido + n_preguntas,
        otros_temas_bloque=otros_temas_bloque,
    )


def _validar_esqueleto(bruto) -> list[dict]:
    """Cada item: {"tipo": "contenido"|"pregunta", "titulo": str}. Descarta
    cualquier elemento sin forma reconocible en vez de reventar."""
    if not isinstance(bruto, list):
        return []
    limpio: list[dict] = []
    for item in bruto:
        if not isinstance(item, dict):
            continue
        t = item.get("t")
        if t not in ("c", "p"):
            continue
        titulo = _texto_seguro(item.get("ti"), 200)
        if not titulo:
            continue
        limpio.append({"tipo": "contenido" if t == "c" else "pregunta", "titulo": titulo})
    return limpio


def _conteo_esqueleto_coincide(esqueleto: list[dict], n_slides_contenido: int, n_preguntas: int) -> bool:
    if not esqueleto:
        return False
    n_contenido = sum(1 for s in esqueleto if s["tipo"] == "contenido")
    n_preguntas_real = sum(1 for s in esqueleto if s["tipo"] == "pregunta")
    return n_contenido == n_slides_contenido and n_preguntas_real == n_preguntas


async def _un_intento_esqueleto_ia(
    grupo: Grupo, tema: str, n_slides_contenido: int, n_preguntas: int,
    otros_temas: Optional[list[str]] = None,
) -> list[dict]:
    prompt = _construir_prompt_esqueleto(grupo, tema, n_slides_contenido, n_preguntas, otros_temas)
    import llm
    raw = await llm.respuesta_completa(
        system_prompt=prompt,
        messages=[{"role": "user", "content": "Generá el índice ahora."}],
        max_tokens=_MAX_TOKENS_ESQUELETO,
        timeout_s=_TIMEOUT_GENERACION_S,
        model=settings.PRESENTACIONES_MODELO_ESQUELETO,
    )
    raw = _limpiar_fences_json(raw)
    try:
        bruto = json.loads(raw)
    except Exception:
        logger.error(
            "LLM devolvió un esqueleto no parseable como JSON (grupo=%s, "
            "tema=%r). Primeros 300 chars: %r",
            grupo.id_grupo, tema, raw[:300],
        )
        bruto = []
    return _validar_esqueleto(bruto)


async def _generar_esqueleto_ia(
    grupo: Grupo, tema: str, n_slides_contenido: int, n_preguntas: int,
    otros_temas: Optional[list[str]] = None,
) -> list[dict]:
    """
    Fase 1 completa PARA UNA SECCIÓN: pide el índice y reintenta UNA vez
    si el conteo de posiciones "contenido"/"pregunta" no coincide EXACTO
    con lo pedido (mismo criterio que la generación de una sola llamada
    en sprints anteriores). Si tras el reintento sigue sin coincidir,
    devuelve [] y ESA sección queda en estado='error' — las demás
    secciones de la presentación siguen su curso (SPRINT 7, Parte A).

    otros_temas (SPRINT 7): títulos de las OTRAS secciones de la misma
    presentación — se le pasan a la IA como contexto para que no repita
    contenido entre secciones del mismo grupo.
    """
    esqueleto: list[dict] = []
    for intento in (1, 2):
        esqueleto = await _un_intento_esqueleto_ia(grupo, tema, n_slides_contenido, n_preguntas, otros_temas)
        if _conteo_esqueleto_coincide(esqueleto, n_slides_contenido, n_preguntas):
            return esqueleto
        logger.warning(
            "Intento %d/2: conteo del esqueleto no coincide con lo pedido "
            "(grupo=%s, tema=%r, pedido=%d contenido/%d preguntas)",
            intento, grupo.id_grupo, tema, n_slides_contenido, n_preguntas,
        )
    return []


# ─── FASE 2: RELLENO (una llamada corta por diapositiva) ───────────

_PROMPT_RELLENO_CONTENIDO_TEMPLATE = """Eres un experto en pedagogía colombiana. Estás completando UNA diapositiva (posición {posicion} de {total}) de una presentación para:
- Docente: {asignatura}, grado {grado}
- Tema general: {tema}
- Título de esta diapositiva: {titulo}

Genera SOLO el contenido de esta diapositiva:
- "cu": explicación en máx 4 puntos concisos (array de strings)
- "nd": notas para el docente, qué decir al proyectar (2-3 líneas)
- "dg" (OPCIONAL — sólo si de verdad ayuda a entender el tema): un objeto {{"tipo": "...", "datos": {{...}}}} eligiendo UNO de este catálogo cerrado (no inventes otros tipos ni otros campos):
{catalogo_diagramas}

Responde SOLO con un objeto JSON compacto: {{"cu": [...], "nd": "...", "dg": {{...}}}} (dg es opcional). Sin texto adicional."""

_PROMPT_RELLENO_PREGUNTA_TEMPLATE = """Eres un experto en pedagogía colombiana. Estás completando UNA pregunta de evaluación tipo Kahoot (posición {posicion} de {total}) para:
- Docente: {asignatura}, grado {grado}
- Tema general: {tema}
- Título de esta pregunta: {titulo}

Elige UNO de estos tipos de pregunta y complétalo:
{tipos_pregunta_desc}

Responde SOLO con un objeto JSON compacto:
- Para "multiple": {{"ti": "multiple", "pr": "enunciado", "op": ["a","b","c","d"], "co": 0-3}}
- Para "verdadero_falso": {{"ti": "verdadero_falso", "pr": "enunciado", "co": 0 (verdadero) o 1 (falso)}}
Sin texto adicional."""


async def _generar_relleno_contenido_ia(grupo: Grupo, tema: str, titulo: str, posicion: int, total: int) -> Optional[dict]:
    """Un único intento de rellenar UNA diapositiva de contenido — SIN
    reintento propio, el reintento por-diapositiva vive en el
    orquestador (_rellenar_slide_con_reintento) para que el límite de
    concurrencia lo controle un único lugar. Devuelve None si la
    respuesta no es válida (JSON malformado o sin "cu")."""
    prompt = _PROMPT_RELLENO_CONTENIDO_TEMPLATE.format(
        asignatura=grupo.asignatura, grado=grupo.grado, tema=tema,
        titulo=titulo, posicion=posicion, total=total,
        catalogo_diagramas=_CATALOGO_DIAGRAMAS_DESC,
    )
    import llm
    raw = await llm.respuesta_completa(
        system_prompt=prompt,
        messages=[{"role": "user", "content": "Completá esta diapositiva ahora."}],
        max_tokens=_MAX_TOKENS_RELLENO_CONTENIDO,
        timeout_s=_TIMEOUT_GENERACION_S,
        model=settings.PRESENTACIONES_MODELO_CONTENIDO,
    )
    raw = _limpiar_fences_json(raw)
    try:
        bruto = json.loads(raw)
    except Exception:
        logger.error("Relleno de contenido no parseable (titulo=%r). raw=%r", titulo, raw[:300])
        return None
    if not isinstance(bruto, dict):
        return None

    cuerpo = _texto_o_lista(bruto.get("cu"), 400, 8)
    if not cuerpo:
        return None
    slide = {
        "tipo": "contenido",
        "titulo": titulo,
        "cuerpo": cuerpo,
        "notas_docente": _texto_seguro(bruto.get("nd"), 1000),
    }
    diagrama = _validar_diagrama(bruto.get("dg"))
    if diagrama is not None:
        slide["diagrama"] = diagrama
    return slide


async def _generar_relleno_pregunta_ia(
    grupo: Grupo, tema: str, titulo: str, posicion: int, total: int, tipos_pregunta: list[str],
    tiempo_pregunta_s: int = 20,
) -> Optional[dict]:
    """Análogo a _generar_relleno_contenido_ia para una posición de
    pregunta. Si la IA elige un tipo que el docente no habilitó, cae al
    primer tipo habilitado en vez de descartar la diapositiva entera."""
    tipos_desc = "\n".join(
        _TIPOS_PREGUNTA_DESC[t] for t in tipos_pregunta if t in _TIPOS_PREGUNTA_DESC
    ) or _TIPOS_PREGUNTA_DESC["multiple"]
    prompt = _PROMPT_RELLENO_PREGUNTA_TEMPLATE.format(
        asignatura=grupo.asignatura, grado=grupo.grado, tema=tema,
        titulo=titulo, posicion=posicion, total=total,
        tipos_pregunta_desc=tipos_desc,
    )
    import llm
    raw = await llm.respuesta_completa(
        system_prompt=prompt,
        messages=[{"role": "user", "content": "Completá esta pregunta ahora."}],
        max_tokens=_MAX_TOKENS_RELLENO_PREGUNTA,
        timeout_s=_TIMEOUT_GENERACION_S,
        model=settings.PRESENTACIONES_MODELO_CONTENIDO,
    )
    raw = _limpiar_fences_json(raw)
    try:
        bruto = json.loads(raw)
    except Exception:
        logger.error("Relleno de pregunta no parseable (titulo=%r). raw=%r", titulo, raw[:300])
        return None
    if not isinstance(bruto, dict):
        return None

    tipo = bruto.get("ti")
    tipos_permitidos = [t for t in tipos_pregunta if t in TIPOS_PREGUNTA_SOPORTADOS]
    if tipo not in tipos_permitidos:
        tipo = tipos_permitidos[0] if tipos_permitidos else "multiple"

    pregunta = _texto_seguro(bruto.get("pr"), 500)
    if not pregunta:
        return None

    if tipo == "verdadero_falso":
        correcta = bruto.get("co")
        correcta = correcta if isinstance(correcta, int) and correcta in (0, 1) else 0
        return {
            "tipo": "verdadero_falso",
            "pregunta": pregunta,
            "opciones": ["Verdadero", "Falso"],
            "correcta": correcta,
            "tiempo_s": tiempo_pregunta_s,
            "puntos": 100,
        }

    opciones_raw = bruto.get("op")
    if not isinstance(opciones_raw, list) or len(opciones_raw) < 2:
        return None
    opciones = [_texto_seguro(o, 200) for o in opciones_raw][:6]
    correcta = bruto.get("co")
    correcta = correcta if isinstance(correcta, int) and 0 <= correcta < len(opciones) else 0
    return {
        "tipo": "multiple",
        "pregunta": pregunta,
        "opciones": opciones,
        "correcta": correcta,
        "tiempo_s": tiempo_pregunta_s,
        "puntos": 100,
    }


async def _rellenar_slide_con_reintento(
    grupo: Grupo, tema: str, stub: dict, index: int, total: int,
    tipos_pregunta: list[str], semaforo: "asyncio.Semaphore",
    tiempo_pregunta_s: int = 20,
) -> dict:
    """
    Rellena UNA diapositiva del esqueleto, respetando el límite de
    concurrencia (el semáforo se toma para los DOS intentos, no sólo el
    primero — dos intentos de la misma diapositiva siguen contando como
    1 hueco de concurrencia). Si el primer intento falla (excepción o
    respuesta inválida), reintenta UNA sola vez; si el segundo también
    falla, devuelve un slide "tipo": "error" en vez de levantar — una
    diapositiva rota nunca debe tumbar las demás (SPRINT 5, Parte B).
    """
    async with semaforo:
        for intento in (1, 2):
            try:
                if stub["tipo"] == "contenido":
                    slide = await _generar_relleno_contenido_ia(grupo, tema, stub["titulo"], index + 1, total)
                else:
                    slide = await _generar_relleno_pregunta_ia(
                        grupo, tema, stub["titulo"], index + 1, total, tipos_pregunta,
                        tiempo_pregunta_s,
                    )
            except Exception:
                logger.exception(
                    "Intento %d/2 de rellenar diapositiva %d falló con excepción (titulo=%r)",
                    intento, index, stub["titulo"],
                )
                slide = None
            if slide is not None:
                return slide
            logger.warning(
                "Intento %d/2 de rellenar diapositiva %d devolvió respuesta inválida (titulo=%r)",
                intento, index, stub["titulo"],
            )
    return {
        "tipo": "error",
        "titulo": stub["titulo"],
        "mensaje": "No se pudo generar esta diapositiva. Podés regenerar la presentación.",
    }


# ═══════════════════════════════════════════════════════════════
# GENERACIÓN EN BACKGROUND (SPRINT 4, extendido en SPRINT 5 a dos fases)
#
# POST /generar respondía 502 desde Cloudflare con generaciones grandes
# — el origen tardaba más que el timeout de proxy porque esperaba a
# Claude DENTRO del request HTTP. La fila se crea con estado='generando'
# y se responde 202 de inmediato; la generación real corre en background
# y deja la fila en 'lista' o 'error'.
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
    tipos_pregunta: List[str],
    docente_id: str,
) -> None:
    task = asyncio.create_task(_ejecutar_generacion_en_background(
        presentacion_id, grupo_id, tipos_pregunta, docente_id,
    ))
    _tareas_generacion_en_curso.add(task)
    task.add_done_callback(_tareas_generacion_en_curso.discard)


async def _emitir_evento_presentacion(evento: str, payload: dict, docente_id: str, contexto: str) -> None:
    """Emite un evento al docente dueño sin dejar que un fallo de
    socket.io tumbe la generación ya persistida en DB — el docente
    igual puede enterarse vía GET /{id} o /{id}/estado (polling)."""
    from socket_events import sio  # import diferido — evita ciclo de imports a nivel de módulo
    try:
        await sio.emit(evento, payload, room=f"docente_{docente_id}")
    except Exception:
        logger.exception("No se pudo emitir %s (%s)", evento, contexto)


async def _marcar_error_y_emitir(db: Session, presentacion_id: str, docente_id: str, mensaje: str) -> None:
    presentacion = db.query(Presentacion).filter(
        Presentacion.id_presentacion == presentacion_id,
    ).first()
    if not presentacion:
        logger.warning(
            "Generación en background terminó en error pero la presentación "
            "ya no existe (presentacion_id=%s).", presentacion_id,
        )
        return
    presentacion.estado = "error"
    presentacion.error_generacion = mensaje
    db.commit()
    await _emitir_evento_presentacion(
        "presentacion:generada",
        {"id_presentacion": presentacion_id, "estado": "error", "error": mensaje},
        docente_id, f"presentacion_id={presentacion_id}",
    )


def _marcar_estado_seccion(presentacion: Presentacion, seccion_index: int, estado: str, error_generacion: Optional[str] = None) -> None:
    """Reasigna presentacion.secciones ENTERO (no in-place) para que
    SQLAlchemy detecte el cambio en la columna JSON — mismo patrón que
    presentacion.diapositivas en todo este módulo."""
    secciones = list(presentacion.secciones)
    seccion = dict(secciones[seccion_index])
    seccion["estado"] = estado
    seccion["error_generacion"] = error_generacion
    secciones[seccion_index] = seccion
    presentacion.secciones = secciones


async def _ejecutar_generacion_seccion(
    db: Session,
    presentacion_id: str,
    grupo: Grupo,
    seccion_index: int,
    tipos_pregunta: List[str],
    docente_id: str,
    semaforo: "asyncio.Semaphore",
) -> None:
    """
    Genera UNA sección completa (fase 1 + fase 2) dentro de su rango ya
    reservado en presentacion.diapositivas[inicio+1 : fin+1] (inicio es
    la diapositiva separadora, ya persistida sin IA desde el endpoint).
    NUNCA propaga una excepción — si esta sección falla, sólo ELLA
    queda en estado='error'; el asyncio.gather del llamador no debe
    verse afectado (SPRINT 7, Parte A: "si una sección falla, las
    demás siguen").
    """
    try:
        presentacion = db.query(Presentacion).filter(
            Presentacion.id_presentacion == presentacion_id,
        ).first()
        if not presentacion:
            return
        seccion = presentacion.secciones[seccion_index]
        tema = seccion["tema"]
        n_slides_contenido = seccion["n_slides_contenido"]
        n_preguntas = seccion["n_preguntas"]
        offset = seccion["inicio"] + 1  # +1 salta la separadora

        # Contexto de las OTRAS secciones (mismo grupo → mismo grado/
        # asignatura siempre) para que la IA no repita contenido.
        otros_temas = [
            s["tema"] for i, s in enumerate(presentacion.secciones) if i != seccion_index
        ]

        try:
            esqueleto = await _generar_esqueleto_ia(
                grupo, tema, n_slides_contenido, n_preguntas, otros_temas,
            )
        except Exception as exc:
            logger.exception(
                "Error inesperado generando el esqueleto de la sección %d "
                "(presentacion_id=%s, tema=%r)", seccion_index, presentacion_id, tema,
            )
            esqueleto = []
            error_esqueleto = f"Error generando la sección: {exc}"
        else:
            error_esqueleto = None if esqueleto else (
                "La IA no devolvió un índice válido para esta sección después de reintentar."
            )

        if not esqueleto:
            # Marca TODA la ventana de la sección como error — nunca un
            # spinner sin información (mismo criterio que una
            # diapositiva individual rota, sólo que acá aplica a la
            # sección completa).
            actuales = list(presentacion.diapositivas)
            for i in range(offset, offset + n_slides_contenido + n_preguntas):
                actuales[i] = {"tipo": "error", "titulo": tema, "mensaje": error_esqueleto}
            presentacion.diapositivas = actuales
            _marcar_estado_seccion(presentacion, seccion_index, "error", error_esqueleto)
            db.commit()
            await _emitir_evento_presentacion(
                "presentacion:seccion_error",
                {"id_presentacion": presentacion_id, "seccion_index": seccion_index, "error": error_esqueleto},
                docente_id, f"presentacion_id={presentacion_id}, seccion={seccion_index}",
            )
            return

        total = len(esqueleto)
        pendientes = [{"tipo": "pendiente", "titulo": s["titulo"]} for s in esqueleto]
        actuales = list(presentacion.diapositivas)
        actuales[offset:offset + total] = pendientes
        presentacion.diapositivas = actuales
        db.commit()
        await _emitir_evento_presentacion(
            "presentacion:esqueleto",
            {
                "id_presentacion": presentacion_id, "seccion_index": seccion_index,
                "offset": offset, "esqueleto": pendientes,
            },
            docente_id, f"presentacion_id={presentacion_id}, seccion={seccion_index}",
        )

        async def _rellenar_y_persistir(pos_local: int, stub: dict) -> None:
            index = offset + pos_local
            slide = await _rellenar_slide_con_reintento(
                grupo, tema, stub, pos_local, total, tipos_pregunta, semaforo,
                presentacion.tiempo_pregunta_s,
            )
            actuales_slide = list(presentacion.diapositivas)
            actuales_slide[index] = slide
            presentacion.diapositivas = actuales_slide
            db.commit()
            await _emitir_evento_presentacion(
                "presentacion:slide_lista",
                {"id_presentacion": presentacion_id, "index": index, "slide": slide},
                docente_id, f"presentacion_id={presentacion_id}, index={index}",
            )

        await asyncio.gather(*[
            _rellenar_y_persistir(i, stub) for i, stub in enumerate(esqueleto)
        ])

        _marcar_estado_seccion(presentacion, seccion_index, "lista")
        db.commit()
    except Exception:
        # Red de seguridad — cualquier cosa no prevista arriba (p.ej.
        # error de DB a mitad de fase 2) tampoco debe dejar la sección
        # colgada ni, peor, tumbar las demás secciones vía el gather.
        logger.exception(
            "Error inesperado no capturado generando la sección %d "
            "(presentacion_id=%s)", seccion_index, presentacion_id,
        )
        try:
            presentacion = db.query(Presentacion).filter(
                Presentacion.id_presentacion == presentacion_id,
            ).first()
            if presentacion:
                _marcar_estado_seccion(presentacion, seccion_index, "error", "Error inesperado generando esta sección.")
                db.commit()
        except Exception:
            logger.exception(
                "No se pudo ni siquiera marcar el error de la sección %d "
                "(presentacion_id=%s)", seccion_index, presentacion_id,
            )


async def _ejecutar_generacion_en_background(
    presentacion_id: str,
    grupo_id: str,
    tipos_pregunta: List[str],
    docente_id: str,
) -> None:
    """
    Corre fuera del ciclo request/response — abre su propia sesión de DB
    (la del request original ya se cerró para cuando esto se ejecuta,
    mismo patrón que los handlers de Socket.io en presentacion_events.py).

    SPRINT 7, Parte A: cada sección (tema) de presentacion.secciones se
    genera en su PROPIA task de asyncio.gather — corren en paralelo
    entre sí, cada una con su fase 1 (esqueleto) + fase 2 (relleno
    concurrente, mismo límite de concurrencia SPRINT 5 pero compartido
    entre TODAS las secciones, no uno por sección — evita saturar al
    proveedor con 5 secciones × 5 rellenos = 25 llamadas a la vez).
    _ejecutar_generacion_seccion nunca propaga una excepción, así que
    el fallo de una sección nunca cancela ni afecta a las demás.

    Contrato: SIEMPRE deja la fila en estado='lista' (si al menos una
    sección quedó lista) o estado='error' (si TODAS fallaron) — nunca
    la deja colgada en 'generando' para siempre.
    """
    db = SessionLocal()
    try:
        grupo = db.query(Grupo).filter(Grupo.id_grupo == grupo_id).first()
        if not grupo:
            logger.error(
                "Generación en background abortada — el grupo ya no existe "
                "(presentacion_id=%s, grupo_id=%s)", presentacion_id, grupo_id,
            )
            await _marcar_error_y_emitir(db, presentacion_id, docente_id, "El grupo ya no existe.")
            return

        presentacion = db.query(Presentacion).filter(
            Presentacion.id_presentacion == presentacion_id,
        ).first()
        if not presentacion:
            logger.warning(
                "Generación en background abortada — la presentación ya no "
                "existe (presentacion_id=%s).", presentacion_id,
            )
            return

        n_secciones = len(presentacion.secciones)
        semaforo = asyncio.Semaphore(_CONCURRENCIA_MAXIMA_RELLENO)
        await asyncio.gather(*[
            _ejecutar_generacion_seccion(
                db, presentacion_id, grupo, i, tipos_pregunta, docente_id, semaforo,
            )
            for i in range(n_secciones)
        ])

        presentacion = db.query(Presentacion).filter(
            Presentacion.id_presentacion == presentacion_id,
        ).first()
        if not presentacion:
            return
        estados_seccion = [s.get("estado") for s in presentacion.secciones]
        todas_fallaron = bool(estados_seccion) and all(e == "error" for e in estados_seccion)
        if todas_fallaron:
            presentacion.estado = "error"
            # Mensajes reales de cada sección — no un genérico — para
            # poder diagnosticar sin depender de los logs de Railway
            # (mismo criterio que SPRINT 4, Parte B).
            errores = [s.get("error_generacion") for s in presentacion.secciones if s.get("error_generacion")]
            presentacion.error_generacion = (
                "No se pudo generar ninguna sección: " + "; ".join(errores)
                if errores else "No se pudo generar ninguna sección. Intenta de nuevo."
            )
        else:
            presentacion.estado = "lista"
            presentacion.error_generacion = None
        db.commit()
        await _emitir_evento_presentacion(
            "presentacion:generada",
            {"id_presentacion": presentacion_id, "estado": presentacion.estado, "error": presentacion.error_generacion},
            docente_id, f"presentacion_id={presentacion_id}",
        )
    except Exception as exc:
        # Red de seguridad final — cualquier cosa no prevista arriba
        # tampoco debe dejar la fila colgada en 'generando' para siempre.
        logger.exception(
            "Error inesperado no capturado en generación en background "
            "(presentacion_id=%s)", presentacion_id,
        )
        try:
            await _marcar_error_y_emitir(
                db, presentacion_id, docente_id, f"Error inesperado generando la presentación: {exc}",
            )
        except Exception:
            logger.exception(
                "No se pudo ni siquiera marcar el error final (presentacion_id=%s)",
                presentacion_id,
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


MODOS_PUNTAJE = frozenset({"competencia", "inclusivo"})
FACTORES_TIEMPO_PIAR_SOPORTADOS = frozenset({1.25, 1.5, 2.0})


def _estudiante_tiene_piar(db: Session, id_grupo: str, nombre_estudiante: str) -> bool:
    """
    SPRINT 6 — el estudiante en una sesión en vivo no tiene cuenta, sólo
    un nombre libre; lo único que podemos hacer es emparejarlo (exacto,
    sin importar mayúsculas/espacios extremos) contra el roster real del
    grupo (Estudiante.codigo_estudiante, que pese al nombre histórico del
    campo es el nombre que usa el resto de la app — ver piar.py). Si el
    nombre no matchea ningún estudiante del grupo, se trata como sin
    PIAR — no es una fuente de verdad perfecta (cualquiera puede escribir
    cualquier nombre), pero es el mismo nivel de confianza que el resto
    del sistema de sesiones sin autenticación.
    """
    nombre_norm = (nombre_estudiante or "").strip().lower()
    if not nombre_norm:
        return False
    from sqlalchemy import func

    from models import Estudiante
    return db.query(Estudiante).filter(
        Estudiante.id_grupo == id_grupo,
        Estudiante.tiene_piar.is_(True),
        func.lower(Estudiante.codigo_estudiante) == nombre_norm,
    ).first() is not None


def _tiempo_limite_ms(presentacion: Presentacion, tiene_piar: bool) -> int:
    """
    Límite de tiempo PROPIO del estudiante — base de la presentación
    (tiempo_pregunta_s) multiplicado por factor_tiempo_piar si tiene
    PIAR. CRÍTICO (SPRINT 6, Parte B): el puntaje en modo competencia se
    calcula contra ESTE valor, nunca contra el base — así un estudiante
    con PIAR que usa proporcionalmente el mismo tiempo relativo no pierde
    puntos por el ajuste.
    """
    base_s = presentacion.tiempo_pregunta_s or 20
    factor = (presentacion.factor_tiempo_piar or 1.5) if tiene_piar else 1.0
    return int(round(base_s * factor * 1000))


def _calcular_puntos(
    modo_puntaje: str,
    es_correcta: Optional[bool],
    tiempo_respuesta_ms: Optional[int],
    tiempo_limite_ms: int,
) -> int:
    """
    SPRINT 6, Parte B — reemplaza el puntaje estilo Kahoot anterior
    (50%-100% de un `puntos` configurable por pregunta) por las dos
    fórmulas fijas que pidió el sprint:
    - inclusivo: 1000 si es correcta, sin importar el tiempo.
    - competencia: entre 500 y 1000 si es correcta, según qué fracción
      del tiempo LÍMITE del estudiante (ya ajustado por PIAR si aplica)
      usó para responder. 0 si es incorrecta, en ambos modos.
    """
    if not es_correcta:
        return 0
    if modo_puntaje == "inclusivo":
        return 1000

    tiempo = tiempo_respuesta_ms if isinstance(tiempo_respuesta_ms, (int, float)) and tiempo_respuesta_ms > 0 else 0
    limite = tiempo_limite_ms if tiempo_limite_ms and tiempo_limite_ms > 0 else 1
    # Clamp a [0, 1]: una respuesta "instantánea" (0ms) da 1.0 de fracción
    # de tiempo AHORRADO → 1000 puntos; una que agota exactamente el
    # límite (o llega tarde por latencia de red) nunca baja de 500.
    fraccion_usada = min(1.0, max(0.0, tiempo / limite))
    return round(1000 * (1 - 0.5 * fraccion_usada))


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
    al mismo slide devuelve la primera en vez de duplicar el conteo —
    IMPORTANTE: en ese caso NO se vuelve a tocar PuntajeEstudiante, para
    no duplicar puntos.

    SPRINT 6: resuelve el ajuste PIAR y calcula los puntos ACÁ (no en
    calcular_resultado) — el límite de tiempo y el puntaje quedan fijos
    en la fila de la respuesta para siempre, y el acumulado de
    PuntajeEstudiante (id_sesion, nombre_estudiante) se actualiza en el
    mismo commit. Como la clave es el nombre (no un sid de socket), un
    estudiante que se reconecta con el mismo nombre sigue sumando sobre
    la misma fila — recupera su puntaje sin ninguna lógica extra.
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
    tiempo_limite_ms = None
    puntos = 0
    if slide.get("tipo") in TIPOS_PREGUNTA_SOPORTADOS:
        es_correcta = respuesta_limpia == str(slide.get("correcta"))
        tiene_piar = _estudiante_tiene_piar(db, presentacion.id_grupo, nombre_limpio)
        tiempo_limite_ms = _tiempo_limite_ms(presentacion, tiene_piar)
        puntos = _calcular_puntos(
            presentacion.modo_puntaje, es_correcta, tiempo_respuesta_ms, tiempo_limite_ms,
        )

    respuesta = RespuestaPresentacion(
        id_sesion=sesion.id_sesion,
        slide_index=slide_index,
        nombre_estudiante=nombre_limpio,
        respuesta=respuesta_limpia,
        es_correcta=es_correcta,
        tiempo_respuesta_ms=tiempo_respuesta_ms,
        tiempo_limite_ms=tiempo_limite_ms,
        puntos_obtenidos=puntos,
    )
    db.add(respuesta)

    from models import PuntajeEstudiante
    puntaje = db.query(PuntajeEstudiante).filter(
        PuntajeEstudiante.id_sesion == sesion.id_sesion,
        PuntajeEstudiante.nombre_estudiante == nombre_limpio,
    ).first()
    if puntaje is None:
        puntaje = PuntajeEstudiante(
            id_sesion=sesion.id_sesion, nombre_estudiante=nombre_limpio,
            puntaje_acumulado=0, aciertos=0, respuestas_totales=0,
        )
        db.add(puntaje)
    puntaje.puntaje_acumulado += puntos
    puntaje.respuestas_totales += 1
    if es_correcta:
        puntaje.aciertos += 1

    db.commit()
    db.refresh(respuesta)
    return respuesta


def calcular_resultado(db: Session, sesion: SesionPresentacion, presentacion: Presentacion) -> dict:
    """
    Conteos por opción (multiple/verdadero_falso/poll) o por palabra
    (nube) del slide ACTUAL, para la distribución de barras que se
    muestra ANTES de revelar. El ranking/podio con puntajes vive en
    calcular_podio — separado a propósito (dos momentos distintos de la
    UI: "cómo respondió la clase esta pregunta" vs "cómo va el podio").
    """
    diapositivas = presentacion.diapositivas or []
    if sesion.slide_actual < 0 or sesion.slide_actual >= len(diapositivas):
        return {"conteos": {}, "correcta": None, "total_respuestas": 0}

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

    return {
        "conteos": conteos,
        "correcta": correcta,
        "total_respuestas": len(respuestas_slide),
    }


def _puntaje_acumulado_hasta(db: Session, id_sesion: str, slide_index_max: int) -> dict[str, int]:
    """Suma puntos_obtenidos por nombre_estudiante considerando sólo
    respuestas con slide_index <= slide_index_max. Se usa dos veces en
    calcular_podio (con y sin la pregunta recién cerrada) para poder
    calcular cuánto subió/bajó cada estudiante — se recalcula desde
    RespuestaPresentacion (el log completo) en vez de confiar en
    snapshots, así siempre es consistente con lo realmente persistido."""
    if slide_index_max < 0:
        return {}
    filas = db.query(
        RespuestaPresentacion.nombre_estudiante, RespuestaPresentacion.puntos_obtenidos,
    ).filter(
        RespuestaPresentacion.id_sesion == id_sesion,
        RespuestaPresentacion.slide_index <= slide_index_max,
    ).all()
    totales: dict[str, int] = {}
    for nombre, puntos in filas:
        totales[nombre] = totales.get(nombre, 0) + (puntos or 0)
    return totales


def calcular_podio(db: Session, sesion: SesionPresentacion, presentacion: Presentacion) -> dict:
    """
    SPRINT 6, Parte C — ranking completo ordenado por puntaje acumulado,
    con `cambio_posicion` (positivo = subió, negativo = bajó, 0 = igual
    o primera vez que puntúa) respecto a como estaba ANTES de la
    pregunta que se acaba de cerrar (sesion.slide_actual).
    """
    idx = sesion.slide_actual
    actual = _puntaje_acumulado_hasta(db, sesion.id_sesion, idx)
    anterior = _puntaje_acumulado_hasta(db, sesion.id_sesion, idx - 1)

    orden_actual = sorted(actual.items(), key=lambda kv: kv[1], reverse=True)
    posiciones_anteriores = {
        nombre: pos for pos, (nombre, _) in enumerate(
            sorted(anterior.items(), key=lambda kv: kv[1], reverse=True),
        )
    }

    ranking = []
    for pos, (nombre, puntos) in enumerate(orden_actual):
        pos_anterior = posiciones_anteriores.get(nombre)
        cambio = (pos_anterior - pos) if pos_anterior is not None else 0
        ranking.append({"nombre": nombre, "puntaje_acumulado": puntos, "cambio_posicion": cambio})

    return {"ranking": ranking, "podio_top5": ranking[:5]}


# ═══════════════════════════════════════════════════════════════
# SECCIONES (SPRINT 7) — límites, duración estimada, helpers
# ═══════════════════════════════════════════════════════════════

MAX_SECCIONES = 5
MAX_DIAPOSITIVAS_TOTAL = 60

# Parte B — la misma fórmula/constantes se replican en JS
# (grupo-panel.html) para actualizar el modal en vivo sin pegarle al
# backend en cada tick del slider; viven acá también para poder
# testear la fórmula y para que la validación del request comparta la
# misma constante de tope.
SEGUNDOS_POR_DIAPOSITIVA_CONTENIDO = 90
SEGUNDOS_EXTRA_POR_PREGUNTA = 20


def _duracion_estimada_s(n_contenido_total: int, n_preguntas_total: int, tiempo_pregunta_s: int) -> int:
    """duración = (n_contenido * 90s) + (n_preguntas * (tiempo_pregunta + 20s))
    — sumando TODAS las secciones (el docente piensa en la clase
    completa, no sección por sección)."""
    return (
        n_contenido_total * SEGUNDOS_POR_DIAPOSITIVA_CONTENIDO
        + n_preguntas_total * (tiempo_pregunta_s + SEGUNDOS_EXTRA_POR_PREGUNTA)
    )


def _clasificar_duracion(minutos: float) -> str:
    """Semáforo puramente informativo (SPRINT 7, Parte B) — NUNCA
    bloquea la generación, sólo orienta: 'verde' hasta 35 min, 'ambar'
    36-50 min, 'rojo' más de 50 min ('considera dividir en dos
    sesiones')."""
    if minutos <= 35:
        return "verde"
    if minutos <= 50:
        return "ambar"
    return "rojo"


def _seccion_de_slide(presentacion: Presentacion, slide_index: int) -> Optional[dict]:
    """Sección (metadata de presentacion.secciones) a la que pertenece
    slide_index, o None si no matchea ninguna — nunca revienta aunque
    `secciones` esté vacío (presentación no migrada todavía, caso que
    no debería darse en la práctica tras la migración de este sprint)."""
    for seccion in presentacion.secciones or []:
        if seccion.get("inicio", -1) <= slide_index <= seccion.get("fin", -2):
            return seccion
    return None


def _es_ultima_slide_de_seccion(presentacion: Presentacion, slide_index: int) -> bool:
    """True si slide_index es la última diapositiva de su sección — el
    punto en el que se muestra el podio PARCIAL de esa sección (SPRINT
    7, Parte C), además del podio de la pregunta individual."""
    seccion = _seccion_de_slide(presentacion, slide_index)
    return seccion is not None and seccion.get("fin") == slide_index


# ═══════════════════════════════════════════════════════════════
# SCHEMAS
# ═══════════════════════════════════════════════════════════════

class SeccionRequest(BaseModel):
    """SPRINT 7, Parte A — un tema = una sección. El docente define
    cantidad de contenido/preguntas POR sección; el máximo de contenido
    subió de 15 a 25 (Parte B) porque ahora el límite real es la
    duración total estimada, no un tope arbitrario por sección."""
    tema: str = Field(min_length=1, max_length=500)
    n_slides_contenido: int = Field(default=8, ge=4, le=25)
    n_preguntas: int = Field(default=4, ge=2, le=10)

    @field_validator("tema")
    @classmethod
    def _sanitizar_tema(cls, v: str) -> str:
        limpio = sanitizar_texto(v, 500) or ""
        if not limpio:
            raise ValueError("El tema no puede estar vacío.")
        return limpio

    @model_validator(mode="after")
    def _validar_preguntas_no_superan_contenido(self):
        if self.n_preguntas > self.n_slides_contenido:
            raise ValueError(
                "La cantidad de preguntas no puede superar la cantidad de "
                "diapositivas de contenido de la misma sección."
            )
        return self


class GenerarPresentacionRequest(BaseModel):
    grupo_id: str
    # SPRINT 7, Parte A: 1 a 5 secciones — una presentación de un solo
    # tema sigue siendo válida, es simplemente `secciones` con 1 item.
    secciones: List[SeccionRequest] = Field(min_length=1, max_length=MAX_SECCIONES)
    tipos_pregunta: List[str] = Field(default_factory=lambda: ["multiple", "verdadero_falso"])
    # SPRINT 6, Parte B — controles de puntaje del modal de creación
    # (compartidos por TODAS las secciones: el puntaje es acumulado a
    # lo largo de toda la presentación, no por sección).
    modo_puntaje: str = Field(default="competencia")
    tiempo_pregunta_s: int = Field(default=20, ge=10, le=60)
    factor_tiempo_piar: float = Field(default=1.5)

    @field_validator("modo_puntaje")
    @classmethod
    def _validar_modo_puntaje(cls, v: str) -> str:
        if v not in MODOS_PUNTAJE:
            raise ValueError(f"modo_puntaje debe ser uno de: {', '.join(sorted(MODOS_PUNTAJE))}")
        return v

    @field_validator("factor_tiempo_piar")
    @classmethod
    def _validar_factor_tiempo_piar(cls, v: float) -> float:
        if v not in FACTORES_TIEMPO_PIAR_SOPORTADOS:
            raise ValueError(
                f"factor_tiempo_piar debe ser uno de: {', '.join(str(f) for f in sorted(FACTORES_TIEMPO_PIAR_SOPORTADOS))}"
            )
        return v

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

    @model_validator(mode="after")
    def _validar_total_no_supera_el_maximo(self):
        # SPRINT 7, Parte B: 60 diapositivas totales sumando secciones
        # (contenido + preguntas; las separadoras no cuentan — son
        # estructurales, no configuradas por el docente).
        total = sum(s.n_slides_contenido + s.n_preguntas for s in self.secciones)
        if total > MAX_DIAPOSITIVAS_TOTAL:
            raise ValueError(
                f"El total de diapositivas de todas las secciones ({total}) no puede "
                f"superar {MAX_DIAPOSITIVAS_TOTAL}."
            )
        return self


class PresentacionOut(BaseModel):
    id_presentacion: str
    id_docente: str
    id_grupo: str
    titulo: str
    tema: str
    diapositivas: list
    secciones: list
    estado: str
    error_generacion: Optional[str] = None
    modo_puntaje: str
    tiempo_pregunta_s: int
    factor_tiempo_piar: float
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
    n_secciones: int
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

def _construir_secciones_y_diapositivas_iniciales(
    secciones_req: List["SeccionRequest"],
) -> tuple[list[dict], list[dict]]:
    """
    SPRINT 7, Parte A — calcula el rango [inicio, fin] (inclusive) de
    cada sección dentro del array PLANO de diapositivas, y arma ese
    array inicial: la diapositiva separadora de cada sección ya
    completa (no necesita IA, se conoce del request) + placeholders
    "pendiente" en el resto de su rango, listos para que la fase 1/2
    de esa sección los vaya llenando de forma independiente.
    """
    secciones_meta: list[dict] = []
    diapositivas: list[dict] = []
    for s in secciones_req:
        inicio = len(diapositivas)
        diapositivas.append({"tipo": "separador", "titulo": s.tema})
        n_total_seccion = s.n_slides_contenido + s.n_preguntas
        diapositivas.extend({"tipo": "pendiente", "titulo": s.tema} for _ in range(n_total_seccion))
        secciones_meta.append({
            "tema": s.tema,
            "n_slides_contenido": s.n_slides_contenido,
            "n_preguntas": s.n_preguntas,
            "inicio": inicio,
            "fin": len(diapositivas) - 1,
            "estado": "generando",
            "error_generacion": None,
        })
    return secciones_meta, diapositivas


@router.post("/generar", response_model=PresentacionOut, status_code=202)
async def generar_presentacion(
    body: GenerarPresentacionRequest,
    docente: Docente = Depends(verify_trial_active),
    db: Session = Depends(get_db),
):
    """
    SPRINT 4: responde 202 de inmediato con estado='generando' — NUNCA
    espera a la IA dentro del request HTTP. Generaciones grandes (hasta
    60 diapositivas entre todas las secciones) tardaban más que el
    timeout de proxy de Cloudflare, que devolvía 502 aunque el servidor
    siguiera vivo.

    SPRINT 7: `body.secciones` (1 a 5 temas) — cada una se genera en
    background de forma independiente (ver
    _ejecutar_generacion_en_background/_ejecutar_generacion_seccion) y
    deja esta fila en estado='lista' (si al menos una sección quedó
    lista) o 'error' (si todas fallaron), emitiendo presentacion:generada
    por socket.io al docente. GET /{id}/estado sirve de respaldo si el
    socket no llega.
    """
    grupo = _grupo_del_docente_o_404(body.grupo_id, docente.id_docente, db)

    secciones_meta, diapositivas_iniciales = _construir_secciones_y_diapositivas_iniciales(body.secciones)
    tema_resumen = ", ".join(s.tema for s in body.secciones)

    presentacion = Presentacion(
        id_docente=docente.id_docente,
        id_grupo=grupo.id_grupo,
        titulo=tema_resumen[:200],
        tema=tema_resumen[:500],
        diapositivas=diapositivas_iniciales,
        secciones=secciones_meta,
        estado="generando",
        modo_puntaje=body.modo_puntaje,
        tiempo_pregunta_s=body.tiempo_pregunta_s,
        factor_tiempo_piar=body.factor_tiempo_piar,
    )
    db.add(presentacion)
    db.commit()
    db.refresh(presentacion)

    _lanzar_generacion_en_background(
        presentacion.id_presentacion,
        grupo.id_grupo,
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
            n_secciones=len(p.secciones or []),
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


@router.get("/sesiones/{id_sesion}/exportar")
def exportar_resultados_sesion(
    id_sesion: str,
    docente: Docente = Depends(verify_trial_active),
    db: Session = Depends(get_db),
):
    """
    SPRINT 6, Parte C/D — CSV de resultados (nombre, aciertos,
    respuestas totales, puntaje acumulado) para que el docente exporte
    después de la sesión. Ownership vía la presentación dueña de la
    sesión (mismo criterio 404-no-403 que el resto del módulo).
    """
    import csv
    import io

    from models import PuntajeEstudiante

    sesion = db.query(SesionPresentacion).filter(SesionPresentacion.id_sesion == id_sesion).first()
    if not sesion or sesion.presentacion.id_docente != docente.id_docente:
        raise HTTPException(status_code=404, detail="Sesión no encontrada")

    puntajes = db.query(PuntajeEstudiante).filter(
        PuntajeEstudiante.id_sesion == id_sesion,
    ).order_by(PuntajeEstudiante.puntaje_acumulado.desc()).all()

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["nombre", "aciertos", "respuestas_totales", "puntaje_acumulado"])
    for p in puntajes:
        writer.writerow([p.nombre_estudiante, p.aciertos, p.respuestas_totales, p.puntaje_acumulado])

    nombre_archivo = f"resultados_{sesion.codigo}.csv"
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{nombre_archivo}"'},
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
