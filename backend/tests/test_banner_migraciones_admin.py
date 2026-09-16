"""
Sprint migraciones-aisladas (extra) — el banner rojo de migraciones
fallidas en el dashboard debe ser imposible de ignorar PARA UN ADMIN, y
completamente invisible para un docente normal.

No hay runner de JS en este repo — igual que test_xss_host_header.py
para chat.html, esto es verificación estática del archivo real que se
sirve: confirma que el gate por es_admin existe en el código, no que un
navegador lo ejecuta correctamente.
"""
from __future__ import annotations

from pathlib import Path

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


def _dashboard_html() -> str:
    path = FRONTEND_DIR / "dashboard.html"
    assert path.exists()
    return path.read_text(encoding="utf-8")


def _api_js() -> str:
    path = FRONTEND_DIR / "js" / "api.js"
    assert path.exists()
    return path.read_text(encoding="utf-8")


def test_banner_existe_oculto_por_default():
    html = _dashboard_html()
    assert 'id="banner-migraciones-fallidas"' in html
    # Debe estar oculto de entrada — sólo mostrarBannerMigracionesFallidasSiAplica
    # lo revela, y sólo tras confirmar es_admin.
    inicio = html.index('id="banner-migraciones-fallidas"')
    etiqueta_completa = html[inicio:html.index(">", inicio)]
    assert "hidden" in etiqueta_completa


def test_banner_enlaza_a_api_version():
    html = _dashboard_html()
    inicio = html.index('id="banner-migraciones-fallidas"')
    bloque = html[max(0, inicio - 200):inicio + 400]
    assert 'href="/api/version"' in bloque


def test_funcion_del_banner_verifica_es_admin_antes_de_cualquier_otra_cosa():
    html = _dashboard_html()
    assert "async function mostrarBannerMigracionesFallidasSiAplica(u)" in html
    inicio = html.index("async function mostrarBannerMigracionesFallidasSiAplica")
    fin = html.index("\n    }", inicio)
    cuerpo = html[inicio:fin]
    lineas = [l.strip() for l in cuerpo.splitlines() if l.strip() and not l.strip().startswith("//")]
    # La PRIMERA línea ejecutable del cuerpo debe ser el guard de es_admin
    # que corta para cualquiera que no sea admin — antes de llamar a
    # api.getVersion() o tocar el DOM.
    assert lineas[1].startswith("if (!u || !u.es_admin) return;"), (
        f"el guard de es_admin debe ser lo primero que corre: {lineas[1]!r}"
    )
    assert "api.getVersion()" in cuerpo


def test_cargar_datos_llama_al_banner_con_el_usuario():
    html = _dashboard_html()
    assert "mostrarBannerMigracionesFallidasSiAplica(u);" in html


def test_api_client_expone_get_version():
    js = _api_js()
    assert "async getVersion()" in js
    assert "/api/version" in js
