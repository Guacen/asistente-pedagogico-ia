# Maestr.ia — Tu colega que conoce la ley

Asistente pedagógico con IA para docentes colombianos.
Genera PIARs, planeaciones y evaluaciones socioemocionales
con base legal sólida (Decreto 1421 de 2017).

Ver [`docs/PLAN.md`](docs/PLAN.md) para el estado completo del producto, backlog priorizado y deuda técnica conocida.

## Stack

- fastapi 0.111.0
- uvicorn[standard] 0.29.0
- python-socketio 5.11.2
- sqlalchemy 2.0.41
- psycopg2-binary 2.9.10
- python-jose[cryptography] 3.3.0
- passlib[bcrypt] 1.7.4 / bcrypt 4.0.1
- anthropic ≥0.40.0 (Claude, proveedor primario)
- google-genai ≥1.0.0 (Gemini, fallback si no hay `CLAUDE_API_KEY` válida)
- stripe 9.9.0
- python-docx 1.1.2
- pydantic-settings 2.2.1
- pytest 8.4.2

## Setup local

Requisitos: Python 3.11+ (SQLAlchemy 2.0.41 no es compatible con 3.13).

```bash
cd backend
pip install -r requirements.txt

cp .env.example .env
# Editá .env y completá al menos CLAUDE_API_KEY (o GOOGLE_API_KEY como alternativa)

uvicorn main:socket_app --reload --port 8000
```

La app queda disponible en `http://localhost:8000/` (frontend), `http://localhost:8000/docs` (Swagger) y el WebSocket de chat vía Socket.io en la misma URL. En desarrollo local, sin `DATABASE_URL` configurada, se usa SQLite automáticamente (no requiere instalar nada).

Si no configurás `SENDGRID_API_KEY` ni el bloque SMTP, el envío de correos (verificación de email) cae a modo "LogOnly": el link de verificación se imprime por consola en vez de enviarse — el flujo de registro funciona igual sin cuenta de correo real.

## Variables de entorno

| Variable | Descripción |
|---|---|
| `DATABASE_URL` | Cadena de conexión — SQLite en dev, PostgreSQL en producción (Railway) |
| `SECRET_KEY` | Clave secreta para firmar JWT |
| `ALGORITHM` | Algoritmo JWT (default `HS256`) |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Expiración del token (default 10080 = 7 días) |
| `CLAUDE_API_KEY` (alias `ANTHROPIC_API_KEY`) | Clave de la API de Anthropic |
| `CLAUDE_MODEL` | Modelo de Claude a usar |
| `GOOGLE_API_KEY` | Clave de Gemini — fallback si `CLAUDE_API_KEY` no es válida |
| `GEMINI_MODEL` | Modelo de Gemini a usar |
| `STRIPE_SECRET_KEY` | Clave secreta de Stripe |
| `STRIPE_WEBHOOK_SECRET` | Secreto del webhook de Stripe |
| `STRIPE_PRICE_ID_PRO` | ID del precio del plan Pro en Stripe |
| `FRONTEND_URL` | URL del frontend, usada para CORS |
| `SENDGRID_API_KEY` | Clave de SendGrid (envío de correo) |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASSWORD` / `SMTP_TLS` | Config SMTP alternativa al envío de correo |
| `FROM_EMAIL` / `FROM_NAME` | Remitente de los correos enviados |
| `UPLOAD_DIR` | Carpeta de archivos subidos |
| `MAX_FILE_SIZE_MB` | Tamaño máximo de archivo subido |
| `ENVIRONMENT` | `development` / `production` |

## Deploy en Railway

1. Crear proyecto nuevo en [railway.app](https://railway.app)
2. Agregar servicio PostgreSQL → copiar `DATABASE_URL`
3. Agregar servicio desde GitHub → Root Directory = `backend/`
4. Configurar las variables de entorno de la tabla anterior
5. Railway detecta el `Procfile` y corre `uvicorn main:socket_app`

## Tests

```bash
cd backend
python -m pytest tests/ -v
```

255 tests en 25 archivos, cubriendo auth, aislamiento multi-tenant, chat multi-modo, sesiones, PIAR (generación, formato, validación JSON, cumplimiento legal), calificaciones/boletines, DOCX, multi-institución e import CSV. Se ejecutan automáticamente en CI (GitHub Actions) en cada push/PR contra `main`.
