"""
extend_trial.py — Extiende manualmente el trial de un docente. Sprint
trial-7-dias. Uso interno (soporte/ventas), NO expuesto como endpoint.

    python scripts/extend_trial.py --email docente@ejemplo.com --days 7

Política de extensión (ya que el sprint no la especificó):
- Si trial_ends_at sigue en el futuro, se suma --days a partir de ESE
  valor (no se pisa tiempo que el docente ya tenía).
- Si trial_ends_at es NULL, ya pasó, o plan='expirado', se suma --days
  a partir de AHORA y el plan vuelve a 'trial'.
- Nunca toca cuentas con plan='activo' (serían docentes de pago o
  grandfathered) — se aborta con un mensaje explícito en vez de asumir
  qué se quiso decir.

Se corre desde backend/: `python scripts/extend_trial.py ...`
"""
import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from database import SessionLocal  # noqa: E402
from models import Docente  # noqa: E402


def extend_trial(email: str, days: int) -> None:
    db = SessionLocal()
    try:
        docente = db.query(Docente).filter(Docente.email == email).first()
        if not docente:
            print(f"❌ No existe ningún docente con email '{email}'.")
            return

        if docente.plan == "activo":
            print(
                f"⚠️  {email} tiene plan='activo' (pago o grandfathered) — "
                "no tiene trial que extender. Nada hecho."
            )
            return

        ahora = datetime.utcnow()
        base = docente.trial_ends_at if (docente.trial_ends_at and docente.trial_ends_at > ahora) else ahora
        docente.trial_ends_at = base + timedelta(days=days)
        docente.plan = "trial"
        db.commit()

        print(
            f"✅ Trial de {email} extendido {days} día(s). "
            f"Nueva fecha de vencimiento: {docente.trial_ends_at.isoformat()}."
        )
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extiende el trial de un docente.")
    parser.add_argument("--email", required=True, help="Email del docente.")
    parser.add_argument("--days", type=int, required=True, help="Días adicionales a otorgar.")
    args = parser.parse_args()
    extend_trial(args.email, args.days)
