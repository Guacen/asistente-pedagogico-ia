"""
SPRINT 4 — generación asíncrona de presentaciones (extendida en SPRINT 7
a generación por secciones — ver test_presentaciones_secciones.py para
los tests específicos de multi-tema; este archivo cubre el contrato
básico de background/estado con una sola sección).

Contexto: POST /api/presentaciones/generar devolvía 502 desde Cloudflare
con generaciones grandes — el origen esperaba a Claude DENTRO del
request HTTP, más tiempo que el timeout de proxy. Ahora el endpoint crea
la fila con estado='generando' y responde 202 de inmediato; la
generación real corre en background (asyncio.create_task, no FastAPI
BackgroundTasks — ver comentario en presentaciones.py sobre por qué) y
dejará la fila en 'lista' o 'error', avisando al docente por
presentacion:generada.

Estos tests cubren las 3 verificaciones obligatorias del sprint 4:
1. El endpoint responde 202 en menos de 1 segundo.
2. Un fallo de la IA deja estado='error' con mensaje, sin colgarse.
3. El evento de socket llega a la ROOM del docente correcto.
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import presentaciones as presentaciones_module  # noqa: E402
from models import Presentacion  # noqa: E402


@pytest.fixture(autouse=True)
def _feature_presentaciones_activa(monkeypatch):
    """Ver test_presentaciones.py — mismo criterio, este archivo también
    golpea /api/presentaciones/* vía TestClient."""
    from config import settings
    monkeypatch.setattr(settings, "FEATURE_PRESENTACIONES", True)


def _patch_session_local(monkeypatch, test_engine):
    Session = sessionmaker(bind=test_engine, autocommit=False, autoflush=False)
    monkeypatch.setattr(presentaciones_module, "SessionLocal", Session)
    return Session


def _body_generar(grupo_id: str, tema: str = "Fracciones equivalentes", n_slides_contenido: int = 4, n_preguntas: int = 2) -> dict:
    """SPRINT 7: el endpoint recibe `secciones` (1 a 5 temas) — acá
    siempre una sola, que es lo que este archivo ejercita."""
    return {
        "grupo_id": grupo_id,
        "secciones": [{"tema": tema, "n_slides_contenido": n_slides_contenido, "n_preguntas": n_preguntas}],
    }


def _construir_secciones_y_diapositivas(temas_config):
    """[(tema, n_contenido, n_preguntas), ...] -> (secciones_meta,
    diapositivas) — replica a mano la lógica de
    presentaciones._construir_secciones_y_diapositivas_iniciales, pero
    sin pasar por SeccionRequest/pydantic (que exige n_slides_contenido
    >= 4) — los tests de este archivo llaman
    _ejecutar_generacion_en_background directo, sin pasar por POST
    /generar, así que no están sujetos al rango del schema HTTP."""
    secciones_meta: list[dict] = []
    diapositivas: list[dict] = []
    for tema, n_contenido, n_preguntas in temas_config:
        inicio = len(diapositivas)
        diapositivas.append({"tipo": "separador", "titulo": tema})
        diapositivas.extend({"tipo": "pendiente", "titulo": tema} for _ in range(n_contenido + n_preguntas))
        secciones_meta.append({
            "tema": tema, "n_slides_contenido": n_contenido, "n_preguntas": n_preguntas,
            "inicio": inicio, "fin": len(diapositivas) - 1, "estado": "generando", "error_generacion": None,
        })
    return secciones_meta, diapositivas


def _crear_presentacion_generando(db_session, docente, grupo, temas_config=None, id_grupo=None):
    temas_config = temas_config or [("T", 1, 0)]
    secciones_meta, diapositivas = _construir_secciones_y_diapositivas(temas_config)
    presentacion = Presentacion(
        id_docente=docente.id_docente, id_grupo=id_grupo if id_grupo is not None else grupo.id_grupo,
        titulo="T", tema="T", diapositivas=diapositivas, secciones=secciones_meta,
        estado="generando",
    )
    db_session.add(presentacion)
    db_session.commit()
    db_session.refresh(presentacion)
    return presentacion


# ═══════════════════════════════════════════════════════════════
# 1. El endpoint responde 202 en menos de 1 segundo — NUNCA espera
#    a la IA, sin importar cuánto tarde la generación real.
# ═══════════════════════════════════════════════════════════════

def test_generar_presentacion_responde_202_en_menos_de_1_segundo(client, seed_docente, monkeypatch):
    """
    Reemplaza el LANZADOR de la generación en background por un no-op
    que sólo registra que se lo llamó — así, si alguien revirtiera el
    código para esperar a la IA de forma síncrona en el propio
    endpoint (en vez de delegarlo), esta prueba lo detecta por el
    estado/llamadas devueltas, no sólo por el reloj (con un mock
    rápido, cualquier implementación "parece" rápida).
    """
    llamadas = []
    monkeypatch.setattr(
        presentaciones_module, "_lanzar_generacion_en_background",
        lambda *args, **kwargs: llamadas.append((args, kwargs)),
    )

    t0 = time.monotonic()
    r = client.post("/api/presentaciones/generar", json=_body_generar(seed_docente["grupo"].id_grupo))
    elapsed = time.monotonic() - t0

    assert r.status_code == 202, r.text
    assert elapsed < 1.0, f"tardó {elapsed:.2f}s — el endpoint no debe esperar a la IA"

    body = r.json()
    assert body["estado"] == "generando"
    # SPRINT 7: la separadora ya se persiste sin IA — el array no
    # arranca vacío, pero SÍ arranca sin ningún contenido real todavía.
    assert all(d["tipo"] in ("separador", "pendiente") for d in body["diapositivas"])
    assert len(llamadas) == 1, "el endpoint debe delegar la generación real, no ejecutarla inline"


def _mock_generacion_dos_fases(monkeypatch, slides):
    """Mockea las dos fases de generación para que produzcan `slides`
    (una lista de diapositivas YA RELLENAS) — el esqueleto se deriva
    de sus tipos/títulos y el relleno de cada una devuelve el slide
    completo tal cual, sin llamar a la IA real."""
    esqueleto = [
        {"tipo": "contenido" if s["tipo"] == "contenido" else "pregunta", "titulo": s.get("titulo") or s.get("pregunta")}
        for s in slides
    ]
    monkeypatch.setattr(
        presentaciones_module, "_generar_esqueleto_ia", AsyncMock(return_value=esqueleto),
    )

    async def _contenido(grupo, tema, titulo, posicion, total):
        return next(s for s in slides if s["tipo"] == "contenido" and s["titulo"] == titulo)

    async def _pregunta(grupo, tema, titulo, posicion, total, tipos_pregunta, tiempo_pregunta_s=20):
        return next(s for s in slides if s["tipo"] != "contenido" and s["pregunta"] == titulo)

    monkeypatch.setattr(presentaciones_module, "_generar_relleno_contenido_ia", _contenido)
    monkeypatch.setattr(presentaciones_module, "_generar_relleno_pregunta_ia", _pregunta)


def test_generar_presentacion_no_bloquea_aunque_la_ia_sea_lenta(client, seed_docente, monkeypatch, test_engine):
    """
    Variante más realista de la #1: la generación real SÍ está
    configurada (con el mock de IA normal, instantáneo) pero se
    verifica explícitamente que la respuesta no incluye ningún
    resultado de generación — sólo la confirmación de que se creó
    la fila y quedó en background.
    """
    _patch_session_local(monkeypatch, test_engine)
    _mock_generacion_dos_fases(monkeypatch, [
        {"tipo": "contenido", "titulo": "T", "cuerpo": "x", "notas_docente": "x"},
    ])
    t0 = time.monotonic()
    r = client.post("/api/presentaciones/generar", json=_body_generar(seed_docente["grupo"].id_grupo))
    elapsed = time.monotonic() - t0

    assert r.status_code == 202
    assert elapsed < 1.0
    assert r.json()["estado"] == "generando"


# ═══════════════════════════════════════════════════════════════
# 2. Un fallo de la IA deja estado='error' con mensaje — nunca
#    colgada en 'generando'.
# ═══════════════════════════════════════════════════════════════

def test_ejecutar_generacion_en_background_deja_error_sin_colgarse(db_session, test_engine, seed_docente, monkeypatch):
    """
    Llama _ejecutar_generacion_en_background directo (sin pasar por
    HTTP) — si la IA revienta con una excepción cualquiera, la función
    debe TERMINAR normalmente (no propagar la excepción — sería fatal
    para una task de background sin nadie que la capture) y dejar la
    fila en estado='error' con el mensaje real.
    """
    _patch_session_local(monkeypatch, test_engine)
    monkeypatch.setattr(
        presentaciones_module, "_generar_esqueleto_ia",
        AsyncMock(side_effect=TimeoutError("la API de Claude no respondió a tiempo")),
    )
    docente = seed_docente["docente"]
    grupo = seed_docente["grupo"]
    presentacion = _crear_presentacion_generando(db_session, docente, grupo)

    # No debe lanzar — una excepción sin capturar acá desaparece en
    # silencio (asyncio no tiene a quién reportársela) y deja la fila
    # colgada en 'generando' para siempre, exactamente el bug del sprint.
    asyncio.run(presentaciones_module._ejecutar_generacion_en_background(
        presentacion.id_presentacion, grupo.id_grupo, ["multiple"], docente.id_docente,
    ))

    db_session.refresh(presentacion)
    assert presentacion.estado == "error"
    assert presentacion.error_generacion
    assert "no respondió a tiempo" in presentacion.error_generacion


def test_ejecutar_generacion_en_background_exito_deja_lista(db_session, test_engine, seed_docente, monkeypatch):
    _patch_session_local(monkeypatch, test_engine)
    slides = [{"tipo": "contenido", "titulo": "T", "cuerpo": "x", "notas_docente": "x"}]
    _mock_generacion_dos_fases(monkeypatch, slides)
    docente = seed_docente["docente"]
    grupo = seed_docente["grupo"]
    presentacion = _crear_presentacion_generando(db_session, docente, grupo, [("T", 1, 0)])

    asyncio.run(presentaciones_module._ejecutar_generacion_en_background(
        presentacion.id_presentacion, grupo.id_grupo, ["multiple"], docente.id_docente,
    ))

    db_session.refresh(presentacion)
    assert presentacion.estado == "lista"
    # separadora (persistida sin IA) + el único slide de contenido.
    assert presentacion.diapositivas == [{"tipo": "separador", "titulo": "T"}] + slides
    assert presentacion.error_generacion is None


def test_ejecutar_generacion_en_background_grupo_borrado_deja_error(db_session, test_engine, seed_docente, monkeypatch):
    """Si el grupo se borra mientras la generación estaba en camino, la
    función tampoco debe colgarse ni reventar — deja error explícito."""
    _patch_session_local(monkeypatch, test_engine)
    docente = seed_docente["docente"]
    grupo = seed_docente["grupo"]
    presentacion = _crear_presentacion_generando(
        db_session, docente, grupo, id_grupo="grupo-que-no-existe",
    )

    asyncio.run(presentaciones_module._ejecutar_generacion_en_background(
        presentacion.id_presentacion, "grupo-que-no-existe", ["multiple"], docente.id_docente,
    ))

    db_session.refresh(presentacion)
    assert presentacion.estado == "error"
    assert presentacion.error_generacion


# ═══════════════════════════════════════════════════════════════
# 3. El evento presentacion:generada llega a la ROOM del docente
#    correcto (docente_{id}), no un broadcast global.
# ═══════════════════════════════════════════════════════════════

def test_presentacion_generada_se_emite_a_la_room_del_docente_dueno(
    db_session, test_engine, seed_docente, monkeypatch,
):
    _patch_session_local(monkeypatch, test_engine)
    slides = [{"tipo": "contenido", "titulo": "T", "cuerpo": "x", "notas_docente": "x"}]
    _mock_generacion_dos_fases(monkeypatch, slides)
    import socket_events
    emit_mock = AsyncMock()
    monkeypatch.setattr(socket_events.sio, "emit", emit_mock)

    docente = seed_docente["docente"]
    grupo = seed_docente["grupo"]
    presentacion = _crear_presentacion_generando(db_session, docente, grupo, [("T", 1, 0)])

    asyncio.run(presentaciones_module._ejecutar_generacion_en_background(
        presentacion.id_presentacion, grupo.id_grupo, ["multiple"], docente.id_docente,
    ))

    # 3 emits (esqueleto, slide_lista x1, generada) — todos a la misma
    # room del docente. El último es el de cierre.
    eventos = [c.args[0] for c in emit_mock.call_args_list]
    assert eventos == ["presentacion:esqueleto", "presentacion:slide_lista", "presentacion:generada"]
    assert all(c.kwargs.get("room") == f"docente_{docente.id_docente}" for c in emit_mock.call_args_list)

    payload = emit_mock.call_args_list[-1].args[1]
    assert payload["id_presentacion"] == presentacion.id_presentacion
    assert payload["estado"] == "lista"
    assert payload["error"] is None


def test_presentacion_generada_incluye_error_cuando_fallo(
    db_session, test_engine, seed_docente, monkeypatch,
):
    """El evento también debe llevar el mensaje de error cuando la
    generación falló — el docente no debe tener que ir a mirar logs."""
    _patch_session_local(monkeypatch, test_engine)
    monkeypatch.setattr(
        presentaciones_module, "_generar_esqueleto_ia",
        AsyncMock(side_effect=RuntimeError("boom")),
    )
    import socket_events
    emit_mock = AsyncMock()
    monkeypatch.setattr(socket_events.sio, "emit", emit_mock)

    docente = seed_docente["docente"]
    grupo = seed_docente["grupo"]
    presentacion = _crear_presentacion_generando(db_session, docente, grupo)

    asyncio.run(presentaciones_module._ejecutar_generacion_en_background(
        presentacion.id_presentacion, grupo.id_grupo, ["multiple"], docente.id_docente,
    ))

    payload = emit_mock.call_args.args[1]
    assert payload["estado"] == "error"
    assert "boom" in payload["error"]


def test_presentacion_generada_no_se_emite_a_room_de_otro_docente(
    db_session, test_engine, two_docentes, monkeypatch,
):
    """Verificación explícita de que la room usada es específica del
    docente DUEÑO de la presentación, no una constante compartida."""
    _patch_session_local(monkeypatch, test_engine)
    _mock_generacion_dos_fases(monkeypatch, [
        {"tipo": "contenido", "titulo": "T", "cuerpo": "x", "notas_docente": "x"},
    ])
    import socket_events
    emit_mock = AsyncMock()
    monkeypatch.setattr(socket_events.sio, "emit", emit_mock)

    docente_a = two_docentes["a"]["docente"]
    grupo_a = two_docentes["a"]["grupo"]
    docente_b = two_docentes["b"]["docente"]

    presentacion = _crear_presentacion_generando(db_session, docente_a, grupo_a, [("T", 1, 0)])

    asyncio.run(presentaciones_module._ejecutar_generacion_en_background(
        presentacion.id_presentacion, grupo_a.id_grupo, ["multiple"], docente_a.id_docente,
    ))

    room_usada = emit_mock.call_args.kwargs.get("room")
    assert room_usada == f"docente_{docente_a.id_docente}"
    assert room_usada != f"docente_{docente_b.id_docente}"


# ═══════════════════════════════════════════════════════════════
# Extra: GET /{id}/estado — respaldo de polling
# ═══════════════════════════════════════════════════════════════

def test_get_estado_presentacion_devuelve_estado_actual(client, db_session, seed_docente):
    presentacion = _crear_presentacion_generando(db_session, seed_docente["docente"], seed_docente["grupo"])

    r = client.get(f"/api/presentaciones/{presentacion.id_presentacion}/estado")
    assert r.status_code == 200
    body = r.json()
    assert body["estado"] == "generando"
    assert body["error_generacion"] is None


def test_get_estado_presentacion_ajena_devuelve_404(client_two_docentes):
    d = client_two_docentes
    d["as_a"]()
    r_gen = d["client"].post("/api/presentaciones/generar", json=_body_generar(d["data"]["a"]["grupo"].id_grupo))
    assert r_gen.status_code == 202
    pid = r_gen.json()["id_presentacion"]

    d["as_b"]()
    r = d["client"].get(f"/api/presentaciones/{pid}/estado")
    assert r.status_code == 404
