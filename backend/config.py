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

    # Claude AI  ← TU CLAVE VA EN EL ARCHIVO .env
    CLAUDE_API_KEY: str = "sk-ant-XXXXXXXXXX"
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
