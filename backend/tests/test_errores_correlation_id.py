"""
Sprint primer-uso, Parte C — ningún error técnico debe llegar a la
pantalla del docente (nada de stack traces, SQL, nombres de tablas,
tokens, "500 Internal Server Error"), pero cada error genera un
correlation_id visible al docente Y logueado en el servidor con el
detalle técnico completo — sin eso, Parte D (Reportar un problema) no
sirve para investigar nada.

Nota sobre TestClient y el handler global: TestClient(app) por default
tiene raise_server_exceptions=True — Starlette RE-LANZA la excepción
hacia el propio test en vez de dejar que el handler registrado
(@app.exception_handler(Exception) en main.py) la convierta en una
respuesta, que es exactamente lo que SÍ pasa en producción con un
servidor ASGI real (uvicorn). Los dos tests que ejercitan el handler de
verdad necesitan su propio TestClient con raise_server_exceptions=False
— si no, pytest ve la excepción "escaparse" del cliente de pruebas y
falla el test aunque el handler esté andando perfecto.
"""
from __future__ import annotations

import logging

from fastapi.routing import APIRoute
from starlette.testclient import TestClient


def _insertar_ruta_temporal(app, path, handler):
    """
    app.add_api_route() APPENDS al final de app.router.routes — pero
    main.py monta StaticFiles en "/" como catch-all AL FINAL del
    archivo, antes de que cualquier test corra. Si sólo agregamos al
    final, el catch-all (ya registrado primero) intercepta la ruta de
    prueba antes de llegar a ella. Insertarla al PRINCIPIO evita eso.
    """
    route = APIRoute(path, handler, methods=["GET"])
    app.router.routes.insert(0, route)


def _quitar_ruta_temporal(app, path):
    app.router.routes = [
        route for route in app.router.routes
        if getattr(route, "path", None) != path
    ]


def test_excepcion_no_manejada_no_filtra_detalle_tecnico(db_session):
    from main import app
    from database import get_db

    def _override_get_db():
        yield db_session
    app.dependency_overrides[get_db] = _override_get_db

    def _ruta_que_explota():
        raise ValueError("SELECT * FROM docentes WHERE password_hash = 'super-secreto-123'")

    _insertar_ruta_temporal(app, "/__test_error_interno__", _ruta_que_explota)
    try:
        with TestClient(app, raise_server_exceptions=False) as c:
            r = c.get("/__test_error_interno__")
        assert r.status_code == 500
        texto_crudo = r.text
        assert "SELECT" not in texto_crudo
        assert "password_hash" not in texto_crudo
        assert "super-secreto" not in texto_crudo
        assert "ValueError" not in texto_crudo
        assert "Traceback" not in texto_crudo

        body = r.json()
        assert body["detail"]["message"] == "Ocurrió un error inesperado. Intenta nuevamente."
        assert "correlation_id" in body["detail"]
        assert len(body["detail"]["correlation_id"]) == 8
    finally:
        _quitar_ruta_temporal(app, "/__test_error_interno__")
        app.dependency_overrides.clear()


def test_correlation_id_del_error_queda_en_el_log(db_session, caplog):
    from main import app
    from database import get_db

    def _override_get_db():
        yield db_session
    app.dependency_overrides[get_db] = _override_get_db

    def _ruta_que_explota():
        raise RuntimeError("boom interno")

    _insertar_ruta_temporal(app, "/__test_error_interno_log__", _ruta_que_explota)
    try:
        with caplog.at_level(logging.ERROR, logger="errores"):
            with TestClient(app, raise_server_exceptions=False) as c:
                r = c.get("/__test_error_interno_log__")
        correlation_id = r.json()["detail"]["correlation_id"]

        logueado = [rec for rec in caplog.records if correlation_id in rec.message]
        assert logueado, f"el correlation_id {correlation_id} no aparece en ningún log"
        # El log SÍ debe tener el detalle técnico real — eso es lo que
        # permite investigar, sólo no debe llegar al docente.
        assert any("boom interno" in rec.message or rec.exc_text for rec in logueado)
    finally:
        _quitar_ruta_temporal(app, "/__test_error_interno_log__")
        app.dependency_overrides.clear()


def test_errores_error_manejable_genera_correlation_id_y_loguea():
    from errores import error_manejable

    try:
        raise KeyError("id_columna")
    except KeyError as exc:
        http_exc = error_manejable(
            400, "No pudimos guardar la información. Intenta nuevamente.",
            contexto="test unitario", exc=exc,
        )

    assert http_exc.status_code == 400
    assert http_exc.detail["message"] == "No pudimos guardar la información. Intenta nuevamente."
    assert "correlation_id" in http_exc.detail
    assert "id_columna" not in http_exc.detail["message"]


def test_errores_correlation_ids_son_distintos_por_llamada():
    from errores import nuevo_correlation_id
    ids = {nuevo_correlation_id() for _ in range(50)}
    assert len(ids) == 50


# ═══════════════════════════════════════════════════════════════
# Integración real: uno de los 9 sitios que filtraban excepción cruda
# (ver test_sin_fugas_de_excepcion.py para el resto, chequeado estático)
# ═══════════════════════════════════════════════════════════════

def test_generar_documento_con_fallo_no_filtra_detalle_y_trae_correlation_id(
    client, seed_docente, monkeypatch,
):
    import documento

    def _docx_bytes_que_rompe(**kwargs):
        raise RuntimeError("python-docx: XMLSyntaxError en template.docx línea 42")

    monkeypatch.setattr(documento, "_docx_bytes", _docx_bytes_que_rompe)

    r = client.post(
        f"/api/grupos/{seed_docente['grupo'].id_grupo}/generar-documento",
        json={"contenido_md": "# Hola", "titulo": "Prueba"},
    )
    assert r.status_code == 500
    assert "XMLSyntaxError" not in r.text
    assert "template.docx" not in r.text
    assert "RuntimeError" not in r.text

    body = r.json()
    assert body["detail"]["message"] == "No pudimos generar el documento. Intenta nuevamente."
    assert len(body["detail"]["correlation_id"]) == 8
