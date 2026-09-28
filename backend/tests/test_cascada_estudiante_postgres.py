"""
Sprint F, Parte B2 — el borrado en cascada de un Estudiante (piar,
observaciones, mensajes, chat_sesiones) se agregó como cascade="all,
delete" de SQLAlchemy en models.py. Ese mecanismo es a nivel de ORM
(emite DELETEs explícitos en el orden correcto antes del DELETE del
padre), así que en teoría funciona igual en cualquier motor — pero el
bug que este sprint corrigió (FKs sin `ondelete` ni cascada, huérfanos
o ForeignKeyViolation) NUNCA se vio en la suite normal porque corre
contra SQLite, que no valida FKs por default (ver database.py — no hay
PRAGMA foreign_keys=ON). Este test prueba el escenario real contra
Postgres, con constraints de verdad, para no repetir ese punto ciego.

Sólo corre si TEST_DATABASE_URL_POSTGRES está seteada (mismo criterio
que test_migraciones_postgres.py) — se saltea en local sin Postgres.
"""
from __future__ import annotations

import os

import pytest

TEST_DATABASE_URL_POSTGRES = os.environ.get("TEST_DATABASE_URL_POSTGRES")

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL_POSTGRES,
    reason=(
        "TEST_DATABASE_URL_POSTGRES no está seteada — este test sólo corre "
        "con un Postgres real disponible. Se saltea en local."
    ),
)


@pytest.fixture
def postgres_session():
    from sqlalchemy import create_engine, text as sa_text
    from sqlalchemy.orm import sessionmaker
    from database import Base

    engine = create_engine(TEST_DATABASE_URL_POSTGRES)
    with engine.connect() as conn:
        conn.execute(sa_text("DROP SCHEMA public CASCADE"))
        conn.execute(sa_text("CREATE SCHEMA public"))
        conn.commit()
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = Session()
    yield session
    session.close()
    engine.dispose()


def test_borrar_estudiante_con_historial_no_deja_huerfanos_en_postgres(postgres_session):
    from models import (
        PIAR, ChatSesion, Docente, Estudiante, Grupo, Institucion, Mensaje, Observacion,
    )

    db = postgres_session

    inst = Institucion(nombre="Institución de prueba", plan="free")
    db.add(inst)
    db.flush()

    docente = Docente(
        nombre_completo="Docente Prueba", email="prueba@test.com",
        password_hash="x", id_institucion=inst.id_institucion,
    )
    db.add(docente)
    db.flush()

    grupo = Grupo(
        id_docente=docente.id_docente, nombre_grupo="Grupo Prueba", grado="6",
        asignatura="Matematicas", anio_lectivo=2026, cantidad_estudiantes=1,
    )
    db.add(grupo)
    db.flush()

    est = Estudiante(id_grupo=grupo.id_grupo, codigo_estudiante="Estudiante Prueba", tiene_piar=True)
    db.add(est)
    db.flush()

    sesion = ChatSesion(
        id_grupo=grupo.id_grupo, id_docente=docente.id_docente, modo="piar",
        id_estudiante=est.id_estudiante,
    )
    db.add(sesion)
    db.flush()

    db.add(Mensaje(
        id_grupo=grupo.id_grupo, remitente="docente", contenido="hola", modo="piar",
        id_estudiante=est.id_estudiante, id_sesion=sesion.id_sesion,
    ))
    db.add(PIAR(
        id_estudiante=est.id_estudiante, id_grupo=grupo.id_grupo, id_docente=docente.id_docente,
        periodo=1, anio=2026, version=1, contenido={},
    ))
    db.add(Observacion(
        id_estudiante=est.id_estudiante, id_docente=docente.id_docente, id_grupo=grupo.id_grupo,
        tipo="academica", situacion_descrita="algo pasó",
    ))
    db.commit()

    eid = est.id_estudiante

    # Antes de la corrección de Parte B2, esto lanzaba
    # sqlalchemy.exc.IntegrityError (ForeignKeyViolation) contra Postgres
    # real — nunca un borrado silencioso con huérfanos, un error duro.
    db.delete(est)
    db.commit()

    assert db.query(Estudiante).filter_by(id_estudiante=eid).first() is None
    assert db.query(ChatSesion).filter_by(id_estudiante=eid).first() is None
    assert db.query(Mensaje).filter_by(id_estudiante=eid).first() is None
    assert db.query(PIAR).filter_by(id_estudiante=eid).first() is None
    assert db.query(Observacion).filter_by(id_estudiante=eid).first() is None
