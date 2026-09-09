"""
Cache-Control para HTML y estáticos servidos por StaticFiles (backend/frontend/).

Contexto: Cloudflare cachea /assets/*.png y /css/*.css con su propio
Edge Cache TTL por extensión — un deploy con un logo.png nuevo se sirvió
desde caché por ~30min pese a que el origen ya tenía el archivo nuevo.
"no-cache" (no "no-store") fuerza revalidación con el origen en cada
request sin prohibir el cacheo del byte en sí.

SPRINT 2 (presentaciones): el mismo problema afectaba páginas HTML
completas — un estudiante entrando a join.html podía recibir una copia
vieja cacheada (sin el cache-buster ?v= que sí tienen /js/ y /css/).
Ahora TODA respuesta con Content-Type text/html lleva
"no-cache, must-revalidate", detectado por content-type (no por
extensión de path) para cubrir StaticFiles(html=True), "/" y rutas
explícitas como /join/{codigo} por igual.
"""
from __future__ import annotations


def test_assets_llevan_no_cache(client_no_auth):
    r = client_no_auth.get("/assets/logo.png")
    assert r.status_code == 200
    assert r.headers.get("cache-control") == "no-cache"


def test_css_lleva_no_cache(client_no_auth):
    r = client_no_auth.get("/css/brand.css")
    assert r.status_code == 200
    assert r.headers.get("cache-control") == "no-cache"


def test_html_lleva_no_cache_must_revalidate(client_no_auth):
    r = client_no_auth.get("/index.html")
    assert r.status_code == 200
    assert r.headers.get("cache-control") == "no-cache, must-revalidate"


def test_join_html_lleva_no_cache_must_revalidate(client_no_auth):
    """El caso que originó el bug: un estudiante entrando a join.html no
    debe poder recibir una copia vieja cacheada."""
    r = client_no_auth.get("/join.html")
    assert r.status_code == 200
    assert r.headers.get("cache-control") == "no-cache, must-revalidate"


def test_api_no_lleva_cache_control_no_cache(client_no_auth):
    """La API devuelve JSON, no HTML — no debe llevar este header."""
    r = client_no_auth.get("/health")
    assert r.status_code == 200
    assert r.headers.get("cache-control") != "no-cache, must-revalidate"
    assert r.headers.get("cache-control") != "no-cache"
