"""
Sprint migraciones-aisladas — post-incidente (una columna con tipo
inválido en Postgres, `sesiones_presentacion.slide_abierto_en DATETIME`,
tumbó el arranque COMPLETO de la app, de una función que ni siquiera
está activa).

Cubre:
- _paso() aísla una excepción: la registra en MIGRATION_ERRORS y NUNCA
  la relanza.
- apply_migrations() limpia MIGRATION_ERRORS al empezar cada corrida.
- Un paso roto NO impide que los pasos siguientes (independientes)
  corran — probado forzando la falla de un paso temprano
  (calificaciones.id_columna) y confirmando que el backfill de
  instituciones (uno de los últimos pasos) corrió igual.
- GET /health y GET /api/version exponen `migraciones_fallidas` cuando
  hay algo que reportar, sin dejar de responder 200/healthy — el punto
  entero de aislar migraciones es que el sitio se mantenga arriba.
"""
from __future__ import annotations

import pytest


# ═══════════════════════════════════════════════════════════════
# _paso() — la unidad de aislamiento
# ═══════════════════════════════════════════════════════════════

@pytest.fixture(autouse=True)
def _migration_errors_limpio():
    """MIGRATION_ERRORS es una lista módulo-nivel compartida por todo el
    proceso — sin este fixture, un test que la ensucia contaminaría los
    siguientes (conftest documenta que los tests normales NO corren
    apply_migrations(), así que nada más la limpia entre tests)."""
    import migrate
    snapshot = list(migrate.MIGRATION_ERRORS)
    migrate.MIGRATION_ERRORS.clear()
    yield
    migrate.MIGRATION_ERRORS.clear()
    migrate.MIGRATION_ERRORS.extend(snapshot)


def test_paso_registra_la_falla_sin_relanzarla():
    import migrate

    def _falla():
        raise ValueError("boom")

    migrate._paso("paso-de-prueba", _falla)  # no debe lanzar

    assert migrate.MIGRATION_ERRORS == [{"paso": "paso-de-prueba", "error": "boom"}]


def test_paso_no_registra_nada_si_no_falla():
    import migrate

    migrate._paso("paso-ok", lambda: None)

    assert migrate.MIGRATION_ERRORS == []


def test_paso_captura_cualquier_tipo_de_excepcion():
    import migrate

    def _falla_feo():
        raise RuntimeError("algo raro")

    migrate._paso("otro-paso", _falla_feo)  # si relanzara, el test fallaría acá

    assert len(migrate.MIGRATION_ERRORS) == 1
    assert migrate.MIGRATION_ERRORS[0]["error"] == "algo raro"


# ═══════════════════════════════════════════════════════════════
# apply_migrations() — aislamiento real, de punta a punta
# ═══════════════════════════════════════════════════════════════

def test_apply_migrations_limpia_migration_errors_al_empezar(monkeypatch):
    import migrate

    migrate.MIGRATION_ERRORS.append({"paso": "de-una-corrida-anterior", "error": "x"})

    # DB ya migrada (test_engine trae el esquema actual completo vía
    # create_all) — todos los pasos deberían ser no-ops idempotentes.
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from database import Base

    test_engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=test_engine)

    monkeypatch.setattr(migrate, "engine", test_engine)
    monkeypatch.setattr(migrate, "SessionLocal", sessionmaker(bind=test_engine, autocommit=False, autoflush=False))
    migrate.apply_migrations()
    test_engine.dispose()

    assert {"paso": "de-una-corrida-anterior", "error": "x"} not in migrate.MIGRATION_ERRORS


def test_un_paso_roto_no_impide_que_los_demas_corran(monkeypatch):
    """El caso real del incidente, simulado: un paso TEMPRANO
    (calificaciones.id_columna) se rompe — un paso MUCHO más adelante e
    independiente (backfill de instituciones, casi el último de la
    función) debe correr igual, y apply_migrations() no debe lanzar."""
    import migrate
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from database import Base
    from models import Docente

    test_engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=test_engine)
    TestSessionLocal = sessionmaker(bind=test_engine, autocommit=False, autoflush=False)

    # Un docente sin id_institucion — es lo que _backfill_instituciones_unipersonales
    # debe encontrar y arreglar si de verdad corrió.
    db = TestSessionLocal()
    docente = Docente(nombre_completo="Ana Prueba", email="ana-migraciones@test.com", password_hash="x")
    db.add(docente)
    db.commit()
    db.refresh(docente)
    docente_id = docente.id_docente
    db.close()

    monkeypatch.setattr(migrate, "engine", test_engine)
    monkeypatch.setattr(migrate, "SessionLocal", TestSessionLocal)

    original_tiene_columna = migrate._tiene_columna

    def _tiene_columna_rota(tabla, columna):
        if (tabla, columna) == ("calificaciones", "id_columna"):
            raise RuntimeError("columna simulada rota — como el incidente real")
        return original_tiene_columna(tabla, columna)

    monkeypatch.setattr(migrate, "_tiene_columna", _tiene_columna_rota)

    migrate.apply_migrations()  # NO debe lanzar

    fallos = {e["paso"] for e in migrate.MIGRATION_ERRORS}
    assert "calificaciones.id_columna" in fallos, migrate.MIGRATION_ERRORS

    db2 = TestSessionLocal()
    try:
        docente_actualizado = db2.query(Docente).filter(Docente.id_docente == docente_id).first()
        assert docente_actualizado.id_institucion is not None, (
            "el backfill de instituciones (paso posterior e independiente) "
            "no debería haberse visto afectado por la falla simulada"
        )
    finally:
        db2.close()
        test_engine.dispose()


# ═══════════════════════════════════════════════════════════════
# GET /health y GET /api/version — visibilidad sin entrar a logs
# ═══════════════════════════════════════════════════════════════

def test_health_sigue_200_healthy_aunque_haya_fallos_registrados(client_no_auth):
    """El punto entero del aislamiento: un fallo de migración NUNCA debe
    volver el healthcheck no-200 — eso reintroduciría el mismo outage
    que este sprint existe para evitar."""
    import migrate
    migrate.MIGRATION_ERRORS.append({"paso": "prueba", "error": "boom"})

    r = client_no_auth.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "healthy"
    assert r.json()["migraciones_fallidas"] == [{"paso": "prueba", "error": "boom"}]


def test_health_no_incluye_la_clave_si_no_hay_fallos(client_no_auth):
    r = client_no_auth.get("/health")
    assert "migraciones_fallidas" not in r.json()


def test_version_expone_migraciones_fallidas_si_las_hay(client_no_auth):
    import migrate
    migrate.MIGRATION_ERRORS.append({"paso": "prueba", "error": "boom"})

    r = client_no_auth.get("/api/version")
    assert r.status_code == 200
    assert r.json()["migraciones_fallidas"] == [{"paso": "prueba", "error": "boom"}]


def test_version_no_incluye_la_clave_si_no_hay_fallos(client_no_auth):
    r = client_no_auth.get("/api/version")
    assert "migraciones_fallidas" not in r.json()
