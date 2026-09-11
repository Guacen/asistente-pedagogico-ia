"""
Tests de Presentaciones Interactivas tipo Kahoot (sprint
presentaciones-interactivas).

NUNCA se llama a Claude/Gemini real: desde SPRINT 5 la generación corre
en dos fases (esqueleto + relleno por diapositiva) — _generar_esqueleto_ia
y _generar_relleno_contenido_ia/_generar_relleno_pregunta_ia se mockean
con monkeypatch (mismo patrón que piar._sintetizar_conversacion_a_json
en test_piar.py) para devolver datos canned.

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
    """Diapositivas ya RELLENAS (formato final), usadas por
    _crear_presentacion para las pruebas de sesión en vivo — no pasan
    por la generación con IA."""
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


def _esqueleto_canned() -> list[dict]:
    """Esqueleto (fase 1) canned — 2 contenido + 2 pregunta,
    intercalados, que _generar_relleno_* de abajo sabe rellenar."""
    return [
        {"tipo": "contenido", "titulo": "Qué es la media aritmética"},
        {"tipo": "pregunta", "titulo": "¿Cuál es la media de 2, 4 y 6?"},
        {"tipo": "contenido", "titulo": "Para qué sirve la media"},
        {"tipo": "pregunta", "titulo": "¿Es útil la media?"},
    ]


@pytest.fixture(autouse=True)
def _mock_generacion_ia(monkeypatch, test_engine):
    """Reemplaza las llamadas a la IA por mocks async con datos canned,
    en TODOS los tests de este archivo — POST /generar nunca golpea la
    API real. SPRINT 5: la generación corre en dos fases, así que se
    mockean las tres piezas que hablan con el LLM (esqueleto + relleno
    de contenido + relleno de pregunta).

    SPRINT 4: la generación real ahora corre en background
    (asyncio.create_task) y abre su PROPIA sesión de DB vía
    presentaciones.SessionLocal() — bajo TestClient esa task sí llega a
    ejecutarse dentro del ciclo de vida del request (confirmado
    empíricamente), pero SessionLocal() por default apunta a la DB real
    de dev, no al test_engine efímero. Sin este patch, el background
    nunca encuentra el grupo/presentación recién creados y todo termina
    en estado='error' con "el grupo ya no existe".
    """
    import presentaciones as presentaciones_module
    from sqlalchemy.orm import sessionmaker

    esqueleto_mock = AsyncMock(return_value=_esqueleto_canned())
    monkeypatch.setattr(presentaciones_module, "_generar_esqueleto_ia", esqueleto_mock)

    async def _relleno_contenido(grupo, tema, titulo, posicion, total):
        return {"tipo": "contenido", "titulo": titulo, "cuerpo": "x", "notas_docente": "x"}

    async def _relleno_pregunta(grupo, tema, titulo, posicion, total, tipos_pregunta, tiempo_pregunta_s=20):
        return {
            "tipo": "multiple", "pregunta": titulo, "opciones": ["A", "B", "C", "D"],
            "correcta": 0, "tiempo_s": tiempo_pregunta_s, "puntos": 100,
        }

    monkeypatch.setattr(presentaciones_module, "_generar_relleno_contenido_ia", _relleno_contenido)
    monkeypatch.setattr(presentaciones_module, "_generar_relleno_pregunta_ia", _relleno_pregunta)

    TestSession = sessionmaker(bind=test_engine, autocommit=False, autoflush=False)
    monkeypatch.setattr(presentaciones_module, "SessionLocal", TestSession)
    return esqueleto_mock


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
# SPRINT 4: el endpoint responde 202 con estado='generando' de inmediato
# — la generación real corre en background. Bajo TestClient esa task
# efectivamente corre y termina dentro del ciclo del propio request
# (confirmado empíricamente en este archivo), así que el resultado final
# ya está disponible en un GET inmediatamente después.

def test_generar_presentacion(client, seed_docente):
    r = client.post("/api/presentaciones/generar", json={
        "grupo_id": seed_docente["grupo"].id_grupo,
        "tema": "Media aritmética",
        "n_slides_contenido": 4,
    })
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["titulo"]
    assert body["tema"] == "Media aritmética"
    assert body["estado"] == "generando"
    assert body["diapositivas"] == []
    pid = body["id_presentacion"]

    r2 = client.get(f"/api/presentaciones/{pid}")
    assert r2.status_code == 200, r2.text
    body2 = r2.json()
    assert body2["estado"] == "lista"
    tipos = [d["tipo"] for d in body2["diapositivas"]]
    assert tipos == ["contenido", "multiple", "contenido", "multiple"]


def test_generar_presentacion_grupo_ajeno_devuelve_404(client, seed_docente_b):
    """Un docente no puede generar presentaciones para un grupo que no es suyo."""
    r = client.post("/api/presentaciones/generar", json={
        "grupo_id": seed_docente_b["grupo"].id_grupo,
        "tema": "Media aritmética",
    })
    assert r.status_code == 404


def test_generar_presentacion_sin_slides_validas_deja_estado_error(client, seed_docente, monkeypatch):
    """
    SPRINT 4: el endpoint YA NO devuelve 502 síncrono — siempre responde
    202 de inmediato. Si la IA no produce slides válidas, la fila queda
    en estado='error' (consultable vía GET /{id}/estado), nunca colgada
    en 'generando'.
    """
    import presentaciones as presentaciones_module
    monkeypatch.setattr(
        presentaciones_module, "_generar_esqueleto_ia", AsyncMock(return_value=[]),
    )
    r = client.post("/api/presentaciones/generar", json={
        "grupo_id": seed_docente["grupo"].id_grupo,
        "tema": "Tema random",
    })
    assert r.status_code == 202
    pid = r.json()["id_presentacion"]

    r2 = client.get(f"/api/presentaciones/{pid}/estado")
    assert r2.status_code == 200
    body2 = r2.json()
    assert body2["estado"] == "error"
    assert body2["error_generacion"]


def test_generar_presentacion_error_proveedor_ia_deja_estado_error_con_mensaje_real(
    client, seed_docente, monkeypatch,
):
    """
    Si el proveedor de IA falla (sin API key, timeout, etc.) la
    presentación queda en estado='error' con el MENSAJE REAL de la
    excepción guardado — para poder diagnosticar sin depender de los
    logs de Railway (SPRINT 4, Parte B).
    """
    import presentaciones as presentaciones_module
    monkeypatch.setattr(
        presentaciones_module, "_generar_esqueleto_ia",
        AsyncMock(side_effect=RuntimeError("proveedor no configurado")),
    )
    r = client.post("/api/presentaciones/generar", json={
        "grupo_id": seed_docente["grupo"].id_grupo,
        "tema": "Tema random",
    })
    assert r.status_code == 202
    pid = r.json()["id_presentacion"]

    r2 = client.get(f"/api/presentaciones/{pid}/estado")
    assert r2.status_code == 200
    body2 = r2.json()
    assert body2["estado"] == "error"
    assert "proveedor no configurado" in body2["error_generacion"]


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
    assert r_gen.status_code == 202, r_gen.text
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


def test_podio_multiple_puntua_por_acierto_y_velocidad(db_session, seed_docente):
    """SPRINT 6: el ranking con puntaje vive en calcular_podio, no en
    calcular_resultado (que sólo trae la distribución del slide actual,
    sin nombres ni puntajes)."""
    from presentaciones import calcular_podio, iniciar_slide, registrar_respuesta

    presentacion = _crear_presentacion(db_session, seed_docente["docente"], seed_docente["grupo"])
    sesion = _crear_sesion(db_session, presentacion)
    iniciar_slide(db_session, sesion, 1)  # slide "multiple", correcta=1

    registrar_respuesta(db_session, sesion, presentacion, 1, "Juan", "1", 3000)
    registrar_respuesta(db_session, sesion, presentacion, 1, "Ana", "0", 4000)
    registrar_respuesta(db_session, sesion, presentacion, 1, "Luis", "1", 2000)

    podio = calcular_podio(db_session, sesion, presentacion)
    nombres_ranking = {r["nombre"] for r in podio["ranking"]}
    assert nombres_ranking == {"Juan", "Ana", "Luis"}
    # Ana respondió incorrecto → 0 puntos, no debería superar a Juan/Luis.
    puntos = {r["nombre"]: r["puntaje_acumulado"] for r in podio["ranking"]}
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


# ═══════════════════════════════════════════════════════════════
# 8. SPRINT 2/5 — validación de rangos de generación (contenido/preguntas)
# ═══════════════════════════════════════════════════════════════

def _slide_pregunta(tipo="multiple"):
    if tipo == "verdadero_falso":
        return {
            "tipo": "verdadero_falso", "pregunta": "¿Es correcto?",
            "opciones": ["Verdadero", "Falso"], "correcta": 0,
        }
    return {"tipo": "multiple", "pregunta": "¿Cuál?", "opciones": ["A", "B"], "correcta": 0}


def test_generar_presentacion_deja_estado_error_si_esqueleto_nunca_coincide(client, seed_docente, monkeypatch):
    """Extremo a extremo por el endpoint: si _generar_esqueleto_ia
    devuelve [] (conteo nunca coincidió tras el reintento), la fila
    queda en estado='error' — no una presentación incompleta ni un 500."""
    import presentaciones as presentaciones_module
    monkeypatch.setattr(
        presentaciones_module, "_generar_esqueleto_ia", AsyncMock(return_value=[]),
    )
    r = client.post("/api/presentaciones/generar", json={
        "grupo_id": seed_docente["grupo"].id_grupo,
        "tema": "Tema random",
        "n_slides_contenido": 8,
        "n_preguntas": 4,
    })
    assert r.status_code == 202
    pid = r.json()["id_presentacion"]
    r2 = client.get(f"/api/presentaciones/{pid}/estado")
    assert r2.json()["estado"] == "error"


def test_generar_presentacion_rechaza_rango_invalido_de_conteos(client, seed_docente):
    r = client.post("/api/presentaciones/generar", json={
        "grupo_id": seed_docente["grupo"].id_grupo,
        "tema": "Tema random",
        "n_slides_contenido": 2,  # por debajo del mínimo (4)
    })
    assert r.status_code == 422


def test_generar_presentacion_rechaza_tipos_pregunta_vacios(client, seed_docente):
    r = client.post("/api/presentaciones/generar", json={
        "grupo_id": seed_docente["grupo"].id_grupo,
        "tema": "Tema random",
        "tipos_pregunta": [],
    })
    assert r.status_code == 422


def test_generar_presentacion_rechaza_mas_preguntas_que_contenido(client, seed_docente):
    """SPRINT 5, Parte A: no puede pedirse más preguntas que
    diapositivas de contenido."""
    r = client.post("/api/presentaciones/generar", json={
        "grupo_id": seed_docente["grupo"].id_grupo,
        "tema": "Tema random",
        "n_slides_contenido": 4,
        "n_preguntas": 5,
    })
    assert r.status_code == 422


def test_generar_presentacion_acepta_preguntas_igual_a_contenido(client, seed_docente):
    r = client.post("/api/presentaciones/generar", json={
        "grupo_id": seed_docente["grupo"].id_grupo,
        "tema": "Tema random",
        "n_slides_contenido": 4,
        "n_preguntas": 4,
    })
    assert r.status_code == 202, r.text


# ═══════════════════════════════════════════════════════════════
# 9. SPRINT 2 — validación del catálogo cerrado de diagramas SVG
# ═══════════════════════════════════════════════════════════════

def test_validar_diagrama_fuerzas_valido():
    from presentaciones import _validar_diagrama
    raw = {"tipo": "fuerzas", "datos": {
        "objeto": "Caja",
        "fuerzas": [
            {"nombre": "Peso", "direccion": "abajo", "magnitud": 3},
            {"nombre": "Normal", "direccion": "arriba", "magnitud": 3},
        ],
    }}
    out = _validar_diagrama(raw)
    assert out["tipo"] == "fuerzas"
    assert out["datos"]["objeto"] == "Caja"
    assert len(out["datos"]["fuerzas"]) == 2


def test_validar_diagrama_ciclo_valido():
    from presentaciones import _validar_diagrama
    raw = {"tipo": "ciclo", "datos": {"pasos": ["Uno", "Dos", "Tres"]}}
    out = _validar_diagrama(raw)
    assert out["datos"]["pasos"] == ["Uno", "Dos", "Tres"]


def test_validar_diagrama_ciclo_invalido_con_menos_de_3_pasos():
    from presentaciones import _validar_diagrama
    raw = {"tipo": "ciclo", "datos": {"pasos": ["Uno", "Dos"]}}
    assert _validar_diagrama(raw) is None


def test_validar_diagrama_linea_tiempo_valido():
    from presentaciones import _validar_diagrama
    raw = {"tipo": "linea_tiempo", "datos": {"eventos": [
        {"etiqueta": "1810", "texto": "Independencia"},
        {"etiqueta": "1819", "texto": "Boyacá"},
    ]}}
    out = _validar_diagrama(raw)
    assert len(out["datos"]["eventos"]) == 2


def test_validar_diagrama_comparacion_valido():
    from presentaciones import _validar_diagrama
    raw = {"tipo": "comparacion", "datos": {
        "titulo_izquierda": "Mitosis", "items_izquierda": ["1 división"],
        "titulo_derecha": "Meiosis", "items_derecha": ["2 divisiones"],
    }}
    out = _validar_diagrama(raw)
    assert out["datos"]["titulo_izquierda"] == "Mitosis"


def test_validar_diagrama_jerarquia_valido():
    from presentaciones import _validar_diagrama
    raw = {"tipo": "jerarquia", "datos": {"raiz": "Reino Animal", "hijos": ["Vertebrados", "Invertebrados"]}}
    out = _validar_diagrama(raw)
    assert out["datos"]["raiz"] == "Reino Animal"
    assert len(out["datos"]["hijos"]) == 2


def test_validar_diagrama_proceso_valido():
    from presentaciones import _validar_diagrama
    raw = {"tipo": "proceso", "datos": {"pasos": ["Paso 1", "Paso 2"]}}
    out = _validar_diagrama(raw)
    assert out["datos"]["pasos"] == ["Paso 1", "Paso 2"]


@pytest.mark.parametrize("raw", [
    None,
    "no es un dict",
    123,
    [],
    {"tipo": "tipo_inventado", "datos": {}},
    {"tipo": "fuerzas"},  # sin "datos"
    {"tipo": "fuerzas", "datos": "no es un dict"},
    {"tipo": "fuerzas", "datos": {"objeto": "Caja", "fuerzas": "no es lista"}},
    {"tipo": "fuerzas", "datos": {"objeto": "Caja", "fuerzas": [{"nombre": "Peso", "direccion": "diagonal"}]}},
    {"tipo": "jerarquia", "datos": {"raiz": "x", "hijos": ["solo uno"]}},
    {"tipo": "comparacion", "datos": {"titulo_izquierda": "A", "items_izquierda": [], "titulo_derecha": "B", "items_derecha": ["x"]}},
    {"tipo": "proceso", "datos": {"pasos": ["solo uno"]}},
])
def test_validar_diagrama_nunca_revienta_con_datos_malformados(raw):
    """Cualquier forma inesperada devuelve None — nunca levanta
    excepción y nunca rompe la diapositiva que lo contiene."""
    from presentaciones import _validar_diagrama
    assert _validar_diagrama(raw) is None


def test_validar_diapositivas_contenido_con_diagrama_valido_lo_incluye():
    from presentaciones import _validar_diapositivas
    bruto = [{
        "tipo": "contenido", "titulo": "T", "cuerpo": "x", "notas_docente": "x",
        "diagrama": {"tipo": "proceso", "datos": {"pasos": ["Paso 1", "Paso 2"]}},
    }]
    limpias = _validar_diapositivas(bruto)
    assert "diagrama" in limpias[0]
    assert limpias[0]["diagrama"]["tipo"] == "proceso"


def test_validar_diapositivas_contenido_con_diagrama_invalido_lo_omite_sin_romper_slide():
    """VERIFICACIÓN OBLIGATORIA #3: una respuesta de IA malformada (acá,
    un diagrama con forma inválida) no rompe la presentación — la
    diapositiva de contenido se valida igual, sólo sin la clave
    'diagrama'."""
    from presentaciones import _validar_diapositivas
    bruto = [{
        "tipo": "contenido", "titulo": "T", "cuerpo": "x", "notas_docente": "x",
        "diagrama": {"tipo": "no_existe", "datos": {"quien_sabe": 1}},
    }]
    limpias = _validar_diapositivas(bruto)
    assert len(limpias) == 1
    assert "diagrama" not in limpias[0]
    assert limpias[0]["titulo"] == "T"


def test_validar_diapositivas_sin_diagrama_no_incluye_la_clave():
    from presentaciones import _validar_diapositivas
    bruto = [{"tipo": "contenido", "titulo": "T", "cuerpo": "x", "notas_docente": "x"}]
    limpias = _validar_diapositivas(bruto)
    assert "diagrama" not in limpias[0]


# ═══════════════════════════════════════════════════════════════
# 10. SPRINT 2 — respuesta de IA totalmente malformada nunca rompe nada
# ═══════════════════════════════════════════════════════════════

@pytest.mark.parametrize("bruto", [
    None,
    "no es un array",
    123,
    {},
    [None, 123, "texto", []],
    [{"tipo": "contenido"}],  # sin titulo/cuerpo
    [{"tipo": "verdadero_falso"}],  # sin pregunta
    [{"sin_tipo": True}],
    [{"tipo": "contenido", "titulo": None, "cuerpo": None}],
])
def test_validar_diapositivas_nunca_revienta_con_bruto_malformado(bruto):
    from presentaciones import _validar_diapositivas
    resultado = _validar_diapositivas(bruto)
    assert isinstance(resultado, list)


# ═══════════════════════════════════════════════════════════════
# 11. SPRINT 2 — verdadero_falso se puntúa y cuenta igual que multiple
# ═══════════════════════════════════════════════════════════════

def test_registrar_respuesta_verdadero_falso_marca_correcta(db_session, seed_docente):
    from presentaciones import iniciar_slide, registrar_respuesta

    diapositivas = [_slide_pregunta("verdadero_falso")]
    diapositivas[0]["puntos"] = 100
    diapositivas[0]["tiempo_s"] = 15
    presentacion = _crear_presentacion(db_session, seed_docente["docente"], seed_docente["grupo"], diapositivas)
    sesion = _crear_sesion(db_session, presentacion)
    iniciar_slide(db_session, sesion, 0)

    correcta = registrar_respuesta(db_session, sesion, presentacion, 0, "Ana", "0", 1000)
    incorrecta = registrar_respuesta(db_session, sesion, presentacion, 0, "Beto", "1", 1000)

    assert correcta.es_correcta is True
    assert incorrecta.es_correcta is False


def test_calcular_resultado_verdadero_falso_expone_correcta_y_conteos(db_session, seed_docente):
    from presentaciones import iniciar_slide, registrar_respuesta, calcular_resultado

    diapositivas = [_slide_pregunta("verdadero_falso")]
    presentacion = _crear_presentacion(db_session, seed_docente["docente"], seed_docente["grupo"], diapositivas)
    sesion = _crear_sesion(db_session, presentacion)
    iniciar_slide(db_session, sesion, 0)
    registrar_respuesta(db_session, sesion, presentacion, 0, "Ana", "0", 1000)

    resultado = calcular_resultado(db_session, sesion, presentacion)
    assert resultado["correcta"] == 0
    assert resultado["conteos"] == {"0": 1, "1": 0}


def test_calcular_podio_verdadero_falso_cuenta_en_ranking(db_session, seed_docente):
    from presentaciones import iniciar_slide, registrar_respuesta, calcular_podio

    diapositivas = [_slide_pregunta("verdadero_falso")]
    presentacion = _crear_presentacion(db_session, seed_docente["docente"], seed_docente["grupo"], diapositivas)
    sesion = _crear_sesion(db_session, presentacion)
    iniciar_slide(db_session, sesion, 0)
    registrar_respuesta(db_session, sesion, presentacion, 0, "Ana", "0", 1000)

    podio = calcular_podio(db_session, sesion, presentacion)
    ranking = {r["nombre"]: r["puntaje_acumulado"] for r in podio["ranking"]}
    assert ranking.get("Ana", 0) > 0
