"""
seed_dbas() — upsert (sprint dba-lenguaje-reextraido).

seed_dbas() usa el SessionLocal global de database.py, no la inyección
de dependencias de FastAPI (get_db) — por eso no puede usar los
fixtures client/db_session de conftest.py como el resto de la suite
(esos sólo interceptan get_db). Acá se monkeypatchea directamente
seed_dbas.SessionLocal y seed_dbas._SEED_PATH para aislarlo en un
engine y un JSON temporales, sin tocar la DB real de dev.
"""
from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import seed_dbas as seed_dbas_module
from database import Base
from models import DBA


@pytest.fixture
def seed_env(tmp_path, monkeypatch):
    """Engine SQLite temporal + JSON temporal, aislados de la DB real."""
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine, tables=[DBA.__table__])
    TestSession = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    monkeypatch.setattr(seed_dbas_module, "SessionLocal", TestSession)

    seed_path = tmp_path / "dba_seed_data.json"
    monkeypatch.setattr(seed_dbas_module, "_SEED_PATH", seed_path)

    def write_json(payload):
        seed_path.write_text(json.dumps(payload), encoding="utf-8")

    session = TestSession()
    yield write_json, session
    session.close()
    engine.dispose()


def test_inserta_dbas_nuevos(seed_env):
    write_json, session = seed_env
    write_json({"asignaturas": {"Lenguaje": {"1": [
        {"numero": 1, "enunciado": "Enunciado original.", "evidencias": ["Evidencia A.", "Evidencia B."]},
    ]}}})

    seed_dbas_module.seed_dbas()

    fila = session.query(DBA).filter_by(asignatura="Lenguaje", grado="1", numero=1).first()
    assert fila is not None
    assert fila.enunciado == "Enunciado original."
    assert fila.evidencias == ["Evidencia A.", "Evidencia B."]


def test_actualiza_dba_existente_si_el_contenido_cambio(seed_env):
    """El caso que motivó el upsert: una corrección en el JSON debe
    propagarse a una fila que ya estaba sembrada con datos viejos."""
    write_json, session = seed_env
    write_json({"asignaturas": {"Lenguaje": {"1": [
        {"numero": 1, "enunciado": "Enunciado truncad", "evidencias": ["m Evidencia trunca"]},
    ]}}})
    seed_dbas_module.seed_dbas()

    write_json({"asignaturas": {"Lenguaje": {"1": [
        {"numero": 1, "enunciado": "Enunciado completo y correcto.",
         "evidencias": ["Evidencia completa uno.", "Evidencia completa dos."]},
    ]}}})
    seed_dbas_module.seed_dbas()

    filas = session.query(DBA).filter_by(asignatura="Lenguaje", grado="1", numero=1).all()
    assert len(filas) == 1, "el upsert no debe duplicar la fila"
    assert filas[0].enunciado == "Enunciado completo y correcto."
    assert filas[0].evidencias == ["Evidencia completa uno.", "Evidencia completa dos."]


def test_segunda_corrida_sin_cambios_es_no_op(seed_env):
    write_json, session = seed_env
    write_json({"asignaturas": {"Lenguaje": {"1": [
        {"numero": 1, "enunciado": "Enunciado estable.", "evidencias": ["Evidencia estable."]},
    ]}}})
    seed_dbas_module.seed_dbas()
    fila_id = session.query(DBA).filter_by(asignatura="Lenguaje", grado="1", numero=1).first().id_dba

    seed_dbas_module.seed_dbas()

    filas = session.query(DBA).filter_by(asignatura="Lenguaje", grado="1", numero=1).all()
    assert len(filas) == 1
    assert filas[0].id_dba == fila_id


def test_no_borra_asignaturas_ausentes_del_json(seed_env):
    """El upsert nunca debe borrar filas de asignaturas que el JSON de
    turno no incluya — sólo inserta/actualiza lo que sí trae."""
    write_json, session = seed_env
    write_json({"asignaturas": {
        "Lenguaje": {"1": [{"numero": 1, "enunciado": "Lenguaje G1.", "evidencias": []}]},
        "Matemáticas": {"1": [{"numero": 1, "enunciado": "Mate G1.", "evidencias": []}]},
    }})
    seed_dbas_module.seed_dbas()

    write_json({"asignaturas": {
        "Lenguaje": {"1": [{"numero": 1, "enunciado": "Lenguaje G1 corregido.", "evidencias": []}]},
    }})
    seed_dbas_module.seed_dbas()

    mate = session.query(DBA).filter_by(asignatura="Matemáticas").first()
    assert mate is not None, "no debía borrarse sólo por no venir en el segundo JSON"
    assert mate.enunciado == "Mate G1."
