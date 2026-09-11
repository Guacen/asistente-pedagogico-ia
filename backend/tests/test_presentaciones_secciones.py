"""
SPRINT 7 — multi-tema por secciones + límites por duración + tabla de
posiciones en vivo.

Cubre las verificaciones obligatorias de este sprint:
1. Una presentación de 3 secciones genera las tres EN PARALELO y el
   fallo de una no aborta las otras.
2. (migración) ver test_migracion_secciones.py.
3. Cálculo de duración estimada contra varias configuraciones.
4. El estudiante NUNCA recibe el ranking completo por socket — el dato
   no debe viajar, no basta con ocultarlo en la interfaz.
5. El puntaje se acumula correctamente ENTRE secciones (no se reinicia
   al cambiar de tema).
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

import presentaciones as presentaciones_module  # noqa: E402
from models import Presentacion, SesionPresentacion  # noqa: E402


def _patch_session_local(monkeypatch, test_engine):
    Session = sessionmaker(bind=test_engine, autocommit=False, autoflush=False)
    monkeypatch.setattr(presentaciones_module, "SessionLocal", Session)
    # presentacion_events.py abre su PROPIA sesión (import directo de
    # database.SessionLocal, no reexportado de presentaciones) — hace
    # falta parchear las dos para que los handlers de socket vean el
    # mismo test_engine que el resto del test.
    import presentacion_events
    monkeypatch.setattr(presentacion_events, "SessionLocal", Session)


def _crear_presentacion_generando_multi(db_session, docente, grupo, temas):
    """temas: [(tema, n_contenido, n_preguntas), ...] — construye
    secciones + diapositivas iniciales a mano (separadora + placeholders
    "pendiente"), igual que haría POST /generar."""
    secciones_meta, diapositivas = [], []
    for tema, n_contenido, n_preguntas in temas:
        inicio = len(diapositivas)
        diapositivas.append({"tipo": "separador", "titulo": tema})
        diapositivas.extend({"tipo": "pendiente", "titulo": tema} for _ in range(n_contenido + n_preguntas))
        secciones_meta.append({
            "tema": tema, "n_slides_contenido": n_contenido, "n_preguntas": n_preguntas,
            "inicio": inicio, "fin": len(diapositivas) - 1, "estado": "generando", "error_generacion": None,
        })
    presentacion = Presentacion(
        id_docente=docente.id_docente, id_grupo=grupo.id_grupo,
        titulo="Multi", tema=", ".join(t for t, _, _ in temas),
        diapositivas=diapositivas, secciones=secciones_meta, estado="generando",
    )
    db_session.add(presentacion)
    db_session.commit()
    db_session.refresh(presentacion)
    return presentacion


# ═══════════════════════════════════════════════════════════════
# 1. 3 secciones se generan EN PARALELO; el fallo de una no aborta
#    las otras.
# ═══════════════════════════════════════════════════════════════

def test_tres_secciones_generan_en_paralelo(db_session, test_engine, seed_docente, monkeypatch):
    _patch_session_local(monkeypatch, test_engine)

    estado_concurrencia = {"actuales": 0, "maximo": 0}

    async def _esqueleto_lento(grupo, tema, n_slides_contenido, n_preguntas, otros_temas=None):
        estado_concurrencia["actuales"] += 1
        estado_concurrencia["maximo"] = max(estado_concurrencia["maximo"], estado_concurrencia["actuales"])
        await asyncio.sleep(0.05)
        estado_concurrencia["actuales"] -= 1
        return [{"tipo": "contenido", "titulo": f"{tema} - contenido {i}"} for i in range(n_slides_contenido)]

    monkeypatch.setattr(presentaciones_module, "_generar_esqueleto_ia", _esqueleto_lento)
    monkeypatch.setattr(
        presentaciones_module, "_generar_relleno_contenido_ia",
        AsyncMock(side_effect=lambda grupo, tema, titulo, posicion, total: {
            "tipo": "contenido", "titulo": titulo, "cuerpo": "x", "notas_docente": "x",
        }),
    )
    monkeypatch.setattr(presentaciones_module, "_generar_relleno_pregunta_ia", AsyncMock())

    docente = seed_docente["docente"]
    grupo = seed_docente["grupo"]
    presentacion = _crear_presentacion_generando_multi(db_session, docente, grupo, [
        ("Fotosíntesis", 4, 0), ("Respiración celular", 4, 0), ("Ciclo del agua", 4, 0),
    ])

    asyncio.run(presentaciones_module._ejecutar_generacion_en_background(
        presentacion.id_presentacion, grupo.id_grupo, ["multiple"], docente.id_docente,
    ))

    # Si las 3 secciones corrieran secuencialmente, el máximo de
    # esqueletos concurrentes sería 1 — con las 3 en paralelo, llega a 3.
    assert estado_concurrencia["maximo"] == 3

    db_session.refresh(presentacion)
    assert presentacion.estado == "lista"
    assert all(s["estado"] == "lista" for s in presentacion.secciones)
    assert len(presentacion.diapositivas) == 3 * (1 + 4)  # separadora + 4 contenido por sección


def test_fallo_de_una_seccion_no_aborta_las_otras(db_session, test_engine, seed_docente, monkeypatch):
    docente = seed_docente["docente"]
    grupo = seed_docente["grupo"]
    _patch_session_local(monkeypatch, test_engine)

    async def _esqueleto_una_rota(grupo, tema, n_slides_contenido, n_preguntas, otros_temas=None):
        if tema == "SECCIÓN ROTA":
            raise RuntimeError("la IA se cayó para esta sección")
        return [{"tipo": "contenido", "titulo": f"{tema} - contenido {i}"} for i in range(n_slides_contenido)]

    monkeypatch.setattr(presentaciones_module, "_generar_esqueleto_ia", _esqueleto_una_rota)
    monkeypatch.setattr(
        presentaciones_module, "_generar_relleno_contenido_ia",
        AsyncMock(side_effect=lambda grupo, tema, titulo, posicion, total: {
            "tipo": "contenido", "titulo": titulo, "cuerpo": "x", "notas_docente": "x",
        }),
    )
    monkeypatch.setattr(presentaciones_module, "_generar_relleno_pregunta_ia", AsyncMock())

    presentacion = _crear_presentacion_generando_multi(db_session, docente, grupo, [
        ("Buena 1", 4, 0), ("SECCIÓN ROTA", 4, 0), ("Buena 2", 4, 0),
    ])

    asyncio.run(presentaciones_module._ejecutar_generacion_en_background(
        presentacion.id_presentacion, grupo.id_grupo, ["multiple"], docente.id_docente,
    ))

    db_session.refresh(presentacion)
    # La presentación entera sigue 'lista' — 2 de 3 secciones sirven.
    assert presentacion.estado == "lista"
    estados_por_tema = {s["tema"]: s["estado"] for s in presentacion.secciones}
    assert estados_por_tema == {"Buena 1": "lista", "SECCIÓN ROTA": "error", "Buena 2": "lista"}

    # La ventana de la sección rota quedó marcada con error en cada
    # posición — nunca un spinner colgado (mismo criterio que una
    # diapositiva individual rota, aplicado a la sección completa).
    seccion_rota = next(s for s in presentacion.secciones if s["tema"] == "SECCIÓN ROTA")
    ventana_rota = presentacion.diapositivas[seccion_rota["inicio"]:seccion_rota["fin"] + 1]
    assert all(d["tipo"] == "error" for d in ventana_rota[1:])  # [0] es la separadora, sigue intacta

    # Las secciones buenas SÍ tienen contenido real.
    seccion_buena_1 = next(s for s in presentacion.secciones if s["tema"] == "Buena 1")
    ventana_buena = presentacion.diapositivas[seccion_buena_1["inicio"]:seccion_buena_1["fin"] + 1]
    assert ventana_buena[0] == {"tipo": "separador", "titulo": "Buena 1"}
    assert all(d["tipo"] == "contenido" for d in ventana_buena[1:])


def test_todas_las_secciones_fallan_deja_presentacion_en_error(db_session, test_engine, seed_docente, monkeypatch):
    _patch_session_local(monkeypatch, test_engine)
    monkeypatch.setattr(
        presentaciones_module, "_generar_esqueleto_ia", AsyncMock(return_value=[]),
    )
    docente = seed_docente["docente"]
    grupo = seed_docente["grupo"]
    presentacion = _crear_presentacion_generando_multi(db_session, docente, grupo, [
        ("Tema 1", 4, 0), ("Tema 2", 4, 0),
    ])

    asyncio.run(presentaciones_module._ejecutar_generacion_en_background(
        presentacion.id_presentacion, grupo.id_grupo, ["multiple"], docente.id_docente,
    ))

    db_session.refresh(presentacion)
    assert presentacion.estado == "error"
    assert all(s["estado"] == "error" for s in presentacion.secciones)


# ═══════════════════════════════════════════════════════════════
# 3. Duración estimada — varias configuraciones
# ═══════════════════════════════════════════════════════════════

@pytest.mark.parametrize("n_contenido,n_preguntas,tiempo_pregunta_s,esperado_s", [
    (8, 4, 20, 8 * 90 + 4 * (20 + 20)),     # default de una sección típica
    (0, 0, 20, 0),                           # sin diapositivas -> 0
    (10, 0, 20, 10 * 90),                    # sólo contenido, sin preguntas
    (0, 5, 30, 5 * (30 + 20)),               # sólo preguntas
    (60, 0, 20, 60 * 90),                    # el máximo total, todo contenido
])
def test_duracion_estimada_contra_varias_configuraciones(n_contenido, n_preguntas, tiempo_pregunta_s, esperado_s):
    from presentaciones import _duracion_estimada_s
    assert _duracion_estimada_s(n_contenido, n_preguntas, tiempo_pregunta_s) == esperado_s


def test_duracion_estimada_suma_todas_las_secciones():
    """La duración se calcula sobre el TOTAL de la presentación, no
    sección por sección — el docente piensa en la clase completa."""
    from presentaciones import _duracion_estimada_s
    # 2 secciones: (8 contenido, 4 preguntas) + (6 contenido, 2 preguntas), tiempo_pregunta_s=20.
    total_contenido = 8 + 6
    total_preguntas = 4 + 2
    assert _duracion_estimada_s(total_contenido, total_preguntas, 20) == (
        total_contenido * 90 + total_preguntas * (20 + 20)
    )


@pytest.mark.parametrize("minutos,esperado", [
    (0, "verde"), (20, "verde"), (35, "verde"),
    (36, "ambar"), (45, "ambar"), (50, "ambar"),
    (51, "rojo"), (90, "rojo"),
])
def test_clasificar_duracion_semaforo(minutos, esperado):
    from presentaciones import _clasificar_duracion
    assert _clasificar_duracion(minutos) == esperado


def test_clasificar_duracion_nunca_bloquea_solo_informa():
    """No existe ninguna excepción/rechazo asociado a _clasificar_duracion
    — es puramente informativo, nunca impide generar (SPRINT 7, Parte B:
    "Nunca bloquear al docente por la duración")."""
    from presentaciones import _clasificar_duracion
    # Un valor extremo (una presentación de duración absurda) sigue
    # devolviendo una clasificación válida, nunca lanza.
    assert _clasificar_duracion(99999) == "rojo"


# ═══════════════════════════════════════════════════════════════
# 4. El estudiante NUNCA recibe el ranking completo por socket — el
#    dato no viaja, no basta con ocultarlo en la UI.
# ═══════════════════════════════════════════════════════════════

def test_ningun_evento_dirigido_al_estudiante_contiene_la_clave_ranking(
    db_session, test_engine, seed_docente, monkeypatch,
):
    """Recorre TODOS los emits dirigidos a un sid de estudiante (to=sid,
    nunca room=) durante un ciclo completo iniciar->responder->cerrar y
    verifica que ninguno traiga la clave "ranking" — ni aunque el panel
    de posiciones del docente exista y esté recibiendo esos mismos
    datos por otro canal."""
    import presentacion_events

    _patch_session_local(monkeypatch, test_engine)
    docente = seed_docente["docente"]
    grupo = seed_docente["grupo"]

    presentacion = Presentacion(
        id_docente=docente.id_docente, id_grupo=grupo.id_grupo,
        titulo="T", tema="T",
        diapositivas=[{
            "tipo": "multiple", "pregunta": "¿Cuál?", "opciones": ["A", "B"],
            "correcta": 0, "tiempo_s": 20, "puntos": 100,
        }],
        secciones=[{
            "tema": "T", "n_slides_contenido": 0, "n_preguntas": 1,
            "inicio": 0, "fin": 0, "estado": "lista", "error_generacion": None,
        }],
        estado="lista",
    )
    db_session.add(presentacion)
    db_session.flush()
    sesion = SesionPresentacion(id_presentacion=presentacion.id_presentacion, codigo="RANK01")
    db_session.add(sesion)
    db_session.commit()
    db_session.refresh(sesion)

    emit_mock = AsyncMock()
    monkeypatch.setattr(presentacion_events.sio, "emit", emit_mock)
    monkeypatch.setattr(presentacion_events.sio, "enter_room", AsyncMock())
    presentacion_events._estudiantes["sid-estudiante"] = {"nombre": "Ana", "id_sesion": sesion.id_sesion}

    asyncio.run(presentacion_events.presentacion_iniciar_slide(
        "sid-docente", {"sesion_id": sesion.id_sesion, "slide_index": 0},
    ))
    asyncio.run(presentacion_events.presentacion_responder(
        "sid-estudiante",
        {"sesion_id": sesion.id_sesion, "slide_index": 0, "respuesta": "0", "tiempo_respuesta_ms": 1000},
    ))
    asyncio.run(presentacion_events.presentacion_cerrar_slide(
        "sid-docente", {"sesion_id": sesion.id_sesion},
    ))

    llamadas_a_estudiante = [c for c in emit_mock.call_args_list if c.kwargs.get("to") == "sid-estudiante"]
    assert llamadas_a_estudiante, "el estudiante debería haber recibido al menos slide_activo + tu_resultado"
    for llamada in llamadas_a_estudiante:
        payload = llamada.args[1] if len(llamada.args) > 1 else {}
        assert "ranking" not in payload, f"evento {llamada.args[0]!r} dirigido al estudiante trae 'ranking'"
        assert "podio_top5" not in payload

    # Verificación cruzada: el dato SÍ existe (le llega al docente) —
    # confirma que la ausencia arriba es a propósito, no porque nadie
    # lo calculó nunca.
    llamadas_a_room_docente = [
        c for c in emit_mock.call_args_list if c.kwargs.get("room") == f"docente_{docente.id_docente}"
    ]
    assert any("ranking" in (c.args[1] if len(c.args) > 1 else {}) for c in llamadas_a_room_docente)


# ═══════════════════════════════════════════════════════════════
# 5. El puntaje se acumula ENTRE secciones — no se reinicia al
#    cambiar de tema.
# ═══════════════════════════════════════════════════════════════

def test_puntaje_se_acumula_entre_secciones(db_session, seed_docente):
    from presentaciones import iniciar_slide, registrar_respuesta, calcular_podio
    from models import PuntajeEstudiante

    docente = seed_docente["docente"]
    grupo = seed_docente["grupo"]

    diapositivas = [
        {"tipo": "separador", "titulo": "Sección A"},
        {"tipo": "multiple", "pregunta": "¿1?", "opciones": ["A", "B"], "correcta": 0, "tiempo_s": 20, "puntos": 100},
        {"tipo": "separador", "titulo": "Sección B"},
        {"tipo": "multiple", "pregunta": "¿2?", "opciones": ["A", "B"], "correcta": 0, "tiempo_s": 20, "puntos": 100},
    ]
    presentacion = Presentacion(
        id_docente=docente.id_docente, id_grupo=grupo.id_grupo,
        titulo="Multi", tema="A, B", diapositivas=diapositivas,
        secciones=[
            {"tema": "Sección A", "n_slides_contenido": 0, "n_preguntas": 1, "inicio": 0, "fin": 1, "estado": "lista", "error_generacion": None},
            {"tema": "Sección B", "n_slides_contenido": 0, "n_preguntas": 1, "inicio": 2, "fin": 3, "estado": "lista", "error_generacion": None},
        ],
        estado="lista", modo_puntaje="inclusivo",
    )
    db_session.add(presentacion)
    db_session.commit()
    db_session.refresh(presentacion)
    sesion = SesionPresentacion(id_presentacion=presentacion.id_presentacion, codigo="ACUM01")
    db_session.add(sesion)
    db_session.commit()
    db_session.refresh(sesion)

    # Responde la pregunta de la Sección A (índice 1) — correcta.
    iniciar_slide(db_session, sesion, 1)
    registrar_respuesta(db_session, sesion, presentacion, 1, "Ana", "0", 1000)

    puntaje = db_session.query(PuntajeEstudiante).filter(
        PuntajeEstudiante.id_sesion == sesion.id_sesion, PuntajeEstudiante.nombre_estudiante == "Ana",
    ).first()
    assert puntaje.puntaje_acumulado == 1000

    # Cambia a la Sección B (salta la separadora en índice 2) y
    # responde la pregunta de esa sección (índice 3) — también correcta.
    iniciar_slide(db_session, sesion, 3)
    registrar_respuesta(db_session, sesion, presentacion, 3, "Ana", "0", 1000)

    db_session.refresh(puntaje)
    # El puntaje de la Sección A NO se resetea — se suma.
    assert puntaje.puntaje_acumulado == 2000
    assert puntaje.respuestas_totales == 2
    assert puntaje.aciertos == 2

    podio = calcular_podio(db_session, sesion, presentacion)
    assert podio["ranking"][0]["nombre"] == "Ana"
    assert podio["ranking"][0]["puntaje_acumulado"] == 2000


def test_podio_parcial_de_seccion_se_emite_al_terminar_la_ultima_pregunta(
    db_session, test_engine, seed_docente, monkeypatch,
):
    """SPRINT 7, Parte C: "al terminar cada sección, mostrar el podio
    parcial de esa sección" — presentacion:podio_seccion se emite
    exactamente cuando se cierra la ÚLTIMA pregunta de una sección, no
    en cada pregunta intermedia."""
    import presentacion_events

    _patch_session_local(monkeypatch, test_engine)
    docente = seed_docente["docente"]
    grupo = seed_docente["grupo"]

    diapositivas = [
        {"tipo": "separador", "titulo": "Sección A"},
        {"tipo": "multiple", "pregunta": "¿1?", "opciones": ["A", "B"], "correcta": 0, "tiempo_s": 20, "puntos": 100},
        {"tipo": "multiple", "pregunta": "¿2?", "opciones": ["A", "B"], "correcta": 0, "tiempo_s": 20, "puntos": 100},
    ]
    presentacion = Presentacion(
        id_docente=docente.id_docente, id_grupo=grupo.id_grupo,
        titulo="T", tema="Sección A", diapositivas=diapositivas,
        secciones=[{
            "tema": "Sección A", "n_slides_contenido": 0, "n_preguntas": 2,
            "inicio": 0, "fin": 2, "estado": "lista", "error_generacion": None,
        }],
        estado="lista",
    )
    db_session.add(presentacion)
    db_session.flush()
    sesion = SesionPresentacion(id_presentacion=presentacion.id_presentacion, codigo="SECFIN")
    db_session.add(sesion)
    db_session.commit()
    db_session.refresh(sesion)

    emit_mock = AsyncMock()
    monkeypatch.setattr(presentacion_events.sio, "emit", emit_mock)

    from presentaciones import iniciar_slide
    iniciar_slide(db_session, sesion, 1)
    asyncio.run(presentacion_events.presentacion_cerrar_slide("sid-docente", {"sesion_id": sesion.id_sesion}))
    eventos_tras_primera = [c.args[0] for c in emit_mock.call_args_list]
    assert "presentacion:podio_seccion" not in eventos_tras_primera

    emit_mock.reset_mock()
    iniciar_slide(db_session, sesion, 2)
    asyncio.run(presentacion_events.presentacion_cerrar_slide("sid-docente", {"sesion_id": sesion.id_sesion}))
    eventos_tras_segunda = [c.args[0] for c in emit_mock.call_args_list]
    assert "presentacion:podio_seccion" in eventos_tras_segunda
