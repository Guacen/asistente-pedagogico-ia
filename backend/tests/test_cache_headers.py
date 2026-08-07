"""
Cache-Control para estáticos servidos por StaticFiles (backend/frontend/).

Contexto: Cloudflare cachea /assets/*.png y /css/*.css con su propio
Edge Cache TTL por extensión — un deploy con un logo.png nuevo se sirvió
desde caché por ~30min pese a que el origen ya tenía el archivo nuevo.
"no-cache" (no "no-store") fuerza revalidación con el origen en cada
request sin prohibir el cacheo del byte en sí.
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


def test_html_no_lleva_no_cache(client_no_auth):
    """El middleware sólo debe tocar assets/ y css/ — no las páginas HTML."""
    r = client_no_auth.get("/index.html")
    assert r.status_code == 200
    assert r.headers.get("cache-control") != "no-cache"


def test_api_no_lleva_cache_control_no_cache(client_no_auth):
    """Tampoco debe inyectarse en respuestas de la API."""
    r = client_no_auth.get("/health")
    assert r.status_code == 200
    assert r.headers.get("cache-control") != "no-cache"
