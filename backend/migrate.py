"""
migrate.py — Migraciones de base de datos y seed de datos iniciales.

Se llama desde main.py en el evento startup, justo después de create_tables().
- apply_migrations(): agrega columnas nuevas a tablas existentes (idempotente).
- seed_pro_user(): sube a Plan Pro al usuario de prueba.
"""

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from database import engine, SessionLocal
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
