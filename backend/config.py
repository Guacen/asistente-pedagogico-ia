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

    # Claude AI — acepta CLAUDE_API_KEY (nombre histórico del proyecto) y
    # ANTHROPIC_API_KEY (nombre estándar del SDK oficial). Cualquiera de
    # los dos configurada en el entorno es válida; si están ambas, gana
    # la primera de la lista.
    CLAUDE_API_KEY: str = Field(
        default="sk-ant-XXXXXXXXXX",
        validation_alias=AliasChoices("CLAUDE_API_KEY", "ANTHROPIC_API_KEY"),
    )
    CLAUDE_MODEL: str = "claude-opus-4-5"

    # Stripe
    STRIPE_SECRET_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""
    STRIPE_PRICE_ID_PRO: str = ""

    # CORS
    FRONTEND_URL: str = "http://localhost:8080"

    # Archivos
    UPLOAD_DIR: str = "uploads"
    MAX_FILE_SIZE_MB: int = 10

    # Entorno
    ENVIRONMENT: str = "development"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
