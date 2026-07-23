"""
Fixtures compartidas para los tests de integración.

Estrategia:
- SQLite en memoria (aislado por test, no toca asistente_pedagogico.db).
- dependency_overrides para inyectar la sesión de test y el docente autenticado.
- No se depende del startup handler de main.py (create_tables/migrate/seed) —
  cada test crea las tablas que necesita sobre su engine efímero.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Permite que los tests importen módulos del backend (config, models, etc.)
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


@pytest.fixture(scope="function")
def test_engine():
    """Engine SQLite en memoria, aislado por test."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,   # comparte la conexión entre threads del test
    )
    from database import Base
    from models import (  # noqa: F401 — asegura registro de tablas en Base
        Archivo, Calificacion, Docente, Estudiante, EvaluacionColumna,
        Grupo, Mensaje, Nota, RateLimitCounter, Suscripcion, UsoMensual,
    )
    Base.metadata.create_all(bind=engine)
    yield engine
    engine.dispose()


@pytest.fixture(scope="function")
def db_session(test_engine):
    TestSession = sessionmaker(bind=test_engine, autocommit=False, autoflush=False)
    session = TestSession()
    try:
        yield session
    finally:
        session.close()


# ─── Docentes sembrados (para tests que necesitan datos base) ──────────────
def _make_docente(db_session, email: str, nombre: str, password_plain: str = "test1234"):
    from models import Docente
    from auth import hash_password
    docente = Docente(
        nombre_completo=nombre,
        email=email,
        password_hash=hash_password(password_plain),
    )
    db_session.add(docente)
    db_session.commit()
    db_session.refresh(docente)
    return docente


def _make_grupo(db_session, docente, nombre="Grupo Test"):
    from models import Grupo
    grupo = Grupo(
        id_docente=docente.id_docente,
        nombre_grupo=nombre,
        grado="8°",
        asignatura="matematicas",
        anio_lectivo=2026,
        periodo_actual=1,
        cantidad_estudiantes=10,
    )
    db_session.add(grupo)
    db_session.commit()
    db_session.refresh(grupo)
    return grupo


@pytest.fixture(scope="function")
def seed_docente(db_session):
    """Docente A con un grupo Test. Mantiene compatibilidad con tests previos."""
    docente = _make_docente(db_session, "test@test.com", "Docente A", "test1234")
    grupo = _make_grupo(db_session, docente, "Grupo A")
    return {"docente": docente, "grupo": grupo, "password": "test1234"}


@pytest.fixture(scope="function")
def seed_docente_b(db_session):
    """Docente B — usado en tests de aislamiento (Fase B)."""
    docente = _make_docente(db_session, "otro@test.com", "Docente B", "test5678")
    grupo = _make_grupo(db_session, docente, "Grupo B")
    return {"docente": docente, "grupo": grupo, "password": "test5678"}


# ─── Clients ───────────────────────────────────────────────────────────────
def _install_db_override(app, db_session):
    from database import get_db
    def _override_get_db():
        try:
            yield db_session
        finally:
            pass
    app.dependency_overrides[get_db] = _override_get_db


@pytest.fixture(scope="function")
def client(test_engine, db_session, seed_docente):
    """
    TestClient con:
    - get_db → sesión in-memory
    - get_current_docente → docente A sembrado
    Evita el startup handler de main.py (que apunta a la DB real de dev).
    """
    from main import app
    from auth import get_current_docente

    _install_db_override(app, db_session)
    app.dependency_overrides[get_current_docente] = lambda: seed_docente["docente"]

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()


@pytest.fixture(scope="function")
def client_as_b(test_engine, db_session, seed_docente_b):
    """Cliente autenticado como docente B (para tests de aislamiento)."""
    from main import app
    from auth import get_current_docente

    _install_db_override(app, db_session)
    app.dependency_overrides[get_current_docente] = lambda: seed_docente_b["docente"]

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()


@pytest.fixture(scope="function")
def client_no_auth(test_engine, db_session):
    """
    Cliente SIN override de auth — para probar el flujo real de login/JWT.
    Sólo sobreescribe get_db (para no tocar la BD real).
    """
    from main import app
    _install_db_override(app, db_session)

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()


@pytest.fixture(scope="function")
def two_docentes(db_session):
    """
    Escenario para tests de aislamiento: dos docentes cada uno con su grupo.
    Docente A y Docente B viven en la misma DB pero no deben verse.
    """
    a = _make_docente(db_session, "docentea@test.com", "Docente A", "passA1234")
    b = _make_docente(db_session, "docenteb@test.com", "Docente B", "passB1234")
    ga = _make_grupo(db_session, a, "Grupo A")
    gb = _make_grupo(db_session, b, "Grupo B")
    return {
        "a": {"docente": a, "grupo": ga, "password": "passA1234"},
        "b": {"docente": b, "grupo": gb, "password": "passB1234"},
    }


@pytest.fixture(scope="function")
def client_two_docentes(test_engine, db_session, two_docentes):
    """
    Devuelve un helper para autenticar como A o como B dinámicamente dentro
    del mismo test — se usa en test_aislamiento_docentes.
    """
    from main import app
    from auth import get_current_docente

    _install_db_override(app, db_session)

    current = {"actor": two_docentes["a"]["docente"]}
    app.dependency_overrides[get_current_docente] = lambda: current["actor"]

    def as_a():
        current["actor"] = two_docentes["a"]["docente"]

    def as_b():
        current["actor"] = two_docentes["b"]["docente"]

    with TestClient(app) as c:
        yield {"client": c, "as_a": as_a, "as_b": as_b, "data": two_docentes}

    app.dependency_overrides.clear()
