"""
SPRINT 7 — migración de `secciones` (multi-tema por secciones).

VERIFICACIÓN OBLIGATORIA #2: las presentaciones que ya existían ANTES
de este sprint (sin la columna `secciones`) quedan, tras migrar, como
una sección única que cubre todo su `diapositivas` actual — y siguen
funcionando exactamente igual (sesión en vivo, puntaje, etc.), sin
haber tocado un solo índice de `diapositivas` (eso rompería
slide_index ya guardado en respuestas/sesiones existentes).

Dos niveles de prueba:
1. La MECÁNICA de la migración en sí — se simula una tabla
   "presentaciones" tal como estaba antes de este sprint (sin la
   columna), se le agrega la columna y se corre el backfill real de
   migrate.py, verificado contra el modelo ORM real.
2. Que una presentación YA MIGRADA (una sola sección sintética, sin
   separadora) sigue funcionando end-to-end con toda la lógica de
   sesión en vivo — iniciar/responder/podio — sin ningún cambio.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


# ═══════════════════════════════════════════════════════════════
# 1. Mecánica de la migración — ALTER TABLE + backfill reales
# ═══════════════════════════════════════════════════════════════

def test_backfill_secciones_migra_presentaciones_existentes(monkeypatch):
    """Simula el esquema de 'presentaciones' tal como estaba ANTES de
    este sprint (sin la columna 'secciones') con una fila ya generada,
    corre exactamente el ALTER TABLE + backfill que aplica migrate.py,
    y verifica el resultado leyendo con el modelo ORM real."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE presentaciones (
                id_presentacion VARCHAR(36) PRIMARY KEY,
                id_docente VARCHAR(36) NOT NULL,
                id_grupo VARCHAR(36) NOT NULL,
                titulo VARCHAR(200) NOT NULL,
                tema VARCHAR(500) NOT NULL,
                diapositivas JSON NOT NULL,
                estado VARCHAR(20) NOT NULL DEFAULT 'lista',
                error_generacion TEXT,
                modo_puntaje VARCHAR(20) NOT NULL DEFAULT 'competencia',
                tiempo_pregunta_s INTEGER NOT NULL DEFAULT 20,
                factor_tiempo_piar FLOAT NOT NULL DEFAULT 1.5,
                creado_en DATETIME NOT NULL
            )
        """))
        conn.commit()
        conn.execute(text("""
            INSERT INTO presentaciones (
                id_presentacion, id_docente, id_grupo, titulo, tema, diapositivas,
                estado, error_generacion, creado_en
            ) VALUES (
                'p1', 'd1', 'g1', 'Fracciones', 'Fracciones equivalentes',
                :diapositivas, 'lista', NULL, '2026-01-01 00:00:00'
            )
        """), {
            "diapositivas": json.dumps([
                {"tipo": "contenido", "titulo": "A", "cuerpo": "x", "notas_docente": "x"},
                {"tipo": "multiple", "pregunta": "¿1?", "opciones": ["a", "b"], "correcta": 0, "tiempo_s": 20, "puntos": 100},
                {"tipo": "contenido", "titulo": "B", "cuerpo": "x", "notas_docente": "x"},
            ]),
        })
        conn.commit()

    # Exactamente lo que hace apply_migrations(): agrega la columna
    # (nullable, sin default — así queda para las filas ya existentes)
    # y corre el backfill.
    with engine.connect() as conn:
        conn.execute(text("ALTER TABLE presentaciones ADD COLUMN secciones JSON"))
        conn.commit()

    import migrate as migrate_module
    TestSessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    monkeypatch.setattr(migrate_module, "SessionLocal", TestSessionLocal)
    migrate_module._backfill_secciones_presentaciones_existentes()

    from models import Presentacion
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        p = db.query(Presentacion).filter(Presentacion.id_presentacion == "p1").first()
        assert p is not None
        # diapositivas NUNCA se tocó — ni un índice corrido.
        assert len(p.diapositivas) == 3
        assert p.diapositivas[0]["tipo"] == "contenido"
        assert p.diapositivas[0]["titulo"] == "A"

        # secciones quedó backfillado como UNA sección sintética que
        # cubre todo el array, derivada de lo que ya había guardado.
        assert p.secciones == [{
            "tema": "Fracciones equivalentes",
            "n_slides_contenido": 2,
            "n_preguntas": 1,
            "inicio": 0,
            "fin": 2,
            "estado": "lista",
            "error_generacion": None,
        }]
    finally:
        db.close()


def test_backfill_secciones_es_idempotente(monkeypatch):
    """Correr el backfill dos veces no debe duplicar ni pisar nada —
    una vez poblado, IS NULL ya no matchea esa fila."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE presentaciones (
                id_presentacion VARCHAR(36) PRIMARY KEY, id_docente VARCHAR(36) NOT NULL,
                id_grupo VARCHAR(36) NOT NULL, titulo VARCHAR(200) NOT NULL, tema VARCHAR(500) NOT NULL,
                diapositivas JSON NOT NULL, secciones JSON, estado VARCHAR(20) NOT NULL DEFAULT 'lista',
                error_generacion TEXT, modo_puntaje VARCHAR(20) NOT NULL DEFAULT 'competencia',
                tiempo_pregunta_s INTEGER NOT NULL DEFAULT 20, factor_tiempo_piar FLOAT NOT NULL DEFAULT 1.5,
                creado_en DATETIME NOT NULL
            )
        """))
        conn.commit()
        conn.execute(text("""
            INSERT INTO presentaciones (id_presentacion, id_docente, id_grupo, titulo, tema, diapositivas, creado_en)
            VALUES ('p1', 'd1', 'g1', 'T', 'T', :diapositivas, '2026-01-01 00:00:00')
        """), {"diapositivas": json.dumps([{"tipo": "contenido", "titulo": "A", "cuerpo": "x", "notas_docente": "x"}])})
        conn.commit()

    import migrate as migrate_module
    TestSessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    monkeypatch.setattr(migrate_module, "SessionLocal", TestSessionLocal)

    migrate_module._backfill_secciones_presentaciones_existentes()
    migrate_module._backfill_secciones_presentaciones_existentes()  # segunda corrida — no debe romper ni duplicar

    from models import Presentacion
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        p = db.query(Presentacion).filter(Presentacion.id_presentacion == "p1").first()
        assert len(p.secciones) == 1
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════
# 2. Una presentación YA MIGRADA sigue funcionando end-to-end
# ═══════════════════════════════════════════════════════════════

def test_presentacion_migrada_sin_separadora_sigue_funcionando(db_session, seed_docente):
    """Una presentación 'vieja' migrada (una sola sección sintética,
    SIN diapositiva separadora — ese concepto no existía antes de este
    sprint) sigue funcionando con toda la lógica de sesión en vivo:
    iniciar slide, registrar respuesta, calcular podio."""
    from models import Presentacion, SesionPresentacion
    from presentaciones import iniciar_slide, registrar_respuesta, calcular_podio, calcular_resultado

    docente = seed_docente["docente"]
    grupo = seed_docente["grupo"]

    # Shape típico de backfill: diapositivas EXACTAMENTE como antes
    # (índice 0 = contenido, sin separadora), secciones sintetizada.
    diapositivas = [
        {"tipo": "contenido", "titulo": "A", "cuerpo": "x", "notas_docente": "x"},
        {"tipo": "multiple", "pregunta": "¿1?", "opciones": ["a", "b"], "correcta": 0, "tiempo_s": 20, "puntos": 100},
    ]
    presentacion = Presentacion(
        id_docente=docente.id_docente, id_grupo=grupo.id_grupo,
        titulo="Vieja", tema="Vieja", diapositivas=diapositivas,
        secciones=[{
            "tema": "Vieja", "n_slides_contenido": 1, "n_preguntas": 1,
            "inicio": 0, "fin": 1, "estado": "lista", "error_generacion": None,
        }],
        estado="lista",
    )
    db_session.add(presentacion)
    db_session.commit()
    db_session.refresh(presentacion)
    sesion = SesionPresentacion(id_presentacion=presentacion.id_presentacion, codigo="OLD001")
    db_session.add(sesion)
    db_session.commit()
    db_session.refresh(sesion)

    iniciar_slide(db_session, sesion, 1)
    respuesta = registrar_respuesta(db_session, sesion, presentacion, 1, "Ana", "0", 1000)
    assert respuesta is not None
    assert respuesta.es_correcta is True

    resultado = calcular_resultado(db_session, sesion, presentacion)
    assert resultado["correcta"] == 0

    podio = calcular_podio(db_session, sesion, presentacion)
    assert podio["ranking"][0]["nombre"] == "Ana"
    assert podio["ranking"][0]["puntaje_acumulado"] > 0


def test_presentacion_migrada_expone_secciones_en_get(client, db_session, seed_docente):
    """GET /{id} de una presentación migrada trae la sección sintética
    (el frontend la puede seguir renderizando igual que cualquier otra)."""
    from models import Presentacion

    docente = seed_docente["docente"]
    grupo = seed_docente["grupo"]
    presentacion = Presentacion(
        id_docente=docente.id_docente, id_grupo=grupo.id_grupo,
        titulo="Vieja", tema="Vieja",
        diapositivas=[{"tipo": "contenido", "titulo": "A", "cuerpo": "x", "notas_docente": "x"}],
        secciones=[{
            "tema": "Vieja", "n_slides_contenido": 1, "n_preguntas": 0,
            "inicio": 0, "fin": 0, "estado": "lista", "error_generacion": None,
        }],
        estado="lista",
    )
    db_session.add(presentacion)
    db_session.commit()
    db_session.refresh(presentacion)

    r = client.get(f"/api/presentaciones/{presentacion.id_presentacion}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["secciones"]) == 1
    assert body["secciones"][0]["tema"] == "Vieja"
