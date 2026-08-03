"""
Sprint reset-limites-periodo — purga de rate_limit_counter vía endpoint
admin (`Docente.es_admin`, mismo flag que ya bypasea el rate limit
diario). Pensado para llamarse desde un cron externo o a mano al
iniciar un nuevo período académico.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from auth import get_current_docente, hash_password
from database import get_db
from models import Docente, RateLimitCounter


def _client_como(app, db_session, docente):
    def _override_get_db():
        try:
            yield db_session
        finally:
            pass
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_docente] = lambda: docente
    return TestClient(app)


def test_reset_limites_requiere_admin(test_engine, db_session):
    from main import app

    docente = Docente(
        nombre_completo="No Admin", email="noadmin@test.com",
        password_hash=hash_password("x"), es_admin=False,
    )
    db_session.add(docente); db_session.commit(); db_session.refresh(docente)

    client = _client_como(app, db_session, docente)
    r = client.post("/api/admin/reset-limites-periodo")
    assert r.status_code == 403
    app.dependency_overrides.clear()


def test_reset_limites_admin_purga_todos_los_contadores(test_engine, db_session):
    from main import app

    admin = Docente(
        nombre_completo="Admin", email="admin2@test.com",
        password_hash=hash_password("x"), es_admin=True,
    )
    docente = Docente(
        nombre_completo="Docente", email="docente2@test.com",
        password_hash=hash_password("x"), es_admin=False,
    )
    db_session.add_all([admin, docente])
    db_session.commit()
    db_session.refresh(admin)
    db_session.refresh(docente)

    db_session.add_all([
        RateLimitCounter(id_docente=admin.id_docente, fecha="2026-08-01", modo="planeacion", count=10),
        RateLimitCounter(id_docente=docente.id_docente, fecha="2026-08-01", modo="piar", count=5),
        RateLimitCounter(id_docente=docente.id_docente, fecha="2026-08-02", modo="calificacion", count=3),
    ])
    db_session.commit()
    assert db_session.query(RateLimitCounter).count() == 3

    client = _client_como(app, db_session, admin)
    r = client.post("/api/admin/reset-limites-periodo")
    assert r.status_code == 200
    assert r.json()["contadores_eliminados"] == 3
    assert db_session.query(RateLimitCounter).count() == 0
    app.dependency_overrides.clear()


def test_reset_limites_sin_contadores_devuelve_cero(test_engine, db_session):
    from main import app

    admin = Docente(
        nombre_completo="Admin Vacío", email="admin3@test.com",
        password_hash=hash_password("x"), es_admin=True,
    )
    db_session.add(admin); db_session.commit(); db_session.refresh(admin)

    client = _client_como(app, db_session, admin)
    r = client.post("/api/admin/reset-limites-periodo")
    assert r.status_code == 200
    assert r.json()["contadores_eliminados"] == 0
    app.dependency_overrides.clear()
