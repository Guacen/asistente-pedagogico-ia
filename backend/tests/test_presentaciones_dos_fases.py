"""
SPRINT 5 — generación en dos fases + controles del docente + diagramas
por descriptor.

Cubre las verificaciones obligatorias específicas de este sprint (las
de diagramas SVG ya estaban cubiertas por
backend/tests/frontend/test_render_contenido_diapositiva.mjs desde el
sprint 2 — no se duplican acá):

1. Pedir 15 diapositivas dispara 15 llamadas de fase 2 (no una sola
   llamada gigante) — y exactamente 1 llamada de fase 1 (esqueleto).
2. El fallo de UNA diapositiva (tras agotar su reintento) no aborta las
   demás — la presentación igual termina en estado='lista', con esa
   posición marcada "tipo": "error".
3. El reintento por-diapositiva es de máximo 1 vez (2 intentos totales).
4. Se respeta el límite de concurrencia de fase 2
   (_CONCURRENCIA_MAXIMA_RELLENO = 5).
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock

from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import presentaciones as presentaciones_module  # noqa: E402
from models import Presentacion  # noqa: E402


def _patch_session_local(monkeypatch, test_engine):
    Session = sessionmaker(bind=test_engine, autocommit=False, autoflush=False)
    monkeypatch.setattr(presentaciones_module, "SessionLocal", Session)


def _crear_presentacion_generando(db_session, docente, grupo):
    presentacion = Presentacion(
        id_docente=docente.id_docente, id_grupo=grupo.id_grupo,
        titulo="T", tema="T", diapositivas=[], estado="generando",
    )
    db_session.add(presentacion)
    db_session.commit()
    db_session.refresh(presentacion)
    return presentacion


async def _contenido_ok(grupo, tema, titulo, posicion, total):
    return {"tipo": "contenido", "titulo": titulo, "cuerpo": "x", "notas_docente": "x"}


async def _pregunta_ok(grupo, tema, titulo, posicion, total, tipos_pregunta, tiempo_pregunta_s=20):
    return {
        "tipo": "multiple", "pregunta": titulo, "opciones": ["A", "B"],
        "correcta": 0, "tiempo_s": tiempo_pregunta_s, "puntos": 100,
    }


# ═══════════════════════════════════════════════════════════════
# 1. 15 diapositivas → 15 llamadas de fase 2 (no una sola llamada)
# ═══════════════════════════════════════════════════════════════

def test_quince_diapositivas_disparan_quince_llamadas_de_relleno(db_session, test_engine, seed_docente, monkeypatch):
    _patch_session_local(monkeypatch, test_engine)

    esqueleto = (
        [{"tipo": "contenido", "titulo": f"Contenido {i}"} for i in range(10)]
        + [{"tipo": "pregunta", "titulo": f"Pregunta {i}"} for i in range(5)]
    )
    esqueleto_mock = AsyncMock(return_value=esqueleto)
    monkeypatch.setattr(presentaciones_module, "_generar_esqueleto_ia", esqueleto_mock)

    contenido_mock = AsyncMock(side_effect=_contenido_ok)
    pregunta_mock = AsyncMock(side_effect=_pregunta_ok)
    monkeypatch.setattr(presentaciones_module, "_generar_relleno_contenido_ia", contenido_mock)
    monkeypatch.setattr(presentaciones_module, "_generar_relleno_pregunta_ia", pregunta_mock)

    docente = seed_docente["docente"]
    grupo = seed_docente["grupo"]
    presentacion = _crear_presentacion_generando(db_session, docente, grupo)

    asyncio.run(presentaciones_module._ejecutar_generacion_en_background(
        presentacion.id_presentacion, grupo.id_grupo, "T", 10, 5, ["multiple"], docente.id_docente,
    ))

    # 1 sola llamada de fase 1 (el índice completo en un solo pedido)...
    assert esqueleto_mock.await_count == 1
    # ...pero 15 llamadas de fase 2, una por diapositiva — nunca una
    # única llamada gigante con las 15 a la vez.
    assert contenido_mock.await_count == 10
    assert pregunta_mock.await_count == 5

    db_session.refresh(presentacion)
    assert presentacion.estado == "lista"
    assert len(presentacion.diapositivas) == 15


# ═══════════════════════════════════════════════════════════════
# 2. El fallo de UNA diapositiva no aborta las demás
# ═══════════════════════════════════════════════════════════════

def test_fallo_de_una_diapositiva_no_aborta_las_demas(db_session, test_engine, seed_docente, monkeypatch):
    _patch_session_local(monkeypatch, test_engine)

    esqueleto = [
        {"tipo": "contenido", "titulo": "Buena 1"},
        {"tipo": "contenido", "titulo": "SIEMPRE FALLA"},
        {"tipo": "contenido", "titulo": "Buena 2"},
    ]
    monkeypatch.setattr(presentaciones_module, "_generar_esqueleto_ia", AsyncMock(return_value=esqueleto))

    async def _contenido_una_rota(grupo, tema, titulo, posicion, total):
        if titulo == "SIEMPRE FALLA":
            raise RuntimeError("la IA se cayó para esta diapositiva")
        return {"tipo": "contenido", "titulo": titulo, "cuerpo": "x", "notas_docente": "x"}

    contenido_mock = AsyncMock(side_effect=_contenido_una_rota)
    monkeypatch.setattr(presentaciones_module, "_generar_relleno_contenido_ia", contenido_mock)
    monkeypatch.setattr(presentaciones_module, "_generar_relleno_pregunta_ia", AsyncMock())

    docente = seed_docente["docente"]
    grupo = seed_docente["grupo"]
    presentacion = _crear_presentacion_generando(db_session, docente, grupo)

    asyncio.run(presentaciones_module._ejecutar_generacion_en_background(
        presentacion.id_presentacion, grupo.id_grupo, "T", 3, 0, ["multiple"], docente.id_docente,
    ))

    db_session.refresh(presentacion)
    # La presentación entera NO se aborta — sigue quedando 'lista'.
    assert presentacion.estado == "lista"
    tipos = [d["tipo"] for d in presentacion.diapositivas]
    assert tipos == ["contenido", "error", "contenido"]
    assert presentacion.diapositivas[1]["titulo"] == "SIEMPRE FALLA"
    assert "mensaje" in presentacion.diapositivas[1]
    # Las otras dos diapositivas sí llegaron completas, sin verse
    # afectadas por el fallo de la del medio.
    assert presentacion.diapositivas[0]["titulo"] == "Buena 1"
    assert presentacion.diapositivas[2]["titulo"] == "Buena 2"
    # Reintentó exactamente 1 vez la que siempre falla + 1 intento cada
    # una de las 2 buenas = 4 llamadas totales (no más, no cuelga en un
    # loop infinito de reintentos).
    assert contenido_mock.await_count == 4


def test_diapositiva_que_falla_una_vez_y_luego_funciona_se_recupera(db_session, test_engine, seed_docente, monkeypatch):
    """El reintento por-diapositiva SÍ debe salvar una falla transitoria
    (a diferencia del caso "siempre falla" de arriba)."""
    _patch_session_local(monkeypatch, test_engine)
    esqueleto = [{"tipo": "contenido", "titulo": "Intermitente"}]
    monkeypatch.setattr(presentaciones_module, "_generar_esqueleto_ia", AsyncMock(return_value=esqueleto))

    llamadas = {"n": 0}

    async def _contenido_intermitente(grupo, tema, titulo, posicion, total):
        llamadas["n"] += 1
        if llamadas["n"] == 1:
            return None  # primer intento: respuesta inválida
        return {"tipo": "contenido", "titulo": titulo, "cuerpo": "x", "notas_docente": "x"}

    monkeypatch.setattr(presentaciones_module, "_generar_relleno_contenido_ia", _contenido_intermitente)
    monkeypatch.setattr(presentaciones_module, "_generar_relleno_pregunta_ia", AsyncMock())

    docente = seed_docente["docente"]
    grupo = seed_docente["grupo"]
    presentacion = _crear_presentacion_generando(db_session, docente, grupo)

    asyncio.run(presentaciones_module._ejecutar_generacion_en_background(
        presentacion.id_presentacion, grupo.id_grupo, "T", 1, 0, ["multiple"], docente.id_docente,
    ))

    db_session.refresh(presentacion)
    assert presentacion.estado == "lista"
    assert presentacion.diapositivas[0]["tipo"] == "contenido"
    assert llamadas["n"] == 2


# ═══════════════════════════════════════════════════════════════
# 3. Límite de concurrencia de fase 2
# ═══════════════════════════════════════════════════════════════

def test_respeta_el_limite_de_concurrencia_en_fase_2(db_session, test_engine, seed_docente, monkeypatch):
    _patch_session_local(monkeypatch, test_engine)

    n_slides = 12  # más del límite de concurrencia (5) para forzar colas
    esqueleto = [{"tipo": "contenido", "titulo": f"T{i}"} for i in range(n_slides)]
    monkeypatch.setattr(presentaciones_module, "_generar_esqueleto_ia", AsyncMock(return_value=esqueleto))

    # Sin asyncio.Lock a propósito: bajo scheduling cooperativo, un
    # incremento/decremento de int sin `await` en medio ya es atómico
    # (nunca se interrumpe a mitad de esa línea), así que no hace falta
    # un lock — y evita crear uno fuera de un event loop corriendo.
    estado = {"actuales": 0, "maximo": 0}

    async def _contenido_lento(grupo, tema, titulo, posicion, total):
        estado["actuales"] += 1
        estado["maximo"] = max(estado["maximo"], estado["actuales"])
        await asyncio.sleep(0.03)
        estado["actuales"] -= 1
        return {"tipo": "contenido", "titulo": titulo, "cuerpo": "x", "notas_docente": "x"}

    monkeypatch.setattr(presentaciones_module, "_generar_relleno_contenido_ia", _contenido_lento)
    monkeypatch.setattr(presentaciones_module, "_generar_relleno_pregunta_ia", AsyncMock())

    docente = seed_docente["docente"]
    grupo = seed_docente["grupo"]
    presentacion = _crear_presentacion_generando(db_session, docente, grupo)

    asyncio.run(presentaciones_module._ejecutar_generacion_en_background(
        presentacion.id_presentacion, grupo.id_grupo, "T", n_slides, 0, ["multiple"], docente.id_docente,
    ))

    assert estado["maximo"] <= presentaciones_module._CONCURRENCIA_MAXIMA_RELLENO
    # Con 12 diapositivas y límite 5, debería haberse llegado al tope
    # real (si esto da menos, la concurrencia no se está aprovechando).
    assert estado["maximo"] == presentaciones_module._CONCURRENCIA_MAXIMA_RELLENO

    db_session.refresh(presentacion)
    assert presentacion.estado == "lista"
    assert len(presentacion.diapositivas) == n_slides


# ═══════════════════════════════════════════════════════════════
# Persistencia progresiva — evento presentacion:esqueleto + slide_lista
# ═══════════════════════════════════════════════════════════════

def test_emite_esqueleto_y_slide_lista_progresivamente(db_session, test_engine, seed_docente, monkeypatch):
    _patch_session_local(monkeypatch, test_engine)
    esqueleto = [
        {"tipo": "contenido", "titulo": "Uno"},
        {"tipo": "contenido", "titulo": "Dos"},
    ]
    monkeypatch.setattr(presentaciones_module, "_generar_esqueleto_ia", AsyncMock(return_value=esqueleto))
    monkeypatch.setattr(presentaciones_module, "_generar_relleno_contenido_ia", AsyncMock(side_effect=_contenido_ok))
    monkeypatch.setattr(presentaciones_module, "_generar_relleno_pregunta_ia", AsyncMock())

    import socket_events
    emit_mock = AsyncMock()
    monkeypatch.setattr(socket_events.sio, "emit", emit_mock)

    docente = seed_docente["docente"]
    grupo = seed_docente["grupo"]
    presentacion = _crear_presentacion_generando(db_session, docente, grupo)

    asyncio.run(presentaciones_module._ejecutar_generacion_en_background(
        presentacion.id_presentacion, grupo.id_grupo, "T", 2, 0, ["multiple"], docente.id_docente,
    ))

    eventos = [c.args[0] for c in emit_mock.call_args_list]
    assert eventos[0] == "presentacion:esqueleto"
    assert eventos.count("presentacion:slide_lista") == 2
    assert eventos[-1] == "presentacion:generada"

    payload_esqueleto = emit_mock.call_args_list[0].args[1]
    assert payload_esqueleto["esqueleto"] == [
        {"tipo": "pendiente", "titulo": "Uno"},
        {"tipo": "pendiente", "titulo": "Dos"},
    ]


# ═══════════════════════════════════════════════════════════════
# Contrato compacto (Parte E) — _generar_relleno_contenido_ia /
# _generar_relleno_pregunta_ia parsean el JSON de claves cortas y nunca
# revientan con una respuesta malformada.
# ═══════════════════════════════════════════════════════════════

def test_relleno_contenido_parsea_claves_cortas_y_normaliza_cuerpo_lista(monkeypatch, seed_docente):
    import llm
    monkeypatch.setattr(
        llm, "respuesta_completa",
        AsyncMock(return_value='{"cu": ["Punto 1", "Punto 2"], "nd": "Decir esto."}'),
    )
    grupo = seed_docente["grupo"]
    slide = asyncio.run(presentaciones_module._generar_relleno_contenido_ia(grupo, "Tema", "Título", 1, 4))
    assert slide == {
        "tipo": "contenido", "titulo": "Título",
        "cuerpo": ["Punto 1", "Punto 2"], "notas_docente": "Decir esto.",
    }


def test_relleno_contenido_json_malformado_devuelve_none_sin_reventar(monkeypatch, seed_docente):
    import llm
    monkeypatch.setattr(llm, "respuesta_completa", AsyncMock(return_value="esto no es JSON {["))
    grupo = seed_docente["grupo"]
    slide = asyncio.run(presentaciones_module._generar_relleno_contenido_ia(grupo, "Tema", "Título", 1, 4))
    assert slide is None


def test_relleno_contenido_incluye_diagrama_valido(monkeypatch, seed_docente):
    import llm
    monkeypatch.setattr(
        llm, "respuesta_completa",
        AsyncMock(return_value='{"cu": ["x"], "nd": "x", "dg": {"tipo": "proceso", "datos": {"pasos": ["Paso 1", "Paso 2"]}}}'),
    )
    grupo = seed_docente["grupo"]
    slide = asyncio.run(presentaciones_module._generar_relleno_contenido_ia(grupo, "Tema", "Título", 1, 4))
    assert slide["diagrama"] == {"tipo": "proceso", "datos": {"pasos": ["Paso 1", "Paso 2"]}}


def test_relleno_pregunta_multiple_parsea_claves_cortas(monkeypatch, seed_docente):
    import llm
    monkeypatch.setattr(
        llm, "respuesta_completa",
        AsyncMock(return_value='{"ti": "multiple", "pr": "¿Cuál?", "op": ["A", "B", "C", "D"], "co": 2}'),
    )
    grupo = seed_docente["grupo"]
    slide = asyncio.run(presentaciones_module._generar_relleno_pregunta_ia(
        grupo, "Tema", "Título", 1, 4, ["multiple", "verdadero_falso"],
    ))
    assert slide == {
        "tipo": "multiple", "pregunta": "¿Cuál?", "opciones": ["A", "B", "C", "D"],
        "correcta": 2, "tiempo_s": 20, "puntos": 100,
    }


def test_relleno_pregunta_tipo_no_habilitado_cae_al_primero_permitido(monkeypatch, seed_docente):
    """Si la IA elige "multiple" pero el docente sólo habilitó
    verdadero_falso, no se descarta la diapositiva — se fuerza al tipo
    habilitado."""
    import llm
    monkeypatch.setattr(
        llm, "respuesta_completa",
        AsyncMock(return_value='{"ti": "multiple", "pr": "¿Es correcto?", "op": ["A", "B"], "co": 0}'),
    )
    grupo = seed_docente["grupo"]
    slide = asyncio.run(presentaciones_module._generar_relleno_pregunta_ia(
        grupo, "Tema", "Título", 1, 4, ["verdadero_falso"],
    ))
    assert slide["tipo"] == "verdadero_falso"
    assert slide["opciones"] == ["Verdadero", "Falso"]


def test_relleno_pregunta_json_malformado_devuelve_none_sin_reventar(monkeypatch, seed_docente):
    import llm
    monkeypatch.setattr(llm, "respuesta_completa", AsyncMock(return_value="no es json"))
    grupo = seed_docente["grupo"]
    slide = asyncio.run(presentaciones_module._generar_relleno_pregunta_ia(
        grupo, "Tema", "Título", 1, 4, ["multiple"],
    ))
    assert slide is None
