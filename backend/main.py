"""
Asistente Pedagógico IA — Backend FastAPI + Socket.io

Una sola URL para todo (desarrollo y producción):
    http://localhost:8000        → index.html (frontend)
    http://localhost:8000/login.html → login
    http://localhost:8000/api/... → API REST
    http://localhost:8000/docs   → Swagger UI

Para correr en desarrollo:
    uvicorn main:socket_app --reload --port 8000

Para Railway/Render (Procfile):
    web: uvicorn main:socket_app --host 0.0.0.0 --port $PORT
"""

import os
from pathlib import Path

import socketio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from config import settings
from database import create_tables
from migrate import apply_migrations, seed_pro_user

# Importar routers
import auth
import chat
import grupos
import suscripciones

# Importar Socket.io (el objeto sio vive en socket_events)
from socket_events import sio

# Carpeta raíz del frontend (un nivel arriba de /backend)
FRONTEND_DIR = Path(__file__).parent.parent

# ============================================================
# FASTAPI APP
# ============================================================

app = FastAPI(
    title="Asistente Pedagógico IA",
    description="Backend para la plataforma SaaS de apoyo pedagógico con IA",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# ============================================================
# CORS
# ============================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        settings.FRONTEND_URL,
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://localhost:8080",
        "http://127.0.0.1:5500",
        "http://localhost:5500",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================
# ROUTERS API  (/api/...)
# ============================================================

app.include_router(auth.router)
app.include_router(grupos.router)
app.include_router(chat.router)
app.include_router(suscripciones.router)

# ============================================================
# ARCHIVOS SUBIDOS (/uploads/...)
# ============================================================

os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=settings.UPLOAD_DIR), name="uploads")

# ============================================================
# HEALTH CHECK
# ============================================================

@app.get("/health")
def health():
    return {"status": "healthy", "app": "Asistente Pedagógico IA"}

# ============================================================
# STARTUP: crear tablas
# ============================================================

@app.on_event("startup")
def on_startup():
    create_tables()
    print("✅ Tablas creadas / verificadas")
    apply_migrations()
    seed_pro_user()
    print(f"🌐 Frontend servido desde: {FRONTEND_DIR}")
    print(f"🤖 Claude model: {settings.CLAUDE_MODEL}")
    print(f"🔑 Claude API Key: {'configurada ✅' if settings.CLAUDE_API_KEY and 'XXXX' not in settings.CLAUDE_API_KEY else 'NO configurada ❌ — edita el .env'}")
    print("📖 Docs: http://localhost:8000/docs")
    print("🚀 App:  http://localhost:8000")

# ============================================================
# FRONTEND ESTÁTICO — DEBE IR AL FINAL (catch-all)
# Sirve todos los .html, .css, .js desde la carpeta raíz del proyecto
# ============================================================

if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")

# ============================================================
# SOCKET.IO ASGI WRAPPER
# ← Este es el objeto que expone uvicorn
# ============================================================

socket_app = socketio.ASGIApp(sio, other_asgi_app=app)
