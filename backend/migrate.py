"""
migrate.py — Migraciones de base de datos y seed de datos iniciales.

Se llama desde main.py en el evento startup, justo después de create_tables().
- apply_migrations(): agrega columnas nuevas a tablas existentes (idempotente).
- seed_pro_user(): sube a Plan Pro al usuario de prueba.
"""

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from database import Base, engine, SessionLocal
from models import Suscripcion


# ============================================================
# MIGRACIONES DE ESQUEMA
# ============================================================

def apply_migrations():
    """
    Aplica cambios al esquema que create_all() no puede hacer
    (p.ej. agregar columnas a tablas ya existentes).
    """
    inspector = inspect(engine)
    with engine.connect() as conn:

        # ── calificaciones.id_columna ──────────────────────────────────
        cols_cal = [c["name"] for c in inspector.get_columns("calificaciones")]
        if "id_columna" not in cols_cal:
            conn.execute(text(
                "ALTER TABLE calificaciones ADD COLUMN id_columna VARCHAR(36) REFERENCES evaluacion_columnas(id_columna)"
            ))
            conn.commit()
            print("✅ Migración: columna 'id_columna' agregada a 'calificaciones'")

        # ── mensajes.modo ──────────────────────────────────────────────
        # Fase B chat multi-modo — mensajes previos quedan como 'planeacion'
        # (era el único modo hasta este sprint).
        cols_msg = [c["name"] for c in inspector.get_columns("mensajes")]
        if "modo" not in cols_msg:
            conn.execute(text(
                "ALTER TABLE mensajes ADD COLUMN modo VARCHAR(32) NOT NULL DEFAULT 'planeacion'"
            ))
            conn.commit()
            print("✅ Migración: columna 'modo' agregada a 'mensajes' (default planeacion)")

        # ── mensajes.id_estudiante ────────────────────────────────────
        # Fase C PIAR: el chat en modo PIAR es por estudiante, así que
        # cada mensaje se asocia al estudiante para poder filtrar el
        # historial por (grupo, modo, estudiante). NULL para mensajes
        # legacy y para modos != piar — retro-compat total.
        if "id_estudiante" not in cols_msg:
            conn.execute(text(
                "ALTER TABLE mensajes ADD COLUMN id_estudiante VARCHAR(36) "
                "REFERENCES estudiantes(id_estudiante)"
            ))
            conn.commit()
            print("✅ Migración: columna 'id_estudiante' agregada a 'mensajes' (nullable)")

    # ── rate_limit_counter (tabla nueva) ────────────────────────────
    # Se crea por metadata.create_all: SQLAlchemy detecta que la tabla no
    # existe y la crea. Es idempotente y compatible con Postgres y SQLite.
    # RateLimitCounter viene del import lazy para evitar ciclo circular.
    from models import RateLimitCounter  # noqa: F401
    Base.metadata.create_all(bind=engine, tables=[RateLimitCounter.__table__])

    # ── piar (tabla nueva) ──────────────────────────────────────────
    # Fase C — Generador de PIAR. Idempotente vía metadata.create_all.
    from models import PIAR  # noqa: F401
    Base.metadata.create_all(bind=engine, tables=[PIAR.__table__])

    # Refrescar inspector para verificar que quedó creada (log claro)
    inspector = inspect(engine)
    if "rate_limit_counter" in inspector.get_table_names():
        print("✅ Migración: tabla 'rate_limit_counter' verificada/creada")
    if "piar" in inspector.get_table_names():
        print("✅ Migración: tabla 'piar' verificada/creada")

    print("✅ Migraciones aplicadas")


# ============================================================
# SEED: USUARIO DE PRUEBA CON PLAN PRO
# ============================================================

def seed_pro_user():
    """
    Asegura que prueba1@prueba.com tenga suscripción Pro activa.
    Idempotente: solo hace cambios si el plan no es 'pro' todavía.
    """
    db: Session = SessionLocal()
    try:
        from models import Docente
        docente = db.query(Docente).filter(Docente.email == "prueba1@prueba.com").first()
        if not docente:
            print("ℹ️  Usuario prueba1@prueba.com no encontrado — se creará al registrarse")
            return

        sus = db.query(Suscripcion).filter(Suscripcion.id_docente == docente.id_docente).first()
        if sus is None:
            sus = Suscripcion(id_docente=docente.id_docente, plan="pro", estado="activa")
            db.add(sus)
            db.commit()
            print("✅ Seed: suscripción Pro creada para prueba1@prueba.com")
        elif sus.plan != "pro":
            sus.plan = "pro"
            sus.estado = "activa"
            db.commit()
            print("✅ Seed: prueba1@prueba.com actualizado a Plan Pro")
        else:
            print("ℹ️  prueba1@prueba.com ya tiene Plan Pro")
    finally:
        db.close()
