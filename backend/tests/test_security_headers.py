"""
Content-Security-Policy — origenes externos que el frontend efectivamente
carga (auditado con grep sobre frontend/*.html, ver comentario en main.py).

Un CSP demasiado angosto no truena en CI (los tests no ejecutan JS de
verdad) pero rompe el sitio en el navegador real — por eso este test
verifica explícitamente que cada origen usado por algún <script>/@import
siga whitelisteado, en vez de sólo snapshottear el string completo.
"""
from __future__ import annotations


def _csp(client_no_auth) -> str:
    r = client_no_auth.get("/index.html")
    assert r.status_code == 200
    csp = r.headers.get("content-security-policy")
    assert csp, "Content-Security-Policy ausente"
    return csp


def test_csp_permite_tailwind_y_fontawesome(client_no_auth):
    csp = _csp(client_no_auth)
    assert "https://cdn.tailwindcss.com" in csp
    assert "https://cdnjs.cloudflare.com" in csp


def test_csp_permite_socketio_y_jsdelivr(client_no_auth):
    """
    cdn.socket.io: chat.html, join.html, presentacion-docente.html.
    cdn.jsdelivr.net: marked.js (chat), qrcode.js/wordcloud2.js
    (presentacion-docente.html). Si estos faltan, el chat y las
    presentaciones interactivas quedan rotos en el navegador real.
    """
    csp = _csp(client_no_auth)
    assert "https://cdn.socket.io" in csp
    assert "https://cdn.jsdelivr.net" in csp


def test_csp_permite_google_fonts(client_no_auth):
    """index.html y precios.html cargan Nunito/Inter vía @import de
    fonts.googleapis.com; los .woff2 reales vienen de fonts.gstatic.com."""
    csp = _csp(client_no_auth)
    assert "https://fonts.googleapis.com" in csp
    assert "https://fonts.gstatic.com" in csp


def test_csp_permite_wompi(client_no_auth):
    csp = _csp(client_no_auth)
    assert "https://checkout.wompi.co" in csp


def test_csp_tambien_presente_en_endpoints_api(client_no_auth):
    """El header se inyecta globalmente — también debe estar en /api/*."""
    r = client_no_auth.get("/health")
    assert r.status_code == 200
    assert r.headers.get("content-security-policy")
