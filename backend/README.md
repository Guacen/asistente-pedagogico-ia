# Backend — Asistente Pedagógico IA

FastAPI + Socket.io + PostgreSQL + Claude API

## Inicio rápido (desarrollo local)

### 1. Requisitos
- Python 3.11+
- PostgreSQL corriendo localmente (o usar Railway)

### 2. Instalar dependencias
```bash
cd backend
pip install -r requirements.txt
```

### 3. Configurar variables de entorno
```bash
cp .env.example .env
```
Abre `.env` y completa:
- `DATABASE_URL` — tu PostgreSQL
- **`CLAUDE_API_KEY`** — tu clave de Anthropic ← **OBLIGATORIO**
- `SECRET_KEY` — genera una con `python -c "import secrets; print(secrets.token_hex(32))"`

### 4. Correr el servidor
```bash
uvicorn main:socket_app --reload --port 8000
```

Documentación interactiva: http://localhost:8000/docs

---

## Deploy en Railway

1. Crear proyecto nuevo en [railway.app](https://railway.app)
2. Agregar servicio PostgreSQL → copiar `DATABASE_URL`
3. Agregar servicio desde GitHub → apuntar a carpeta `backend/`
4. Variables de entorno en Railway:
   - Todas las del `.env.example`
   - Railway agrega `PORT` automáticamente
5. Railway detecta el `Procfile` y corre `uvicorn main:socket_app`

---

## Estructura

```
backend/
├── main.py           # Entrada: FastAPI + Socket.io ASGI wrapper
├── config.py         # Settings desde .env (incluye CLAUDE_API_KEY)
├── database.py       # SQLAlchemy engine y sesión
├── models.py         # Modelos de DB (Docente, Grupo, Estudiante, etc.)
├── schemas.py        # Esquemas Pydantic (request/response)
├── auth.py           # Endpoints de autenticación + JWT
├── grupos.py         # Grupos, Estudiantes, Notas, Archivos
├── chat.py           # Historial de chat
├── suscripciones.py  # Stripe + planes Free/Pro
├── ia.py             # Integración Claude API (streaming)
├── socket_events.py  # Eventos Socket.io en tiempo real
├── Procfile          # Para Railway/Render
├── requirements.txt
└── .env.example      # Plantilla de variables de entorno
```

## Variables de entorno requeridas

| Variable | Descripción |
|---|---|
| `DATABASE_URL` | URL de PostgreSQL |
| `SECRET_KEY` | Clave secreta para JWT |
| `CLAUDE_API_KEY` | **Tu clave de Anthropic** |
| `FRONTEND_URL` | URL del frontend (para CORS) |
| `STRIPE_SECRET_KEY` | Clave Stripe (opcional en desarrollo) |
