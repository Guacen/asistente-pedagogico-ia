"""
rate_limiter.py — instancia única de slowapi.Limiter, separada de main.py
para que los routers (auth.py) puedan importarla y decorar sus endpoints
sin generar un import circular con main.py (que a su vez importa los
routers para registrarlos).
"""
from slowapi import Limiter
from slowapi.util import get_remote_address

# headers_enabled=True: la respuesta 429 incluye Retry-After (y
# X-RateLimit-*) — sin esto slowapi NO agrega esos headers por default.
limiter = Limiter(key_func=get_remote_address, headers_enabled=True)
