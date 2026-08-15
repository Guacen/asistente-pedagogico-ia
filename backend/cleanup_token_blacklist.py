"""
cleanup_token_blacklist.py — purga filas de token_blacklist cuyo token
ya habría expirado por su cuenta (expires_at < now). Sprint
seguridad-avanzada, tarea 2.

Uso (cron diario en Railway — Settings > Cron Schedule del servicio, o
un servicio "worker" separado apuntando a este comando):

    python cleanup_token_blacklist.py

Mismo patrón que seed_dbas.py / seed_pro_user(): script standalone,
idempotente, que abre su propia sesión sobre SessionLocal y no depende
del ciclo de vida de la app FastAPI. También se ejecuta una vez al
arrancar el proceso web (ver main.py on_startup) como best-effort
adicional para instalaciones sin cron configurado — no reemplaza al
cron diario porque un proceso web de larga duración no vuelve a correr
el startup hook entre deploys.
"""
from datetime import datetime

from database import SessionLocal
from models import TokenBlacklist


def limpiar_blacklist_expirados() -> int:
    """Borra los tokens ya expirados de la blacklist. Devuelve cuántos borró."""
    db = SessionLocal()
    try:
        borrados = (
            db.query(TokenBlacklist)
            .filter(TokenBlacklist.expires_at < datetime.utcnow())
            .delete(synchronize_session=False)
        )
        db.commit()
        if borrados:
            print(f"✅ cleanup_token_blacklist: {borrados} token(s) expirado(s) purgado(s)")
        else:
            print("ℹ️  cleanup_token_blacklist: nada que purgar")
        return borrados
    finally:
        db.close()


if __name__ == "__main__":
    limpiar_blacklist_expirados()
