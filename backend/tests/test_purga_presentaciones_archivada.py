"""
Sprint F, Parte B2 — purga de datos personales sin FK ni finalidad
vigente: puntajes_estudiante y respuestas_presentacion guardan
`nombre_estudiante` como texto libre, sin ningún FK a `estudiantes`
(Presentaciones identifica participantes por nombre, no por cuenta).
Presentaciones está detrás de FEATURE_PRESENTACIONES=False desde un
sprint anterior — todo lo que hubiera en estas dos tablas es dato de
prueba de una función archivada, sin finalidad vigente. Decisión
explícita del owner: vaciarlas por completo (no un borrado selectivo
por coincidencia de nombre, que sí tendría riesgo de falso positivo).

migrate.py corre este DELETE sin condición en cada arranque — una vez
vacías, es un no-op (DELETE sobre 0 filas), mismo patrón de
idempotencia que el resto de _paso() en este archivo.
"""
from __future__ import annotations


def _preparar_schema_con_datos(test_engine):
    from sqlalchemy.orm import sessionmaker
    from database import Base
    from models import (
        Docente, Grupo, Institucion, Presentacion, PuntajeEstudiante,
        RespuestaPresentacion, SesionPresentacion,
    )

    Base.metadata.create_all(bind=test_engine)
    Session = sessionmaker(bind=test_engine, autocommit=False, autoflush=False)
    db = Session()

    inst = Institucion(nombre="Institución de prueba", plan="free")
    db.add(inst)
    db.flush()

    docente = Docente(
        nombre_completo="Docente Prueba", email="purga@test.com",
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

    presentacion = Presentacion(
        id_docente=docente.id_docente, id_grupo=grupo.id_grupo,
        titulo="Presentación de prueba", tema="Prueba",
    )
    db.add(presentacion)
    db.flush()

    sesion = SesionPresentacion(id_presentacion=presentacion.id_presentacion, codigo="ABC123")
    db.add(sesion)
    db.flush()

    db.add(RespuestaPresentacion(
        id_sesion=sesion.id_sesion, slide_index=0, nombre_estudiante="Estudiante Prueba",
        respuesta="a", es_correcta=True, puntos_obtenidos=100,
    ))
    db.add(PuntajeEstudiante(
        id_sesion=sesion.id_sesion, nombre_estudiante="Estudiante Prueba",
        puntaje_acumulado=100, aciertos=1, respuestas_totales=1,
    ))
    db.commit()
    db.close()
    return Session


def test_purga_vacia_ambas_tablas(monkeypatch):
    import migrate
    from sqlalchemy import create_engine
    from sqlalchemy.pool import StaticPool
    from models import PuntajeEstudiante, RespuestaPresentacion

    test_engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Session = _preparar_schema_con_datos(test_engine)

    db = Session()
    assert db.query(RespuestaPresentacion).count() == 1
    assert db.query(PuntajeEstudiante).count() == 1
    db.close()

    monkeypatch.setattr(migrate, "engine", test_engine)
    monkeypatch.setattr(migrate, "SessionLocal", Session)
    migrate.apply_migrations()

    assert migrate.MIGRATION_ERRORS == [], migrate.MIGRATION_ERRORS

    db2 = Session()
    assert db2.query(RespuestaPresentacion).count() == 0
    assert db2.query(PuntajeEstudiante).count() == 0
    db2.close()
    test_engine.dispose()


def test_purga_es_idempotente_sobre_tablas_ya_vacias(monkeypatch):
    """Correrla de nuevo (arranque normal, ya purgado antes) no debe
    fallar ni volver a reportar nada — es exactamente el mismo criterio
    de idempotencia que el resto de _paso() en migrate.py."""
    import migrate
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from database import Base

    test_engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=test_engine)
    Session = sessionmaker(bind=test_engine, autocommit=False, autoflush=False)

    monkeypatch.setattr(migrate, "engine", test_engine)
    monkeypatch.setattr(migrate, "SessionLocal", Session)

    migrate.apply_migrations()
    assert migrate.MIGRATION_ERRORS == []

    migrate.apply_migrations()  # segunda corrida, tablas ya vacías
    assert migrate.MIGRATION_ERRORS == []

    test_engine.dispose()
