"""
Asistente Pedagógico IA — Backend FastAPI + Socket.io

Para correr en desarrollo:
    uvicorn main:socket_app --reload --port 8000

Para Railway/Render (Procfile):
    web: uvicorn main:socket_app --host 0.0.0.0 --port $PORT
"""

import os

import socketio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from config import settings
from database import create_tables

# Importar routers
import auth
import chat
import grupos
import suscripciones

# Importar Socket.io (el objeto sio vive en socket_events)
from socket_events import sio

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
        "http://localhost:8080",
        "http://127.0.0.1:5500",
        "http://localhost:5500",
        "http://127.0.0.1:8080",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================
# ROUTERS
# ============================================================

app.include_router(auth.router)
app.include_router(grupos.router)
app.include_router(chat.router)
app.include_router(suscripciones.router)

# ============================================================
# ARCHIVOS ESTÁTICOS (carpeta uploads)
# ============================================================

os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=settings.UPLOAD_DIR), name="uploads")

# ============================================================
# HEALTH CHECK
# ============================================================

@app.get("/")
def root():
    return {"status": "ok", "app": "Asistente Pedagógico IA", "version": "1.0.0"}


@app.get("/health")
def health():
    return {"status": "healthy"}

# ============================================================
# STARTUP: crear tablas
# ============================================================

@app.on_event("startup")
def on_startup():
    create_tables()
    print("✅ Tablas creadas / verificadas")
    print(f"📡 CORS habilitado para: {settings.FRONTEND_URL}")
    print(f"🤖 Claude model: {settings.CLAUDE_MODEL}")
    print(f"🔑 Claude API Key: {'configurada ✅' if settings.CLAUDE_API_KEY and 'XXXX' not in settings.CLAUDE_API_KEY else 'NO configurada ❌ — edita el .env'}")

# ============================================================
# SOCKET.IO ASGI WRAPPER
# ← Este es el objeto que expone uvicorn
# ============================================================

socket_app = socketio.ASGIApp(sio, other_asgi_app=app)
