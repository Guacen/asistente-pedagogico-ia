"""
Tests de Presentaciones Interactivas tipo Kahoot (sprint
presentaciones-interactivas).

NUNCA se llama a Claude/Gemini real: _generar_diapositivas_ia se
mockea con monkeypatch (mismo patrón que
piar._sintetizar_conversacion_a_json en test_piar.py) para devolver un
array de slides canned.

La lógica de sesión en vivo (iniciar/cerrar slide, registrar
respuesta, calcular resultado, finalizar) se prueba directo contra
db_session, sin pasar por Socket.io — son funciones puras pensadas
para eso (mismo criterio que _consumir_rate_limit en socket_events.py).
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _slides_canned() -> list[dict]:
    return [
        {
            "tipo": "contenido",
            "titulo": "Qué es la media aritmética",
            "cuerpo": "La media es la suma de los valores dividida entre la cantidad de datos.",
            "notas_docente": "Explicar con un ejemplo de notas del grupo.",
        },
        {
            "tipo": "multiple",
            "pregunta": "¿Cuál es la media de 2, 4 y 6?",
            "opciones": ["2", "4", "6", "12"],
            "correcta": 1,
            "tiempo_s": 20,
            "puntos": 100,
        },
        {
            "tipo": "contenido",
            "titulo": "Para qué sirve la media",
            "cuerpo": "Permite resumir un conjunto de datos en un solo número.",
            "notas_docente": "Dar ejemplos de la vida cotidiana.",
        },
        {
            "tipo": "poll",
            "pregunta": "¿Qué tan útil te parece la media?",
            "opciones": ["Muy útil", "Algo útil", "Poco útil"],
        },
    ]


@pytest.fixture(autouse=True)
def _mock_generacion_ia(monkeypatch):
    """Reemplaza la llamada a la IA por un mock async con slides canned,
    en TODOS los tests de este archivo — POST /generar nunca golpea la
    API real."""
    import presentaciones as presentaciones_module
    mock = AsyncMock(return_value=_slides_canned())
    monkeypatch.setattr(presentaciones_module, "_generar_diapositivas_ia", mock)
    return mock


def _crear_presentacion(db_session, docente, grupo, diapositivas=None):
    from models import Presentacion
    p = Presentacion(
        id_docente=docente.id_docente,
        id_grupo=grupo.id_grupo,
        titulo="Media aritmética",
        tema="Media aritmética",
        diapositivas=diapositivas if diapositivas is not None else _slides_canned(),
    )
    db_session.add(p)
    db_session.commit()
    db_session.refresh(p)
    return p


def _crear_sesion(db_session, presentacion, codigo="ABC234"):
    from models import SesionPresentacion
    s = SesionPresentacion(id_presentacion=presentacion.id_presentacion, codigo=codigo)
    db_session.add(s)
    db_session.commit()
    db_session.refresh(s)
    return s


# ─── 1. POST /generar produce slides con tipos válidos ─────────────

def test_generar_presentacion(client, seed_docente):
    r = client.post("/api/presentaciones/generar", json={
        "grupo_id": seed_docente["grupo"].id_grupo,
        "tema": "Media aritmética",
        "n_slides_contenido": 2,
    })
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["titulo"]
    assert body["tema"] == "Media aritmética"
    tipos = [d["tipo"] for d in body["diapositivas"]]
    assert tipos == ["contenido", "multiple", "contenido", "poll"]
    assert all(t in {"contenido", "multiple", "poll", "nube"} for t in tipos)


def test_generar_presentacion_grupo_ajeno_devuelve_404(client, seed_docente_b):
    """Un docente no puede generar presentaciones para un grupo que no es suyo."""
    r = client.post("/api/presentaciones/generar", json={
        "grupo_id": seed_docente_b["grupo"].id_grupo,
        "tema": "Media aritmética",
    })
    assert r.status_code == 404


def test_generar_presentacion_sin_slides_validas_devuelve_502(client, seed_docente, monkeypatch):
    import presentaciones as presentaciones_module
    monkeypatch.setattr(
        presentaciones_module, "_generar_diapositivas_ia", AsyncMock(return_value=[]),
    )
    r = client.post("/api/presentaciones/generar", json={
        "grupo_id": seed_docente["grupo"].id_grupo,
        "tema": "Tema random",
    })
    assert r.status_code == 502


def test_generar_presentacion_error_proveedor_ia_devuelve_502(client, seed_docente, monkeypatch):
    """Si el proveedor de IA falla (sin API key, timeout, etc.) el docente recibe un 502
    limpio, no un 500 con stack trace."""
    import presentaciones as presentaciones_module
    monkeypatch.setattr(
        presentaciones_module, "_generar_diapositivas_ia",
        AsyncMock(side_effect=RuntimeError("proveedor no configurado")),
    )
    r = client.post("/api/presentaciones/generar", json={
        "grupo_id": seed_docente["grupo"].id_grupo,
        "tema": "Tema random",
    })
    assert r.status_code == 502


# ─── 2. GET /join/{codigo} inválido → 404 ──────────────────────────

def test_join_codigo_invalido(client_no_auth):
    r = client_no_auth.get("/api/presentaciones/join/NOEXST")
    assert r.status_code == 404


def test_join_codigo_valido_devuelve_datos_publicos(client, client_no_auth, seed_docente, db_session):
    r_gen = client.post("/api/presentaciones/generar", json={
        "grupo_id": seed_docente["grupo"].id_grupo,
        "tema": "Media aritmética",
    })
    presentacion_id = r_gen.json()["id_presentacion"]

    r_iniciar = client.post(f"/api/presentaciones/{presentacion_id}/iniciar")
    assert r_iniciar.status_code == 201, r_iniciar.text
    codigo = r_iniciar.json()["codigo"]
    assert len(codigo) == 6

    r_join = client_no_auth.get(f"/api/presentaciones/join/{codigo}")
    assert r_join.status_code == 200
    body = r_join.json()
    assert body["codigo"] == codigo
    assert body["estado"] == "esperando"
    assert body["grado"] == seed_docente["grupo"].grado


def test_iniciar_sesion_presentacion_ajena_devuelve_404(client_two_docentes):
    """Docente B no puede iniciar sesión de una presentación de Docente A."""
    c = client_two_docentes["client"]
    grupo_a = client_two_docentes["data"]["a"]["grupo"]

    client_two_docentes["as_a"]()
    r_gen = c.post("/api/presentaciones/generar", json={
        "grupo_id": grupo_a.id_grupo,
        "tema": "Media aritmética",
    })
    assert r_gen.status_code == 201, r_gen.text
    presentacion_id = r_gen.json()["id_presentacion"]

    client_two_docentes["as_b"]()
    r_iniciar = c.post(f"/api/presentaciones/{presentacion_id}/iniciar")
    assert r_iniciar.status_code == 404


def test_obtener_presentacion_incluye_diapositivas(client, seed_docente):
    r_gen = client.post("/api/presentaciones/generar", json={
        "grupo_id": seed_docente["grupo"].id_grupo,
        "tema": "Media aritmética",
    })
    presentacion_id = r_gen.json()["id_presentacion"]

    r = client.get(f"/api/presentaciones/{presentacion_id}")
    assert r.status_code == 200, r.text
    assert len(r.json()["diapositivas"]) == 4


def test_obtener_presentacion_ajena_devuelve_404(client_two_docentes):
    c = client_two_docentes["client"]
    grupo_a = client_two_docentes["data"]["a"]["grupo"]

    client_two_docentes["as_a"]()
    r_gen = c.post("/api/presentaciones/generar", json={
        "grupo_id": grupo_a.id_grupo, "tema": "Media aritmética",
    })
    presentacion_id = r_gen.json()["id_presentacion"]

    client_two_docentes["as_b"]()
    r = c.get(f"/api/presentaciones/{presentacion_id}")
    assert r.status_code == 404


def test_listar_presentaciones_incluye_sesiones(client, seed_docente):
    r_gen = client.post("/api/presentaciones/generar", json={
        "grupo_id": seed_docente["grupo"].id_grupo,
        "tema": "Media aritmética",
    })
    presentacion_id = r_gen.json()["id_presentacion"]
    client.post(f"/api/presentaciones/{presentacion_id}/iniciar")

    r_lista = client.get("/api/presentaciones/")
    assert r_lista.status_code == 200
    body = r_lista.json()
    assert len(body) == 1
    assert body[0]["id_presentacion"] == presentacion_id
    assert body[0]["n_slides"] == 4
    assert len(body[0]["sesiones"]) == 1


# ─── 3. Respuesta fuera de tiempo → ignorada ───────────────────────

def test_respuesta_fuera_de_tiempo(db_session, seed_docente):
    from presentaciones import cerrar_slide, iniciar_slide, registrar_respuesta

    presentacion = _crear_presentacion(db_session, seed_docente["docente"], seed_docente["grupo"])
    sesion = _crear_sesion(db_session, presentacion)

    iniciar_slide(db_session, sesion, 1)
    cerrar_slide(db_session, sesion)

    resultado = registrar_respuesta(db_session, sesion, presentacion, 1, "Juan", "1", 5000)
    assert resultado is None


def test_respuesta_a_slide_distinto_del_actual_es_ignorada(db_session, seed_docente):
    from presentaciones import iniciar_slide, registrar_respuesta

    presentacion = _crear_presentacion(db_session, seed_docente["docente"], seed_docente["grupo"])
    sesion = _crear_sesion(db_session, presentacion)

    iniciar_slide(db_session, sesion, 1)  # slide 1 abierto
    resultado = registrar_respuesta(db_session, sesion, presentacion, 3, "Juan", "0", 1000)
    assert resultado is None


def test_respuesta_duplicada_del_mismo_estudiante_no_se_duplica(db_session, seed_docente):
    from presentaciones import iniciar_slide, registrar_respuesta
    from models import RespuestaPresentacion

    presentacion = _crear_presentacion(db_session, seed_docente["docente"], seed_docente["grupo"])
    sesion = _crear_sesion(db_session, presentacion)
    iniciar_slide(db_session, sesion, 1)

    r1 = registrar_respuesta(db_session, sesion, presentacion, 1, "Juan", "1", 3000)
    r2 = registrar_respuesta(db_session, sesion, presentacion, 1, "Juan", "0", 1000)

    assert r1.id_respuesta == r2.id_respuesta
    total = db_session.query(RespuestaPresentacion).filter(
        RespuestaPresentacion.id_sesion == sesion.id_sesion,
    ).count()
    assert total == 1


# ─── 4. Conteos correctos por opción ───────────────────────────────

def test_resultado_multiple(db_session, seed_docente):
    from presentaciones import calcular_resultado, iniciar_slide, registrar_respuesta

    presentacion = _crear_presentacion(db_session, seed_docente["docente"], seed_docente["grupo"])
    sesion = _crear_sesion(db_session, presentacion)
    iniciar_slide(db_session, sesion, 1)  # slide "multiple", correcta=1

    registrar_respuesta(db_session, sesion, presentacion, 1, "Juan", "1", 3000)
    registrar_respuesta(db_session, sesion, presentacion, 1, "Ana", "0", 4000)
    registrar_respuesta(db_session, sesion, presentacion, 1, "Luis", "1", 2000)

    resultado = calcular_resultado(db_session, sesion, presentacion)
    assert resultado["conteos"] == {"0": 1, "1": 2, "2": 0, "3": 0}
    assert resultado["correcta"] == 1
    assert resultado["total_respuestas"] == 3

    nombres_ranking = {r["nombre"] for r in resultado["ranking_top5"]}
    assert nombres_ranking == {"Juan", "Ana", "Luis"}
    # Ana respondió incorrecto → 0 puntos, no debería superar a Juan/Luis.
    puntos = {r["nombre"]: r["puntos"] for r in resultado["ranking_top5"]}
    assert puntos["Ana"] == 0
    assert puntos["Juan"] > 0
    assert puntos["Luis"] > puntos["Juan"]  # Luis respondió más rápido


def test_resultado_poll_no_expone_correcta(db_session, seed_docente):
    from presentaciones import calcular_resultado, iniciar_slide, registrar_respuesta

    presentacion = _crear_presentacion(db_session, seed_docente["docente"], seed_docente["grupo"])
    sesion = _crear_sesion(db_session, presentacion)
    iniciar_slide(db_session, sesion, 3)  # slide "poll"

    registrar_respuesta(db_session, sesion, presentacion, 3, "Juan", "0", None)

    resultado = calcular_resultado(db_session, sesion, presentacion)
    assert resultado["correcta"] is None
    assert resultado["conteos"]["0"] == 1


# ─── 5. Finalizar cambia estado en DB ──────────────────────────────

def test_sesion_finalizada(db_session, seed_docente):
    from presentaciones import finalizar_sesion

    presentacion = _crear_presentacion(db_session, seed_docente["docente"], seed_docente["grupo"])
    sesion = _crear_sesion(db_session, presentacion)
    assert sesion.estado == "esperando"

    finalizar_sesion(db_session, sesion)
    db_session.refresh(sesion)

    assert sesion.estado == "finalizada"
    assert sesion.finalizado_en is not None
    assert sesion.slide_abierto is False


# ─── 6. Sanitización XSS en nombre / respuesta de estudiante ───────

def test_nombre_estudiante_se_sanitiza(db_session, seed_docente):
    from presentaciones import iniciar_slide, registrar_respuesta

    presentacion = _crear_presentacion(db_session, seed_docente["docente"], seed_docente["grupo"])
    sesion = _crear_sesion(db_session, presentacion)
    iniciar_slide(db_session, sesion, 1)

    resultado = registrar_respuesta(
        db_session, sesion, presentacion, 1,
        "<script>alert(1)</script>Juan", "1", 1000,
    )
    assert resultado is not None
    assert "<script>" not in resultado.nombre_estudiante
    assert "Juan" in resultado.nombre_estudiante


# ─── 7. BUG 1 (SPRINT 1) — _validar_diapositivas normaliza `cuerpo` ──
# El prompt pide "cuerpo: explicación en máx 4 puntos concisos", lo que
# empuja a la IA a devolver un array en vez de un párrafo. Antes de este
# fix, str(lista) guardaba literalmente "['a', 'b']" en la DB — bug
# reportado en clase real (corchetes y comillas visibles en pantalla).

def test_validar_diapositivas_cuerpo_como_array_se_preserva_como_lista():
    from presentaciones import _validar_diapositivas

    bruto = [{
        "tipo": "contenido",
        "titulo": "Diagrama de cuerpo libre",
        "cuerpo": [
            "Es un dibujo simplificado que muestra TODAS las fuerzas que actúan sobre un objeto",
            "El objeto se representa como un punto o forma simple",
        ],
        "notas_docente": "Dibujar un ejemplo en el tablero.",
    }]
    limpias = _validar_diapositivas(bruto)
    assert len(limpias) == 1
    cuerpo = limpias[0]["cuerpo"]
    assert isinstance(cuerpo, list)
    assert cuerpo == [
        "Es un dibujo simplificado que muestra TODAS las fuerzas que actúan sobre un objeto",
        "El objeto se representa como un punto o forma simple",
    ]


def test_validar_diapositivas_cuerpo_como_string_se_preserva_como_string():
    from presentaciones import _validar_diapositivas

    bruto = [{
        "tipo": "contenido",
        "titulo": "Título normal",
        "cuerpo": "Un párrafo normal de una sola pieza.",
        "notas_docente": "x",
    }]
    limpias = _validar_diapositivas(bruto)
    assert limpias[0]["cuerpo"] == "Un párrafo normal de una sola pieza."
    assert isinstance(limpias[0]["cuerpo"], str)


def test_validar_diapositivas_cuerpo_como_string_json_se_parsea_a_lista():
    from presentaciones import _validar_diapositivas

    bruto = [{
        "tipo": "contenido",
        "titulo": "Título normal",
        "cuerpo": '["Primer punto", "Segundo punto"]',
        "notas_docente": "x",
    }]
    limpias = _validar_diapositivas(bruto)
    assert limpias[0]["cuerpo"] == ["Primer punto", "Segundo punto"]


def test_validar_diapositivas_titulo_como_array_se_une_en_un_string():
    """titulo/pregunta/instruccion/notas_docente siempre deben quedar
    como string plano (nunca lista) — a diferencia de cuerpo."""
    from presentaciones import _validar_diapositivas

    bruto = [{
        "tipo": "contenido",
        "titulo": ["Diagrama", "de", "cuerpo libre"],
        "cuerpo": "Cuerpo normal.",
        "notas_docente": "x",
    }]
    limpias = _validar_diapositivas(bruto)
    assert limpias[0]["titulo"] == "Diagrama de cuerpo libre"
    assert isinstance(limpias[0]["titulo"], str)


def test_validar_diapositivas_pregunta_como_array_se_une_en_un_string():
    from presentaciones import _validar_diapositivas

    bruto = [{
        "tipo": "multiple",
        "pregunta": ["¿Cuál", "es la fuerza neta?"],
        "opciones": ["A", "B"],
        "correcta": 0,
    }]
    limpias = _validar_diapositivas(bruto)
    assert limpias[0]["pregunta"] == "¿Cuál es la fuerza neta?"


def test_validar_diapositivas_opcion_como_array_se_une_en_un_string():
    from presentaciones import _validar_diapositivas

    bruto = [{
        "tipo": "multiple",
        "pregunta": "¿Cuál es correcta?",
        "opciones": [["2", "/", "4"], "1/3"],
        "correcta": 0,
    }]
    limpias = _validar_diapositivas(bruto)
    assert limpias[0]["opciones"][0] == "2 / 4"
    assert limpias[0]["opciones"][1] == "1/3"
