"""
SPRINT 8, Parte A — reconexión de estudiantes.

Cubre las verificaciones obligatorias:
1. Simular desconexión y reconexión: el participante conserva
   identidad (mismo nombre, sin duplicarse en el conteo de la sala),
   su puntaje sigue acumulado, y recibe el estado actual completo vía
   presentacion:sincronizar.
4. El tiempo restante de la pregunta lo calcula el SERVIDOR
   (_tiempo_restante_s), no el cliente — verificado con el reloj
   real (time.sleep) para que quede claro que no es un valor fijo.
"""
from __future__ import annotations

import asyncio
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock

from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import presentaciones as presentaciones_module  # noqa: E402
from models import Presentacion, SesionPresentacion  # noqa: E402


def _patch_session_local(monkeypatch, test_engine):
    Session = sessionmaker(bind=test_engine, autocommit=False, autoflush=False)
    monkeypatch.setattr(presentaciones_module, "SessionLocal", Session)
    import presentacion_events
    monkeypatch.setattr(presentacion_events, "SessionLocal", Session)


def _crear_presentacion_con_pregunta(db_session, docente, grupo, **kwargs):
    diapositivas = [{
        "tipo": "multiple", "pregunta": "¿Cuál es la capital de Colombia?",
        "opciones": ["Bogotá", "Medellín", "Cali", "Cartagena"],
        "correcta": 0, "tiempo_s": 20, "puntos": 100,
    }]
    presentacion = Presentacion(
        id_docente=docente.id_docente, id_grupo=grupo.id_grupo,
        titulo="T", tema="T", diapositivas=diapositivas,
        secciones=[{
            "tema": "T", "n_slides_contenido": 0, "n_preguntas": 1,
            "inicio": 0, "fin": 0, "estado": "lista", "error_generacion": None,
        }],
        estado="lista", **kwargs,
    )
    db_session.add(presentacion)
    db_session.commit()
    db_session.refresh(presentacion)
    return presentacion


def _crear_sesion(db_session, presentacion, codigo="RECN01"):
    sesion = SesionPresentacion(id_presentacion=presentacion.id_presentacion, codigo=codigo)
    db_session.add(sesion)
    db_session.commit()
    db_session.refresh(sesion)
    return sesion


# ═══════════════════════════════════════════════════════════════
# 1. Reconexión: identidad, puntaje y estado completo se preservan
# ═══════════════════════════════════════════════════════════════

def test_unirse_de_nuevo_con_mismo_participante_id_limpia_el_sid_viejo(
    db_session, test_engine, seed_docente, monkeypatch,
):
    """El navegador se reconecta con un sid NUEVO (comportamiento real
    de socket.io) pero el mismo participante_id — el servidor debe
    reasociar al mismo participante, no duplicarlo en el conteo de la
    sala."""
    import presentacion_events

    _patch_session_local(monkeypatch, test_engine)
    docente = seed_docente["docente"]
    grupo = seed_docente["grupo"]
    presentacion = _crear_presentacion_con_pregunta(db_session, docente, grupo)
    sesion = _crear_sesion(db_session, presentacion)

    emit_mock = AsyncMock()
    monkeypatch.setattr(presentacion_events.sio, "emit", emit_mock)
    monkeypatch.setattr(presentacion_events.sio, "enter_room", AsyncMock())

    # Primera conexión.
    asyncio.run(presentacion_events.presentacion_unirse(
        "sid-viejo", {"codigo": sesion.codigo, "nombre": "Ana", "participante_id": "part-1"},
    ))
    assert "sid-viejo" in presentacion_events._estudiantes
    assert presentacion_events._contar_estudiantes_sala(sesion.id_sesion) == 1

    # Reconexión — sid nuevo, MISMO participante_id.
    asyncio.run(presentacion_events.presentacion_unirse(
        "sid-nuevo", {"codigo": sesion.codigo, "nombre": "Ana", "participante_id": "part-1"},
    ))

    # El sid viejo se limpió — nunca quedan dos entradas para el mismo
    # participante inflando el conteo de la sala.
    assert "sid-viejo" not in presentacion_events._estudiantes
    assert "sid-nuevo" in presentacion_events._estudiantes
    assert presentacion_events._contar_estudiantes_sala(sesion.id_sesion) == 1
    assert presentacion_events._estudiantes["sid-nuevo"]["nombre"] == "Ana"

    presentacion_events._estudiantes.clear()


def test_unirse_con_participante_id_distinto_no_afecta_a_otros_estudiantes(
    db_session, test_engine, seed_docente, monkeypatch,
):
    """La limpieza de sid viejo es POR participante — dos estudiantes
    distintos (participante_id distinto) coexisten sin pisarse."""
    import presentacion_events

    _patch_session_local(monkeypatch, test_engine)
    docente = seed_docente["docente"]
    grupo = seed_docente["grupo"]
    presentacion = _crear_presentacion_con_pregunta(db_session, docente, grupo)
    sesion = _crear_sesion(db_session, presentacion)

    monkeypatch.setattr(presentacion_events.sio, "emit", AsyncMock())
    monkeypatch.setattr(presentacion_events.sio, "enter_room", AsyncMock())

    asyncio.run(presentacion_events.presentacion_unirse(
        "sid-ana", {"codigo": sesion.codigo, "nombre": "Ana", "participante_id": "part-ana"},
    ))
    asyncio.run(presentacion_events.presentacion_unirse(
        "sid-beto", {"codigo": sesion.codigo, "nombre": "Beto", "participante_id": "part-beto"},
    ))

    assert presentacion_events._contar_estudiantes_sala(sesion.id_sesion) == 2
    assert "sid-ana" in presentacion_events._estudiantes
    assert "sid-beto" in presentacion_events._estudiantes

    presentacion_events._estudiantes.clear()


def test_reconexion_conserva_puntaje_y_sincronizar_lo_devuelve(
    db_session, test_engine, seed_docente, monkeypatch,
):
    """Flujo completo: Ana responde correctamente, se "desconecta"
    (se borra su entrada en memoria, como haría socket_events.disconnect),
    reconecta con sid nuevo + mismo participante_id, y
    presentacion:sincronizar le devuelve su puntaje intacto."""
    import presentacion_events
    from presentaciones import iniciar_slide, registrar_respuesta

    _patch_session_local(monkeypatch, test_engine)
    docente = seed_docente["docente"]
    grupo = seed_docente["grupo"]
    presentacion = _crear_presentacion_con_pregunta(db_session, docente, grupo, modo_puntaje="inclusivo")
    sesion = _crear_sesion(db_session, presentacion)

    monkeypatch.setattr(presentacion_events.sio, "emit", AsyncMock())
    monkeypatch.setattr(presentacion_events.sio, "enter_room", AsyncMock())

    # Ana se une y responde correctamente.
    asyncio.run(presentacion_events.presentacion_unirse(
        "sid-1", {"codigo": sesion.codigo, "nombre": "Ana", "participante_id": "part-ana"},
    ))
    iniciar_slide(db_session, sesion, 0)
    registrar_respuesta(db_session, sesion, presentacion, 0, "Ana", "0", 1000)

    # Se "desconecta" (simulando socket_events.disconnect, que limpia su
    # entrada del dict en memoria) y reconecta con un sid nuevo.
    presentacion_events._estudiantes.pop("sid-1", None)
    asyncio.run(presentacion_events.presentacion_unirse(
        "sid-2", {"codigo": sesion.codigo, "nombre": "Ana", "participante_id": "part-ana"},
    ))

    emit_mock = AsyncMock()
    monkeypatch.setattr(presentacion_events.sio, "emit", emit_mock)
    asyncio.run(presentacion_events.presentacion_sincronizar(
        "sid-2", {"sesion_id": sesion.id_sesion},
    ))

    emit_mock.assert_awaited_once()
    args, kwargs = emit_mock.call_args
    assert args[0] == "presentacion:sincronizado"
    assert kwargs.get("to") == "sid-2"
    payload = args[1]
    assert payload["ya_respondio"] is True
    assert payload["puntaje_acumulado"] == 1000  # su puntaje NO se perdió
    assert payload["posicion"] == 1

    presentacion_events._estudiantes.clear()


def test_sincronizar_sin_haberse_unido_da_error_no_estado(db_session, test_engine, seed_docente, monkeypatch):
    """Un sid que nunca pasó por presentacion:unirse (o cuya entrada ya
    se limpió) no puede pedir sincronizar — evita filtrar estado de la
    sesión a cualquiera."""
    import presentacion_events

    _patch_session_local(monkeypatch, test_engine)
    docente = seed_docente["docente"]
    grupo = seed_docente["grupo"]
    presentacion = _crear_presentacion_con_pregunta(db_session, docente, grupo)
    sesion = _crear_sesion(db_session, presentacion)

    emit_mock = AsyncMock()
    monkeypatch.setattr(presentacion_events.sio, "emit", emit_mock)

    asyncio.run(presentacion_events.presentacion_sincronizar(
        "sid-fantasma", {"sesion_id": sesion.id_sesion},
    ))

    emit_mock.assert_awaited_once()
    args, kwargs = emit_mock.call_args
    assert args[0] == "presentacion:error"


# ═══════════════════════════════════════════════════════════════
# 4. Tiempo restante — SIEMPRE calculado por el servidor
# ═══════════════════════════════════════════════════════════════

def test_tiempo_restante_s_disminuye_con_el_reloj_real(db_session, seed_docente):
    """No es un valor fijo ni lo manda el cliente — se deriva de
    sesion.slide_abierto_en (un timestamp real) contra datetime.utcnow()
    (el reloj real del servidor)."""
    from presentaciones import _tiempo_restante_s, iniciar_slide

    docente = seed_docente["docente"]
    grupo = seed_docente["grupo"]
    presentacion = _crear_presentacion_con_pregunta(db_session, docente, grupo)
    sesion = _crear_sesion(db_session, presentacion)

    iniciar_slide(db_session, sesion, 0)
    inmediato = _tiempo_restante_s(sesion, tiempo_limite_ms=5000)
    assert inmediato in (4, 5)  # recién abierto, prácticamente el límite completo

    time.sleep(1.1)
    despues = _tiempo_restante_s(sesion, tiempo_limite_ms=5000)
    assert despues < inmediato  # el reloj real avanzó, el restante bajó


def test_tiempo_restante_s_nunca_negativo():
    from presentaciones import _tiempo_restante_s

    class SesionFalsa:
        slide_abierto = True
        slide_abierto_en = datetime.utcnow() - timedelta(seconds=999)

    assert _tiempo_restante_s(SesionFalsa(), tiempo_limite_ms=5000) == 0


def test_tiempo_restante_s_es_0_si_el_slide_no_esta_abierto():
    from presentaciones import _tiempo_restante_s

    class SesionFalsa:
        slide_abierto = False
        slide_abierto_en = datetime.utcnow()

    assert _tiempo_restante_s(SesionFalsa(), tiempo_limite_ms=5000) == 0


def test_construir_estado_sincronizacion_incluye_tiempo_restante_del_servidor(db_session, seed_docente):
    from presentaciones import construir_estado_sincronizacion, iniciar_slide

    docente = seed_docente["docente"]
    grupo = seed_docente["grupo"]
    presentacion = _crear_presentacion_con_pregunta(db_session, docente, grupo)
    sesion = _crear_sesion(db_session, presentacion)
    iniciar_slide(db_session, sesion, 0)

    estado = construir_estado_sincronizacion(db_session, sesion, presentacion, "Ana")
    assert estado["slide_activa"] is True
    assert estado["slide_abierto"] is True
    assert isinstance(estado["tiempo_restante_s"], int)
    assert 0 < estado["tiempo_restante_s"] <= presentacion.tiempo_pregunta_s
    assert estado["tiempo_limite_s"] == presentacion.tiempo_pregunta_s
    assert estado["ya_respondio"] is False
    # slide_data nunca expone la respuesta correcta antes de revelar.
    assert "correcta" not in estado["slide_data"]


def test_construir_estado_sincronizacion_marca_ya_respondio(db_session, seed_docente):
    from presentaciones import construir_estado_sincronizacion, iniciar_slide, registrar_respuesta

    docente = seed_docente["docente"]
    grupo = seed_docente["grupo"]
    presentacion = _crear_presentacion_con_pregunta(db_session, docente, grupo)
    sesion = _crear_sesion(db_session, presentacion)
    iniciar_slide(db_session, sesion, 0)
    registrar_respuesta(db_session, sesion, presentacion, 0, "Ana", "0", 1000)

    estado = construir_estado_sincronizacion(db_session, sesion, presentacion, "Ana")
    assert estado["ya_respondio"] is True


def test_construir_estado_sincronizacion_finalizada(db_session, seed_docente):
    from presentaciones import construir_estado_sincronizacion, iniciar_slide, registrar_respuesta, finalizar_sesion

    docente = seed_docente["docente"]
    grupo = seed_docente["grupo"]
    presentacion = _crear_presentacion_con_pregunta(db_session, docente, grupo, modo_puntaje="inclusivo")
    sesion = _crear_sesion(db_session, presentacion)
    iniciar_slide(db_session, sesion, 0)
    registrar_respuesta(db_session, sesion, presentacion, 0, "Ana", "0", 1000)
    finalizar_sesion(db_session, sesion)

    estado = construir_estado_sincronizacion(db_session, sesion, presentacion, "Ana")
    assert estado["finalizada"] is True
    assert estado["puntaje_acumulado"] == 1000
    assert estado["posicion"] == 1
    assert estado["total_participantes"] == 1


def test_construir_estado_sincronizacion_sin_pregunta_activa(db_session, seed_docente):
    """El docente está en una diapositiva de contenido — nada que
    responder, pero igual se informa la posición del array."""
    from presentaciones import construir_estado_sincronizacion, iniciar_slide

    docente = seed_docente["docente"]
    grupo = seed_docente["grupo"]
    diapositivas = [{"tipo": "contenido", "titulo": "A", "cuerpo": "x", "notas_docente": "x"}]
    presentacion = Presentacion(
        id_docente=docente.id_docente, id_grupo=grupo.id_grupo,
        titulo="T", tema="T", diapositivas=diapositivas,
        secciones=[{"tema": "T", "n_slides_contenido": 1, "n_preguntas": 0, "inicio": 0, "fin": 0, "estado": "lista", "error_generacion": None}],
        estado="lista",
    )
    db_session.add(presentacion)
    db_session.commit()
    db_session.refresh(presentacion)
    sesion = _crear_sesion(db_session, presentacion, codigo="CONT01")

    estado = construir_estado_sincronizacion(db_session, sesion, presentacion, "Ana")
    assert estado["finalizada"] is False
    assert estado["slide_activa"] is False
