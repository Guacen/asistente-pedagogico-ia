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
        Grupo, Mensaje, Nota, Suscripcion, UsoMensual,
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


@pytest.fixture(scope="function")
def seed_docente(db_session):
    """Crea un docente y un grupo mínimo para las pruebas."""
    from models import Docente, Grupo
    docente = Docente(
        nombre_completo="Test Docente",
        email="test@test.com",
        password_hash="fake",  # no lo verificamos: bypass de auth vía override
    )
    db_session.add(docente)
    db_session.flush()
    grupo = Grupo(
        id_docente=docente.id_docente,
        nombre_grupo="Grupo Test",
        grado="8°",
        asignatura="matematicas",
        anio_lectivo=2026,
        periodo_actual=1,
        cantidad_estudiantes=10,
    )
    db_session.add(grupo)
    db_session.commit()
    db_session.refresh(docente)
    db_session.refresh(grupo)
    return {"docente": docente, "grupo": grupo}


@pytest.fixture(scope="function")
def client(test_engine, db_session, seed_docente):
    """
    TestClient con:
    - get_db → sesión in-memory
    - get_current_docente → el docente sembrado
    Evita el startup de main.py (que apunta a la DB real de dev).
    """
    from main import app
    from database import get_db
    from auth import get_current_docente

    def _override_get_db():
        try:
            yield db_session
        finally:
            pass  # el fixture db_session lo cierra

    def _override_current_docente():
        return seed_docente["docente"]

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_docente] = _override_current_docente

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()
