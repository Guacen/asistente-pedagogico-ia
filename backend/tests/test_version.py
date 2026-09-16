"""
GET /api/version — sprint xss-host-header (extra). Público, sin auth:
confirmar en una sola petición si un commit está vivo en producción, en
vez de adivinar comparando contenidos de archivos.
"""
from __future__ import annotations


def test_version_publico_sin_auth(client_no_auth):
    r = client_no_auth.get("/api/version")
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == {"commit", "desplegado"}


def test_version_sin_railway_git_commit_sha_devuelve_desconocido(client_no_auth, monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "RAILWAY_GIT_COMMIT_SHA", None)

    r = client_no_auth.get("/api/version")
    assert r.status_code == 200
    assert r.json()["commit"] == "desconocido"


def test_version_con_railway_git_commit_sha_devuelve_sha_corto(client_no_auth, monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "RAILWAY_GIT_COMMIT_SHA", "abcdef1234567890abcdef1234567890abcdef12")

    r = client_no_auth.get("/api/version")
    assert r.status_code == 200
    assert r.json()["commit"] == "abcdef1"


def test_version_desplegado_es_timestamp_iso(client_no_auth):
    from datetime import datetime
    r = client_no_auth.get("/api/version")
    desplegado = r.json()["desplegado"]
    assert desplegado.endswith("Z")
    # No debe fallar al parsear como ISO 8601 (quitando la 'Z').
    datetime.fromisoformat(desplegado[:-1])


def test_version_no_cambia_entre_requests(client_no_auth):
    """'desplegado' es la hora en que arrancó el proceso, no la hora de
    la request — dos pedidos seguidos deben devolver el mismo valor."""
    r1 = client_no_auth.get("/api/version").json()
    r2 = client_no_auth.get("/api/version").json()
    assert r1["desplegado"] == r2["desplegado"]
