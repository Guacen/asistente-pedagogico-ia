"""
Hotfix P0 — producción caída con 502 tras el deploy de PR#87/#88:
migrate.py:328 tenía `ADD COLUMN slide_abierto_en DATETIME`. DATETIME es
sintaxis SQLite/MySQL — PostgreSQL no tiene ese tipo
(psycopg2.errors.UndefinedObject: type "datetime" does not exist).
apply_migrations() corre en el arranque, así que la app ni siquiera
levantaba en Railway (Postgres), aunque toda la suite (SQLite) pasaba
en verde — SQLite acepta cualquier nombre de tipo (afinidad de columna),
por eso esto nunca se detectó localmente ni en CI.

Guarda de regresión: ningún ALTER TABLE / CREATE TABLE crudo en
migrate.py debe usar un tipo que no exista en PostgreSQL. No ejecuta
contra un Postgres real (no hay uno disponible en este entorno) — es un
chequeo estático del código fuente, mismo nivel de garantía que ya usa
test_security_headers.py/test_xss_host_header.py para archivos que no
se pueden probar de punta a punta acá.
"""
from __future__ import annotations

import re
from pathlib import Path

MIGRATE_PY = Path(__file__).resolve().parent.parent / "migrate.py"

# Tipos SQLite/MySQL que NO existen en PostgreSQL y que son fáciles de
# colar sin darse cuenta (todos compilan silenciosamente en SQLite, que
# acepta cualquier nombre de tipo). Si algún día hace falta un tipo
# nuevo legítimo, agregarlo a esta lista con su equivalente correcto en
# vez de aflojar el test.
TIPOS_INVALIDOS_EN_POSTGRES = (
    "DATETIME",     # usar TIMESTAMP
    "AUTOINCREMENT",  # usar SERIAL / IDENTITY (o dejarlo al ORM)
    "TINYINT",      # usar SMALLINT
    "MEDIUMINT",    # usar INTEGER
    "MEDIUMTEXT",   # usar TEXT
    "LONGTEXT",     # usar TEXT
    "UNSIGNED",     # no existe en Postgres
    "ENUM(",        # crear un tipo ENUM real o usar VARCHAR + CHECK
)


def _ddl_crudo() -> list[str]:
    """Todas las líneas de migrate.py con ALTER TABLE o CREATE TABLE
    crudo (SQL de texto, no DDL generado por el ORM vía Base.metadata)."""
    texto = MIGRATE_PY.read_text(encoding="utf-8")
    return [
        linea for linea in texto.splitlines()
        if "ALTER TABLE" in linea or re.search(r"\bCREATE TABLE\b", linea)
    ]


def test_migrate_py_existe_y_tiene_ddl_crudo():
    """Sanity check: si este test empieza a fallar porque la lista viene
    vacía, es que migrate.py cambió de forma — revisar el regex de arriba,
    no borrar este test."""
    assert MIGRATE_PY.exists()
    assert len(_ddl_crudo()) > 10


def test_ningun_ddl_crudo_usa_tipos_invalidos_en_postgres():
    lineas = _ddl_crudo()
    fallos = []
    for linea in lineas:
        mayus = linea.upper()
        for tipo in TIPOS_INVALIDOS_EN_POSTGRES:
            if tipo in mayus:
                fallos.append(f"{tipo!r} en: {linea.strip()!r}")
    assert not fallos, (
        "migrate.py tiene DDL crudo con tipos que no existen en PostgreSQL "
        "(rompe el arranque en producción, aunque la suite en SQLite pase):\n"
        + "\n".join(fallos)
    )


def test_slide_abierto_en_usa_timestamp_no_datetime():
    """Regresión puntual del incidente: la columna específica que causó
    el 502 en producción."""
    texto = MIGRATE_PY.read_text(encoding="utf-8")
    assert "slide_abierto_en TIMESTAMP" in texto
    assert "slide_abierto_en DATETIME" not in texto
