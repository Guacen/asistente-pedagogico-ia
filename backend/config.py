from typing import Optional

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Base de datos
    # Desarrollo local: SQLite (no requiere instalación)
    # Producción (Railway): postgresql://user:pass@host:5432/db
    DATABASE_URL: str = "sqlite:///./asistente_pedagogico.db"

    # JWT
    SECRET_KEY: str = "cambia-esta-clave-en-produccion"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 10080  # 7 días

    # Prueba gratuita self-service — sprint trial-7-dias.
    TRIAL_DIAS: int = 7

    # Claude AI — acepta CLAUDE_API_KEY (nombre histórico del proyecto) y
    # ANTHROPIC_API_KEY (nombre estándar del SDK oficial). Cualquiera de
    # los dos configurada en el entorno es válida; si están ambas, gana
    # la primera de la lista.
    CLAUDE_API_KEY: str = Field(
        default="sk-ant-XXXXXXXXXX",
        validation_alias=AliasChoices("CLAUDE_API_KEY", "ANTHROPIC_API_KEY"),
    )
    CLAUDE_MODEL: str = "claude-opus-4-5"

    # Gemini (Google) — proveedor alternativo. Si CLAUDE_API_KEY no está
    # configurada pero GOOGLE_API_KEY sí, el módulo llm.py usa Gemini como
    # fallback para chat y síntesis PIAR.
    GOOGLE_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.0-flash"

    # Stripe
    STRIPE_SECRET_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""
    STRIPE_PRICE_ID_PRO: str = ""  # legacy (USD) — ya no lo referencia el checkout, ver STRIPE_PRICE_ID_PRO_COP

    # Sprint stripe-colombia — Price IDs en COP, creados a mano en el
    # Stripe Dashboard (este código no los crea, solo los referencia).
    STRIPE_PRICE_ID_DOCENTE_COP: str = ""
    STRIPE_PRICE_ID_PRO_COP: str = ""

    # CORS
    FRONTEND_URL: str = "http://localhost:8080"

    # ── Envío de correo (sprint email-verification-consent) ──
    # Adapter con fallback automático: Resend > SendGrid > SMTP > LogOnly.
    # En dev local nada está configurado y cae al LogOnly, que sólo
    # imprime el link de verificación por consola — el flujo funciona
    # igual sin necesidad de cuenta de correo.
    # En Railway, SMTP no sirve (puerto saliente bloqueado) — usar
    # RESEND_API_KEY o SENDGRID_API_KEY. FROM_EMAIL siempre debe estar
    # (dirección del "from").
    RESEND_API_KEY: Optional[str] = Field(default=None)
    SENDGRID_API_KEY: str = ""
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_TLS: bool = True
    FROM_EMAIL: str = "no-reply@maestria.co"
    FROM_NAME: str = "Maestr.ia"

    # Archivos
    UPLOAD_DIR: str = "uploads"
    MAX_FILE_SIZE_MB: int = 10

    # Entorno
    ENVIRONMENT: str = "development"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()


# ============================================================
# LÍMITES POR PLAN (sprint stripe-colombia)
# Antes vivían hardcodeados en suscripciones.py — movidos acá para
# poder ajustarlos sin tocar el módulo de pagos. Las claves son los
# valores de Suscripcion.plan ("free"/"pro"); el checkout de Stripe
# ofrece dos precios en COP ("docente"/"pro") pero ambos activan el
# mismo plan interno "pro" — el webhook no distingue entre ellos (no
# se tocó esa lógica en este sprint).
# ============================================================
LIMITES_PLAN: dict = {
    "free": {"mensajes": 10, "grupos": 1},
    "pro": {"mensajes": 999999, "grupos": 999999},
}
