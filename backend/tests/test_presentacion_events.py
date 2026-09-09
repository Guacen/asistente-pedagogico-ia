"""
BUG 2 (SPRINT 1 presentaciones) — flujo de join por socket (servidor).

Reporte de clase real: el estudiante ingresa código + nombre, presiona
"Unirme", y queda colgado en "Uniendo…" indefinidamente. El handler del
servidor (`presentacion_events.presentacion_unirse`) en sí mismo emitía
correctamente `presentacion:unido`/`presentacion:error` — la hipótesis
principal terminó siendo el CSP bloqueando el WebSocket en Safari — pero
no existía ningún test automatizado que confirmara que el handler real
(no sólo las funciones puras de presentaciones.py) efectivamente hace lo
que promete. Estos tests cubren ese hueco: invocan el handler
`@sio.on("presentacion:unirse")` directamente (no un helper extraído),
con `sio.emit`/`sio.enter_room` mockeados y una sesión de DB de prueba,
para verificar que SIEMPRE se le emite algo de vuelta al estudiante —
nunca "nada" (que es exactamente lo que deja el botón colgado).
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import presentacion_events  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


def _monkeypatch_session_local(monkeypatch, test_engine):
    """
    presentacion_unirse crea su propia sesión vía SessionLocal() en vez
    de recibirla por parámetro (a diferencia de iniciar_slide/
    cerrar_slide/etc. en presentaciones.py) — para testear el handler
    real tal como corre en producción, en vez de sólo un helper extraído,
    hace falta que esa sesión apunte al engine efímero del test.
    """
    Session = sessionmaker(bind=test_engine, autocommit=False, autoflush=False)
    monkeypatch.setattr(presentacion_events, "SessionLocal", Session)


def _mock_sio(monkeypatch):
    emit_mock = AsyncMock()
    monkeypatch.setattr(presentacion_events.sio, "emit", emit_mock)
    monkeypatch.setattr(presentacion_events.sio, "enter_room", AsyncMock())
    return emit_mock


def _eventos_emitidos(emit_mock):
    return [c.args[0] for c in emit_mock.call_args_list]


def _payload(emit_mock, evento):
    llamada = next(c for c in emit_mock.call_args_list if c.args[0] == evento)
    return llamada.args[1], llamada.kwargs


@pytest.fixture
def sesion_activa(db_session, seed_docente):
    """Presentación + sesión de prueba directamente en la DB del test,
    imitando lo que crean POST /generar + POST /iniciar."""
    from models import Presentacion, SesionPresentacion

    presentacion = Presentacion(
        id_docente=seed_docente["docente"].id_docente,
        id_grupo=seed_docente["grupo"].id_grupo,
        titulo="Fuerzas", tema="Diagrama de cuerpo libre",
        diapositivas=[{
            "tipo": "multiple", "pregunta": "¿1/2 = ?",
            "opciones": ["2/4", "1/3"], "correcta": 0,
            "tiempo_s": 20, "puntos": 100,
        }],
    )
    db_session.add(presentacion)
    db_session.flush()
    sesion = SesionPresentacion(
        id_presentacion=presentacion.id_presentacion, codigo="FVGUUU",
    )
    db_session.add(sesion)
    db_session.commit()
    db_session.refresh(sesion)
    return sesion


@pytest.fixture(autouse=True)
def _limpiar_estudiantes():
    """El dict compartido _estudiantes_presentacion (socket_events.py) no
    se limpia solo entre tests — usamos sids únicos por test así que no
    hay colisión, pero lo limpiamos igual por higiene."""
    yield
    presentacion_events._estudiantes.clear()


def test_unirse_codigo_valido_emite_unido_con_sesion_id(
    db_session, test_engine, sesion_activa, monkeypatch,
):
    """El caso feliz: código correcto → presentacion:unido con el
    sesion_id (sin esto el estudiante nunca puede emitir 'responder')."""
    _monkeypatch_session_local(monkeypatch, test_engine)
    emit_mock = _mock_sio(monkeypatch)

    _run(presentacion_events.presentacion_unirse(
        "sid-1", {"codigo": "fvguuu", "nombre": "Ana"},
    ))

    assert "presentacion:unido" in _eventos_emitidos(emit_mock)
    payload, kwargs = _payload(emit_mock, "presentacion:unido")
    assert payload["nombre"] == "Ana"
    assert payload["sesion_id"] == sesion_activa.id_sesion
    assert kwargs.get("to") == "sid-1"
    assert presentacion_events._estudiantes["sid-1"]["id_sesion"] == sesion_activa.id_sesion


def test_unirse_codigo_invalido_emite_error_nunca_se_cuelga(
    db_session, test_engine, monkeypatch,
):
    """CRÍTICO: código que no existe → el estudiante recibe un error
    explícito, no silencio (silencio == botón colgado en "Uniendo…")."""
    _monkeypatch_session_local(monkeypatch, test_engine)
    emit_mock = _mock_sio(monkeypatch)

    _run(presentacion_events.presentacion_unirse(
        "sid-2", {"codigo": "NOEXST", "nombre": "Ana"},
    ))

    eventos = _eventos_emitidos(emit_mock)
    assert eventos, "el handler no emitió NADA — este es exactamente el bug reportado"
    assert "presentacion:error" in eventos
    payload, _ = _payload(emit_mock, "presentacion:error")
    assert "no encontrado" in payload["message"].lower()


def test_unirse_sesion_finalizada_emite_error(db_session, test_engine, sesion_activa, monkeypatch):
    sesion_activa.estado = "finalizada"
    db_session.commit()
    _monkeypatch_session_local(monkeypatch, test_engine)
    emit_mock = _mock_sio(monkeypatch)

    _run(presentacion_events.presentacion_unirse(
        "sid-3", {"codigo": "FVGUUU", "nombre": "Ana"},
    ))

    payload, _ = _payload(emit_mock, "presentacion:error")
    assert "finaliz" in payload["message"].lower()


def test_unirse_sin_codigo_o_nombre_emite_error(db_session, test_engine, monkeypatch):
    _monkeypatch_session_local(monkeypatch, test_engine)
    emit_mock = _mock_sio(monkeypatch)

    _run(presentacion_events.presentacion_unirse("sid-4", {"codigo": "", "nombre": ""}))

    assert _eventos_emitidos(emit_mock) == ["presentacion:error"]


def test_unirse_error_inesperado_igual_emite_algo_al_estudiante(
    db_session, test_engine, sesion_activa, monkeypatch,
):
    """
    Si algo inesperado explota adentro del handler (ej. sio.enter_room
    falla), el estudiante NO debe quedarse sin ninguna respuesta — eso es
    exactamente el bug reportado en clase real. Confirma que el except
    genérico agregado en este sprint emite presentacion:error en vez de
    dejar la excepción sin ningún aviso al cliente.
    """
    _monkeypatch_session_local(monkeypatch, test_engine)
    emit_mock = AsyncMock()
    monkeypatch.setattr(presentacion_events.sio, "emit", emit_mock)
    monkeypatch.setattr(
        presentacion_events.sio, "enter_room",
        AsyncMock(side_effect=RuntimeError("boom")),
    )

    _run(presentacion_events.presentacion_unirse(
        "sid-5", {"codigo": "FVGUUU", "nombre": "Ana"},
    ))

    eventos = _eventos_emitidos(emit_mock)
    assert eventos, "una excepción inesperada dejó al estudiante sin NINGUNA respuesta"
    assert "presentacion:error" in eventos
