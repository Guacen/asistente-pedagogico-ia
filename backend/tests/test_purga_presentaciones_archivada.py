"""
Sprint F, Parte B2 — purga de datos personales sin FK ni finalidad
vigente: puntajes_estudiante y respuestas_presentacion guardan
`nombre_estudiante` como texto libre, sin ningún FK a `estudiantes`
(Presentaciones identifica participantes por nombre, no por cuenta).
Presentaciones está detrás de FEATURE_PRESENTACIONES=False desde un
sprint anterior — todo lo que hubiera en estas dos tablas al momento
de este sprint era dato de prueba de una función archivada, sin
finalidad vigente. Decisión explícita del owner: vaciarlas por
completo, UNA sola vez (no un borrado selectivo por coincidencia de
nombre, que sí tendría riesgo de falso positivo — acá no hay nada
legítimo que conservar en ese momento).

Es una migración de DATOS de una sola vez, registrada en
migraciones_aplicadas (ver MigracionAplicada en models.py) — NO un
DELETE incondicional en la ruta de arranque. La diferencia importa: en
cuanto Sprint 8 arregle la causa raíz (FK real o dejar de persistir el
nombre), estas tablas van a volver a tener filas LEGÍTIMAS de uso
real, y un DELETE que corriera en cada arranque las borraría sin que
nadie se diera cuenta. El test más importante de este archivo
(`test_purga_no_toca_datos_legitimos_de_una_corrida_posterior`) prueba
exactamente ese escenario.
"""
from __future__ import annotations


def _crear_engine_vacio():
    from sqlalchemy import create_engine
    from sqlalchemy.pool import StaticPool
    return create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)


def _sembrar_datos_de_prueba(Session, sesion_id=None):
    """Inserta una SesionPresentacion (si no se pasa una existente) +
    una fila en cada tabla objetivo. Devuelve el id_sesion usado, para
    poder insertar más filas sobre la misma sesión en llamadas
    posteriores del mismo test."""
    from models import (
        Docente, Grupo, Institucion, Presentacion, PuntajeEstudiante,
        RespuestaPresentacion, SesionPresentacion,
    )

    db = Session()
    if sesion_id is None:
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
        sesion_id = sesion.id_sesion

    db.add(RespuestaPresentacion(
        id_sesion=sesion_id, slide_index=0, nombre_estudiante="Estudiante Prueba",
        respuesta="a", es_correcta=True, puntos_obtenidos=100,
    ))
    db.add(PuntajeEstudiante(
        id_sesion=sesion_id, nombre_estudiante="Estudiante Prueba",
        puntaje_acumulado=100, aciertos=1, respuestas_totales=1,
    ))
    db.commit()
    db.close()
    return sesion_id


def test_purga_vacia_ambas_tablas_la_primera_vez(monkeypatch):
    import migrate
    from sqlalchemy.orm import sessionmaker
    from database import Base
    from models import PuntajeEstudiante, RespuestaPresentacion

    test_engine = _crear_engine_vacio()
    Base.metadata.create_all(bind=test_engine)
    Session = sessionmaker(bind=test_engine, autocommit=False, autoflush=False)
    _sembrar_datos_de_prueba(Session)

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


def test_purga_queda_registrada_en_migraciones_aplicadas(monkeypatch):
    import migrate
    from sqlalchemy.orm import sessionmaker
    from database import Base
    from models import MigracionAplicada

    test_engine = _crear_engine_vacio()
    Base.metadata.create_all(bind=test_engine)
    Session = sessionmaker(bind=test_engine, autocommit=False, autoflush=False)

    monkeypatch.setattr(migrate, "engine", test_engine)
    monkeypatch.setattr(migrate, "SessionLocal", Session)
    migrate.apply_migrations()

    db = Session()
    fila = db.query(MigracionAplicada).filter_by(
        nombre="sprint_f_b2_purga_presentaciones_archivada"
    ).first()
    db.close()
    assert fila is not None, "la purga debe dejar su marca en migraciones_aplicadas"
    test_engine.dispose()


def test_purga_no_toca_datos_legitimos_de_una_corrida_posterior(monkeypatch):
    """
    El escenario que este sprint existe para prevenir: una vez que la
    purga ya corrió (quedó registrada en migraciones_aplicadas), datos
    NUEVOS y legítimos en las mismas tablas (el caso real: Sprint 8
    arregla la causa raíz y Presentaciones vuelve a escribir ahí) NO
    deben desaparecer en el siguiente arranque. Si este test fallara,
    sería exactamente el incidente que el owner pidió prevenir: un
    DELETE corriendo de nuevo sin que nadie se diera cuenta.
    """
    import migrate
    from sqlalchemy.orm import sessionmaker
    from database import Base
    from models import PuntajeEstudiante, RespuestaPresentacion

    test_engine = _crear_engine_vacio()
    Base.metadata.create_all(bind=test_engine)
    Session = sessionmaker(bind=test_engine, autocommit=False, autoflush=False)
    sesion_id = _sembrar_datos_de_prueba(Session)

    monkeypatch.setattr(migrate, "engine", test_engine)
    monkeypatch.setattr(migrate, "SessionLocal", Session)

    # Primera corrida: purga los datos de prueba de este sprint.
    migrate.apply_migrations()
    db = Session()
    assert db.query(RespuestaPresentacion).count() == 0
    assert db.query(PuntajeEstudiante).count() == 0
    db.close()

    # Simula Sprint 8: Presentaciones vuelve a escribir datos reales.
    _sembrar_datos_de_prueba(Session, sesion_id=sesion_id)
    db = Session()
    assert db.query(RespuestaPresentacion).count() == 1
    assert db.query(PuntajeEstudiante).count() == 1
    db.close()

    # Segunda corrida (arranque normal siguiente) — la migración ya
    # está en el ledger, así que NO debe volver a ejecutar el DELETE.
    migrate.apply_migrations()
    assert migrate.MIGRATION_ERRORS == []

    db2 = Session()
    assert db2.query(RespuestaPresentacion).count() == 1, (
        "la purga volvió a correr y se comió datos legítimos posteriores"
    )
    assert db2.query(PuntajeEstudiante).count() == 1, (
        "la purga volvió a correr y se comió datos legítimos posteriores"
    )
    db2.close()
    test_engine.dispose()


def test_apply_migrations_es_idempotente_sobre_base_vacia(monkeypatch):
    """Correr apply_migrations() dos veces sobre una base sin datos de
    prueba (caso normal de reinicio del proceso) no debe fallar."""
    import migrate
    from sqlalchemy.orm import sessionmaker
    from database import Base

    test_engine = _crear_engine_vacio()
    Base.metadata.create_all(bind=test_engine)
    Session = sessionmaker(bind=test_engine, autocommit=False, autoflush=False)

    monkeypatch.setattr(migrate, "engine", test_engine)
    monkeypatch.setattr(migrate, "SessionLocal", Session)

    migrate.apply_migrations()
    assert migrate.MIGRATION_ERRORS == []

    migrate.apply_migrations()  # segunda corrida
    assert migrate.MIGRATION_ERRORS == []

    test_engine.dispose()
