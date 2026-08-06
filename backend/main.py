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
import admin
import auth
import chat
import documento
import grupos
import institucion
import malla
import observaciones
import perfil
import piar
import sesiones
import suscripciones

# Importar Socket.io (el objeto sio vive en socket_events)
from socket_events import sio

# Carpeta del frontend, dentro de /backend para que Railway la incluya
# en el contenedor cuando el service tiene Root Directory=backend/.
FRONTEND_DIR = Path(__file__).parent / "frontend"

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

app.include_router(admin.router)
app.include_router(auth.router)
app.include_router(grupos.router)
app.include_router(chat.router)
app.include_router(documento.router)
app.include_router(piar.router)
app.include_router(institucion.router)
app.include_router(malla.router)
app.include_router(observaciones.router)
app.include_router(perfil.router)
app.include_router(sesiones.router)
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
    import llm
    proveedor = llm.proveedor_activo()
    if proveedor == "claude":
        print(f"🤖 Proveedor IA: Claude (Anthropic) — {settings.CLAUDE_MODEL}")
    elif proveedor == "gemini":
        print(f"🤖 Proveedor IA: Gemini (Google) — {settings.GEMINI_MODEL} (modo gratuito)")
    else:
        print("❌ Sin proveedor IA configurado — set ANTHROPIC_API_KEY (o CLAUDE_API_KEY) o GOOGLE_API_KEY")
    if not settings.STRIPE_SECRET_KEY:
        print("⚠️  WARNING: STRIPE_SECRET_KEY vacío — /api/suscripciones/checkout y el webhook fallarán (503) hasta configurarlo")
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
