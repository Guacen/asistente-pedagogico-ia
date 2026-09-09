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
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from starlette.middleware.base import BaseHTTPMiddleware

from config import settings
from database import create_tables
from migrate import apply_migrations, seed_pro_user
from rate_limiter import limiter

# Importar routers
import admin
import auth
import chat
import documento
import grupos
import institucion
import malla
import observaciones
import pagos
import perfil
import piar
import presentaciones
import sesiones
import suscripciones

# Importar Socket.io (el objeto sio vive en socket_events)
from socket_events import sio
# Registra los handlers de Presentaciones Interactivas sobre `sio` — se
# importa sólo por su efecto lateral, no se usa ningún símbolo suyo acá.
import presentacion_events  # noqa: F401

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
# RATE LIMITING (slowapi) — sprint seguridad-avanzada
# El Limiter vive en rate_limiter.py (evita import circular con auth.py,
# que lo usa para decorar login/register/forgot-password/refresh).
# key_func=get_remote_address → límite por IP, no por docente (todavía
# no hay sesión en esos endpoints).
# ============================================================

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ============================================================
# CORS — restrictivo (sprint seguridad-avanzada)
# En producción SOLO el dominio real de Maestr.ia. Los orígenes de
# desarrollo local (localhost/127.0.0.1) sólo se agregan cuando
# ENVIRONMENT=development — nunca en el deploy de Railway.
# ============================================================

_CORS_ORIGINS_PROD = [
    "https://usemaestria.co",
    "https://www.usemaestria.co",
]
if settings.FRONTEND_URL not in _CORS_ORIGINS_PROD:
    _CORS_ORIGINS_PROD.append(settings.FRONTEND_URL)

origins = list(_CORS_ORIGINS_PROD)
if settings.ENVIRONMENT == "development":
    origins.extend([
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://localhost:8080",
        "http://127.0.0.1:5500",
        "http://localhost:5500",
        "http://localhost:3000",
    ])

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)

# ============================================================
# SECURITY HEADERS — sprint seguridad-avanzada
# Protección contra XSS, clickjacking y MIME sniffing en TODAS las
# respuestas.
#
# El CSP whitelistea exactamente los recursos externos que el frontend
# ya carga hoy (auditado con grep sobre frontend/*.html) — un CSP que
# sólo cubriera 'self' + checkout.wompi.co habría roto el sitio entero
# en el primer request real:
#   script-src: cdn.socket.io (chat en vivo + presentaciones interactivas),
#     cdn.tailwindcss.com (Tailwind vía CDN, usado en casi todas las
#     páginas), cdn.jsdelivr.net (marked.js del chat; qrcode.js y
#     wordcloud2.js de presentacion-docente.html), cdnjs.cloudflare.com
#     (Font Awesome), checkout.wompi.co (widget de pago),
#     static.cloudflareinsights.com (beacon de Cloudflare Browser
#     Insights — inyectado por el propio Cloudflare a nivel de edge en
#     páginas servidas a navegadores reales, no visible con curl).
#   style-src / font-src: cdnjs.cloudflare.com (CSS + webfonts de Font
#     Awesome, cargados por <link>/@font-face); fonts.googleapis.com /
#     fonts.gstatic.com (Google Fonts, @import en index.html/precios.html).
#   connect-src: checkout.wompi.co (el checkout de Wompi se embebe/
#     redirige desde precios.html/cuenta.html); static.cloudflareinsights.com
#     (el beacon de Browser Insights reporta analítica vía fetch/XHR
#     después de cargar, eso SÍ es connect-src — a diferencia de
#     cdn.tailwindcss.com/cdnjs.cloudflare.com/fonts.googleapis.com/
#     fonts.gstatic.com más abajo, que sólo cargan como <script>/<link>/
#     @font-face y ya están cubiertos por script-src/style-src/font-src;
#     se agregaron igual por pedido explícito, son inofensivos aunque
#     redundantes para esos 4 orígenes); wss://usemaestria.co — Safari/
#     WebKit no deriva conexiones wss:// del mismo origen a partir de
#     'self' de forma confiable (a diferencia de Chrome/Firefox), así
#     que se agrega explícito para que el WebSocket de Socket.io
#     (estudiantes uniéndose a una presentación en vivo) no quede
#     bloqueado en esos navegadores.
#   frame-src: checkout.wompi.co.
# ============================================================

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' "
            "https://checkout.wompi.co https://cdn.socket.io "
            "https://cdn.tailwindcss.com https://cdn.jsdelivr.net "
            "https://cdnjs.cloudflare.com https://static.cloudflareinsights.com; "
            "style-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com "
            "https://fonts.googleapis.com; "
            "font-src 'self' data: https://cdnjs.cloudflare.com "
            "https://fonts.gstatic.com; "
            "img-src 'self' data: https:; "
            "connect-src 'self' https://checkout.wompi.co "
            "https://cdn.tailwindcss.com https://cdnjs.cloudflare.com "
            "https://fonts.googleapis.com https://fonts.gstatic.com "
            "https://static.cloudflareinsights.com wss://usemaestria.co; "
            "frame-src https://checkout.wompi.co;"
        )
        return response


app.add_middleware(SecurityHeadersMiddleware)

# ============================================================
# CACHE-CONTROL — HTML, assets/ y css/
#
# assets/ y css/ (logo, icon, brand.css, main.css): Cloudflare cachea
# estáticos por extensión con su propio Edge Cache TTL (vimos un
# logo.png viejo servido desde caché 30min después de un deploy que ya
# tenía el archivo nuevo). "no-cache" (no "no-store") a propósito:
# Cloudflare/el navegador SIGUEN pudiendo cachear el byte, pero deben
# revalidar con el origen (ETag/Last-Modified, que StaticFiles ya
# calcula) antes de servir la copia cacheada.
#
# HTML (TODAS las páginas, no sólo presentaciones): mismo problema pero
# sin el cache-buster ?v= que sí tienen /js/ y /css/ — un estudiante
# entrando a join.html podía recibir una copia vieja cacheada por
# Cloudflare/el navegador (bug real: colgaba en "Uniendo…" con JS
# desactualizado sin ningún indicio de por qué). Se detecta por
# Content-Type en vez de por extensión de path — cubre StaticFiles
# (html=True), "/", y la ruta explícita /join/{codigo} por igual.
# "must-revalidate" además de "no-cache": una vez vencida cualquier
# frescura implícita, el cliente NO puede usar la copia stale ni
# siquiera en modo offline/error de red — debe ir al origen sí o sí.
# ============================================================

@app.middleware("http")
async def no_cache_para_html_y_assets_estaticos(request: Request, call_next):
    response = await call_next(request)
    path = request.url.path
    content_type = response.headers.get("content-type", "")
    if content_type.startswith("text/html"):
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
    elif path.startswith("/assets/") or path.startswith("/css/"):
        response.headers["Cache-Control"] = "no-cache"
    return response

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
app.include_router(pagos.router)
app.include_router(perfil.router)
app.include_router(presentaciones.router)
app.include_router(sesiones.router)
app.include_router(suscripciones.router)

# ============================================================
# LINK BONITO PARA ESTUDIANTES (/join/{codigo}) — Presentaciones
# Interactivas. Sirve join.html directo; el código se resuelve del
# lado del cliente leyendo window.location.pathname. Debe registrarse
# ANTES del mount de StaticFiles en "/" (más abajo, catch-all) para que
# esta ruta gane sobre el intento de servir un archivo literal
# "join/ABC123" que no existe.
# ============================================================

@app.get("/join/{codigo}")
def join_estudiante(codigo: str):
    return FileResponse(FRONTEND_DIR / "join.html")

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
    from cleanup_token_blacklist import limpiar_blacklist_expirados
    limpiar_blacklist_expirados()
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
