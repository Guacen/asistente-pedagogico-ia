"""
Sprint migraciones-aisladas — corre TODAS las migraciones de migrate.py
contra un PostgreSQL real y limpio. Éste es exactamente el chequeo que
habría detectado el incidente antes del merge: el resto de la suite
(568 tests en el momento del incidente) pasaba en verde porque corre
sobre SQLite, que acepta cualquier nombre de tipo por afinidad de
columna — `ADD COLUMN slide_abierto_en DATETIME` nunca falla ahí, sólo
en Postgres real (`type "datetime" does not exist`).

Sólo corre si TEST_DATABASE_URL_POSTGRES está seteada — la trae el job
de CI (ver .github/workflows/tests.yml, servicio `postgres`). Se
saltea en local si no hay Postgres disponible (mismo criterio que el
resto de este sprint: nunca asumir que un desarrollador tiene Postgres
instalado a mano).

Estrategia para forzar que las migraciones corran DE VERDAD, no como
no-ops: create_tables() ya crea el esquema completo y ACTUAL (incluye
columnas que en producción real sólo existen porque migrate.py las
agregó alguna vez, pero que el modelo ORM de hoy ya declara desde el
arranque) — así que correr apply_migrations() sobre una DB recién
creada por create_tables() haría que CADA "if columna no existe: ALTER
TABLE" se salte, porque la columna YA está. Para exercitar el ALTER
TABLE real (que es exactamente donde vivía el bug), se le hace DROP a
cada columna que migrate.py agrega manualmente, simulando el esquema
"viejo" que sí existe en producción — y ENTONCES se corre
apply_migrations() sin modificar nada de su código real.
"""
from __future__ import annotations

import os

import pytest

TEST_DATABASE_URL_POSTGRES = os.environ.get("TEST_DATABASE_URL_POSTGRES")

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL_POSTGRES,
    reason=(
        "TEST_DATABASE_URL_POSTGRES no está seteada — este test sólo corre "
        "con un Postgres real disponible (ver servicio 'postgres' en "
        ".github/workflows/tests.yml). Se saltea en local."
    ),
)

# Cada columna que migrate.py agrega vía ALTER TABLE crudo (no las que
# sólo crean tablas nuevas por completo, ésas ya las prueba create_all
# normalmente). Si se agrega una migración nueva de este tipo, sumarla
# acá — si no, este test deja de exercitarla de verdad.
COLUMNAS_MIGRADAS_MANUALMENTE = [
    ("calificaciones", "id_columna"),
    ("mensajes", "modo"),
    ("mensajes", "id_estudiante"),
    ("docentes", "id_institucion"),
    ("docentes", "rol"),
    ("docentes", "es_admin"),
    ("mensajes", "id_sesion"),
    ("docentes", "email_verificado"),
    ("docentes", "fecha_verificacion"),
    ("docentes", "consentimiento_datos"),
    ("docentes", "fecha_consentimiento"),
    ("docentes", "ip_consentimiento"),
    ("docentes", "plan"),
    ("docentes", "trial_ends_at"),
    ("presentaciones", "estado"),
    ("presentaciones", "error_generacion"),
    ("presentaciones", "modo_puntaje"),
    ("presentaciones", "tiempo_pregunta_s"),
    ("presentaciones", "factor_tiempo_piar"),
    ("respuestas_presentacion", "tiempo_limite_ms"),
    ("respuestas_presentacion", "puntos_obtenidos"),
    ("presentaciones", "secciones"),
    ("sesiones_presentacion", "slide_abierto_en"),
]


@pytest.fixture
def postgres_engine():
    """Postgres real, esquema público reseteado — cada test de este
    archivo arranca desde cero, sin importar qué corrió antes en el
    mismo servicio de CI."""
    from sqlalchemy import create_engine, text as sa_text

    engine = create_engine(TEST_DATABASE_URL_POSTGRES)
    with engine.connect() as conn:
        conn.execute(sa_text("DROP SCHEMA public CASCADE"))
        conn.execute(sa_text("CREATE SCHEMA public"))
        conn.commit()
    yield engine
    engine.dispose()


def _preparar_esquema_viejo(postgres_engine):
    """create_tables() con el esquema ACTUAL, luego DROP de cada
    columna que migrate.py agrega manualmente — simula la DB "vieja"
    contra la que de verdad corren esas migraciones en producción."""
    from sqlalchemy import text as sa_text
    from database import Base

    Base.metadata.create_all(bind=postgres_engine)
    with postgres_engine.connect() as conn:
        for tabla, columna in COLUMNAS_MIGRADAS_MANUALMENTE:
            conn.execute(sa_text(f'ALTER TABLE {tabla} DROP COLUMN "{columna}"'))
        conn.commit()


def test_apply_migrations_corre_limpio_contra_postgres_desde_esquema_viejo(postgres_engine, monkeypatch):
    """El test que habría atrapado el incidente: TODAS las columnas que
    migrate.py agrega manualmente se sacan primero, para forzar que cada
    ALTER TABLE corra DE VERDAD contra Postgres — no como no-op."""
    import migrate
    from sqlalchemy import inspect
    from sqlalchemy.orm import sessionmaker

    _preparar_esquema_viejo(postgres_engine)

    monkeypatch.setattr(migrate, "engine", postgres_engine)
    monkeypatch.setattr(
        migrate, "SessionLocal",
        sessionmaker(bind=postgres_engine, autocommit=False, autoflush=False),
    )

    migrate.apply_migrations()  # no debe lanzar

    assert migrate.MIGRATION_ERRORS == [], (
        "apply_migrations() dejó errores corriendo contra Postgres real — "
        "esto es EXACTAMENTE lo que este test existe para atrapar antes "
        "del merge:\n" + "\n".join(f"  {e['paso']}: {e['error']}" for e in migrate.MIGRATION_ERRORS)
    )

    inspector = inspect(postgres_engine)
    for tabla, columna in COLUMNAS_MIGRADAS_MANUALMENTE:
        cols = [c["name"] for c in inspector.get_columns(tabla)]
        assert columna in cols, f"'{columna}' no quedó en '{tabla}' tras apply_migrations()"


def test_apply_migrations_es_idempotente_en_postgres(postgres_engine, monkeypatch):
    """Correrla dos veces seguidas (esquema ya al día la segunda vez)
    tampoco debe fallar ni dejar errores — es lo que pasa en cada
    restart normal del contenedor en Railway."""
    import migrate
    from sqlalchemy.orm import sessionmaker

    _preparar_esquema_viejo(postgres_engine)

    monkeypatch.setattr(migrate, "engine", postgres_engine)
    monkeypatch.setattr(
        migrate, "SessionLocal",
        sessionmaker(bind=postgres_engine, autocommit=False, autoflush=False),
    )

    migrate.apply_migrations()
    assert migrate.MIGRATION_ERRORS == []

    migrate.apply_migrations()  # segunda corrida — todo ya existe
    assert migrate.MIGRATION_ERRORS == []
