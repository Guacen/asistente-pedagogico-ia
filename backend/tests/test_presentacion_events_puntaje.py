"""
SPRINT 6 — privacidad del podio/ajuste PIAR a nivel de los handlers
REALES de Socket.io (no sólo las funciones puras de presentaciones.py):

- El tiempo extendido PIAR se manda personalizado por estudiante, nunca
  en un broadcast que permita comparar payloads entre compañeros.
- El podio completo (con nombres) sólo llega a la room del docente
  (docente_{id}), nunca a la room de la sesión (donde también están
  los estudiantes).
- Cada estudiante recibe SÓLO su propio resultado (presentacion:tu_resultado
  / presentacion:tu_resultado_final), nunca el de sus compañeros.

Mismo patrón que test_presentacion_events.py: invoca los handlers
@sio.on(...) directamente, con sio.emit/enter_room mockeados.
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
    Session = sessionmaker(bind=test_engine, autocommit=False, autoflush=False)
    monkeypatch.setattr(presentacion_events, "SessionLocal", Session)


def _mock_sio(monkeypatch):
    emit_mock = AsyncMock()
    monkeypatch.setattr(presentacion_events.sio, "emit", emit_mock)
    monkeypatch.setattr(presentacion_events.sio, "enter_room", AsyncMock())
    return emit_mock


def _llamadas_a(emit_mock, evento):
    return [c for c in emit_mock.call_args_list if c.args[0] == evento]


@pytest.fixture(autouse=True)
def _limpiar_estudiantes():
    yield
    presentacion_events._estudiantes.clear()


@pytest.fixture
def sesion_con_dos_estudiantes(db_session, seed_docente):
    """Presentación con UNA pregunta "multiple", sesión creada, y dos
    estudiantes ya "unidos" (uno con PIAR en el roster, otro sin) —
    imitando el estado que dejaría presentacion:unirse."""
    from models import Estudiante, Presentacion, SesionPresentacion

    docente = seed_docente["docente"]
    grupo = seed_docente["grupo"]
    db_session.add(Estudiante(id_grupo=grupo.id_grupo, codigo_estudiante="Con Piar", tiene_piar=True))
    db_session.add(Estudiante(id_grupo=grupo.id_grupo, codigo_estudiante="Sin Piar", tiene_piar=False))

    presentacion = Presentacion(
        id_docente=docente.id_docente, id_grupo=grupo.id_grupo,
        titulo="T", tema="T",
        diapositivas=[{
            "tipo": "multiple", "pregunta": "¿Cuál?", "opciones": ["A", "B"],
            "correcta": 0, "tiempo_s": 20, "puntos": 100,
        }],
        tiempo_pregunta_s=20, factor_tiempo_piar=1.5,
    )
    db_session.add(presentacion)
    db_session.flush()
    sesion = SesionPresentacion(id_presentacion=presentacion.id_presentacion, codigo="ABCXYZ")
    db_session.add(sesion)
    db_session.commit()
    db_session.refresh(sesion)

    presentacion_events._estudiantes["sid-con-piar"] = {"nombre": "Con Piar", "id_sesion": sesion.id_sesion}
    presentacion_events._estudiantes["sid-sin-piar"] = {"nombre": "Sin Piar", "id_sesion": sesion.id_sesion}
    return sesion


# ═══════════════════════════════════════════════════════════════
# iniciar_slide — tiempo personalizado, nunca un broadcast compartido
# ═══════════════════════════════════════════════════════════════

def test_iniciar_slide_manda_tiempo_extendido_solo_al_estudiante_con_piar(
    db_session, test_engine, sesion_con_dos_estudiantes, monkeypatch,
):
    _monkeypatch_session_local(monkeypatch, test_engine)
    emit_mock = _mock_sio(monkeypatch)

    _run(presentacion_events.presentacion_iniciar_slide(
        "sid-docente", {"sesion_id": sesion_con_dos_estudiantes.id_sesion, "slide_index": 0},
    ))

    llamadas = _llamadas_a(emit_mock, "presentacion:slide_activo")
    por_destinatario = {c.kwargs.get("to"): c.args[1] for c in llamadas if c.kwargs.get("to")}

    assert por_destinatario["sid-con-piar"]["tiempo_s"] == 30  # 20 * 1.5
    assert por_destinatario["sid-sin-piar"]["tiempo_s"] == 20
    assert por_destinatario["sid-docente"]["tiempo_s"] == 20  # el docente ve el base

    # Nunca un broadcast a toda la sala con el tiempo — si lo hubiera,
    # cualquier estudiante podría inferir el ajuste comparando payloads.
    assert not any(c.kwargs.get("room") for c in llamadas)


def test_iniciar_slide_sin_ajuste_relevante_usa_un_solo_broadcast(
    db_session, test_engine, seed_docente, monkeypatch,
):
    """Una diapositiva sin tiempo sensible a PIAR (poll) no necesita
    personalizar nada — un solo broadcast a la sala basta."""
    from models import Presentacion, SesionPresentacion

    docente = seed_docente["docente"]
    grupo = seed_docente["grupo"]
    presentacion = Presentacion(
        id_docente=docente.id_docente, id_grupo=grupo.id_grupo,
        titulo="T", tema="T",
        diapositivas=[{"tipo": "poll", "pregunta": "¿Qué opinas?", "opciones": ["A", "B"]}],
    )
    db_session.add(presentacion)
    db_session.flush()
    sesion = SesionPresentacion(id_presentacion=presentacion.id_presentacion, codigo="POLL01")
    db_session.add(sesion)
    db_session.commit()
    db_session.refresh(sesion)

    _monkeypatch_session_local(monkeypatch, test_engine)
    emit_mock = _mock_sio(monkeypatch)

    _run(presentacion_events.presentacion_iniciar_slide(
        "sid-docente", {"sesion_id": sesion.id_sesion, "slide_index": 0},
    ))

    llamadas = _llamadas_a(emit_mock, "presentacion:slide_activo")
    # Una al docente (to=sid) + una a la sala completa (room=).
    assert len(llamadas) == 2
    assert any(c.kwargs.get("room") for c in llamadas)


# ═══════════════════════════════════════════════════════════════
# cerrar_slide — podio sólo al docente, resultado personal por estudiante
# ═══════════════════════════════════════════════════════════════

def test_cerrar_slide_podio_completo_solo_llega_a_la_room_del_docente(
    db_session, test_engine, sesion_con_dos_estudiantes, monkeypatch,
):
    from presentaciones import iniciar_slide, registrar_respuesta

    _monkeypatch_session_local(monkeypatch, test_engine)
    iniciar_slide(db_session, sesion_con_dos_estudiantes, 0)
    registrar_respuesta(db_session, sesion_con_dos_estudiantes, sesion_con_dos_estudiantes.presentacion, 0, "Con Piar", "0", 5000)
    registrar_respuesta(db_session, sesion_con_dos_estudiantes, sesion_con_dos_estudiantes.presentacion, 0, "Sin Piar", "1", 5000)

    emit_mock = _mock_sio(monkeypatch)
    _run(presentacion_events.presentacion_cerrar_slide(
        "sid-docente", {"sesion_id": sesion_con_dos_estudiantes.id_sesion},
    ))

    llamadas_podio = _llamadas_a(emit_mock, "presentacion:podio")
    assert len(llamadas_podio) == 1
    docente_id = sesion_con_dos_estudiantes.presentacion.id_docente
    assert llamadas_podio[0].kwargs.get("room") == f"docente_{docente_id}"
    # El payload trae AMBOS nombres — por eso nunca puede ir a la sala.
    nombres = {r["nombre"] for r in llamadas_podio[0].args[1]["ranking"]}
    assert nombres == {"Con Piar", "Sin Piar"}


def test_cerrar_slide_manda_resultado_personal_sin_exponer_al_otro_estudiante(
    db_session, test_engine, sesion_con_dos_estudiantes, monkeypatch,
):
    from presentaciones import iniciar_slide, registrar_respuesta

    _monkeypatch_session_local(monkeypatch, test_engine)
    iniciar_slide(db_session, sesion_con_dos_estudiantes, 0)
    # "Con Piar" acierta, "Sin Piar" falla — correcta es índice 0.
    registrar_respuesta(db_session, sesion_con_dos_estudiantes, sesion_con_dos_estudiantes.presentacion, 0, "Con Piar", "0", 5000)
    registrar_respuesta(db_session, sesion_con_dos_estudiantes, sesion_con_dos_estudiantes.presentacion, 0, "Sin Piar", "1", 5000)

    emit_mock = _mock_sio(monkeypatch)
    _run(presentacion_events.presentacion_cerrar_slide(
        "sid-docente", {"sesion_id": sesion_con_dos_estudiantes.id_sesion},
    ))

    llamadas = _llamadas_a(emit_mock, "presentacion:tu_resultado")
    por_sid = {c.kwargs.get("to"): c.args[1] for c in llamadas}

    assert por_sid["sid-con-piar"]["acerto"] is True
    assert por_sid["sid-con-piar"]["puntos_ganados"] > 0
    assert por_sid["sid-sin-piar"]["acerto"] is False
    assert por_sid["sid-sin-piar"]["puntos_ganados"] == 0

    # Ningún payload individual debe traer el nombre de NADIE (ni el
    # propio ni el ajeno) ni una lista de ranking — sólo los campos
    # (acerto/puntos/posición/cambio) de SU propio resultado.
    for payload in por_sid.values():
        assert "ranking" not in payload
        assert "nombre" not in payload
    assert "Con Piar" not in str(por_sid["sid-sin-piar"])
    assert "Sin Piar" not in str(por_sid["sid-con-piar"])


# ═══════════════════════════════════════════════════════════════
# finalizar — mismo criterio de privacidad en el cierre de sesión
# ═══════════════════════════════════════════════════════════════

def test_finalizar_podio_final_solo_al_docente_y_resultado_propio_a_cada_estudiante(
    db_session, test_engine, sesion_con_dos_estudiantes, monkeypatch,
):
    from presentaciones import iniciar_slide, registrar_respuesta

    _monkeypatch_session_local(monkeypatch, test_engine)
    iniciar_slide(db_session, sesion_con_dos_estudiantes, 0)
    registrar_respuesta(db_session, sesion_con_dos_estudiantes, sesion_con_dos_estudiantes.presentacion, 0, "Con Piar", "0", 5000)
    registrar_respuesta(db_session, sesion_con_dos_estudiantes, sesion_con_dos_estudiantes.presentacion, 0, "Sin Piar", "1", 5000)

    emit_mock = _mock_sio(monkeypatch)
    _run(presentacion_events.presentacion_finalizar(
        "sid-docente", {"sesion_id": sesion_con_dos_estudiantes.id_sesion},
    ))

    llamadas_podio = _llamadas_a(emit_mock, "presentacion:podio_final")
    assert len(llamadas_podio) == 1
    docente_id = sesion_con_dos_estudiantes.presentacion.id_docente
    assert llamadas_podio[0].kwargs.get("room") == f"docente_{docente_id}"

    llamadas_finales = _llamadas_a(emit_mock, "presentacion:tu_resultado_final")
    por_sid = {c.kwargs.get("to"): c.args[1] for c in llamadas_finales}
    assert por_sid["sid-con-piar"]["posicion"] == 1
    assert por_sid["sid-sin-piar"]["posicion"] == 2
    for payload in por_sid.values():
        assert "ranking" not in payload

    # El genérico "se acabó" sí va a la sala completa — no lleva nombres.
    llamadas_finalizada = _llamadas_a(emit_mock, "presentacion:finalizada")
    assert len(llamadas_finalizada) == 1
    assert llamadas_finalizada[0].kwargs.get("room") == presentacion_events._sala(sesion_con_dos_estudiantes.id_sesion)
    assert llamadas_finalizada[0].args[1] == {}
