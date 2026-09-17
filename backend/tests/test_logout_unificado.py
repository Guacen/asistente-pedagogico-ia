"""
Sprint auto-refresh-jwt-frontend — las 3 páginas con botón real de
"cerrar sesión" (chat.html, dashboard.html, trial-expirado.html) tenían
cada una su propia implementación ad-hoc que sólo limpiaba localStorage
— NINGUNA llamaba al backend, así que el fix de logout() (blacklistear
access + refresh token) no se aplicaba en la práctica a lo que un
docente click-eaba de verdad. Ahora las tres delegan en Auth.logout(),
la única implementación real (ver tests/js/test_api_refresh.js para
api.logout() y tests/test_auto_refresh_jwt.py para el backend).

Verificación estática (no hay runner de JS con DOM en este repo para
estos archivos completos) — confirma que el código servido delega en
Auth.logout(), no que un navegador lo ejecuta.
"""
from __future__ import annotations

from pathlib import Path

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


def _leer(nombre: str) -> str:
    path = FRONTEND_DIR / nombre
    assert path.exists()
    return path.read_text(encoding="utf-8")


def test_chat_cerrar_sesion_delega_en_auth_logout():
    html = _leer("chat.html")
    inicio = html.index("function cerrarSesion()")
    fin = html.index("\n}", inicio)
    cuerpo = html[inicio:fin]
    assert "Auth.logout()" in cuerpo
    assert "localStorage.clear()" not in cuerpo


def test_dashboard_cerrar_sesion_delega_en_auth_logout():
    html = _leer("dashboard.html")
    inicio = html.index("function cerrarSesion()")
    fin = html.index("\n    }", inicio)
    cuerpo = html[inicio:fin]
    assert "Auth.logout()" in cuerpo
    assert "localStorage.clear()" not in cuerpo


def test_trial_expirado_boton_logout_delega_en_auth_logout():
    html = _leer("trial-expirado.html")
    inicio = html.index("btn-logout")
    fin = html.index("});", inicio)
    cuerpo = html[inicio:fin]
    assert "Auth.logout()" in cuerpo
    assert "localStorage.clear()" not in cuerpo
