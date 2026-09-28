"""
Sprint primer-uso, Parte D — verificación estática del frontend (no hay
runner de JS con DOM real para estos archivos en este repo, mismo nivel
de garantía que el resto de tests de frontend de esta sesión):
- api.js captura el correlation_id de cualquier error REST.
- chat.html captura el correlation_id de cualquier ia_error (socket).
- El widget reportar-problema.js sólo pide la descripción al docente —
  todo lo demás se captura solo.
- El link a reportes.html en el dashboard está oculto por default y
  gateado por es_admin, igual que el banner de migraciones fallidas.
- reportes.html existe y llama al endpoint admin-only.
"""
from __future__ import annotations

from pathlib import Path

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


def _leer(nombre: str) -> str:
    path = FRONTEND_DIR / nombre
    assert path.exists(), f"falta {nombre}"
    return path.read_text(encoding="utf-8")


def test_api_js_captura_correlation_id_de_errores_rest():
    js = _leer("js/api.js")
    assert "_capturarCorrelationId" in js
    assert "ultimo_correlation_id" in js
    assert "crearReporteProblema" in js
    assert "listarReportesProblema" in js


def test_chat_html_captura_correlation_id_de_ia_error():
    html = _leer("chat.html")
    inicio = html.index("socket.on('ia_error'")
    # el guard de captura debe estar ANTES de las ramas específicas
    # (trial_expirado, rate_limit_diario, etc.) — si un ia_error de
    # timeout también trae un code que cae en alguna rama con return
    # temprano, igual se captura el correlation_id primero.
    bloque = html[inicio:inicio + 800]
    assert "ultimo_correlation_id" in bloque
    assert bloque.index("ultimo_correlation_id") < bloque.index("trial_expirado")


def test_widget_reportar_problema_existe_y_captura_todo_menos_la_descripcion():
    js = _leer("js/reportar-problema.js")
    # Lo único que el docente escribe:
    assert "reporte-descripcion" in js
    # Todo lo demás se captura automático:
    assert "window.location.pathname" in js
    assert "localStorage.getItem('ultimo_correlation_id')" in js
    assert "navigator.userAgent" in js
    assert "_detectarNavegador" in js
    assert "_esMovil" in js
    # Minimización de datos — nunca se manda el user-agent crudo (sólo
    # se usa localmente para DERIVAR navegador/es_movil), ni capturas de
    # pantalla, ni nada de otros campos del formulario.
    payload_enviado = js[js.index("crearReporteProblema"):js.index("crearReporteProblema") + 400]
    assert "navigator.userAgent" not in payload_enviado
    assert "screenshot" not in js.lower()
    assert "canvas" not in js.lower()


def test_widget_reportar_problema_esta_incluido_en_paginas_autenticadas():
    paginas = [
        "dashboard.html", "chat.html", "grupos.html", "grupo-panel.html",
        "cuenta.html", "panel-docente.html", "pago-resultado.html",
        "presentacion-docente.html", "trial-expirado.html", "precios.html",
    ]
    for pagina in paginas:
        html = _leer(pagina)
        assert "reportar-problema.js" in html, f"{pagina} no incluye el widget"


def test_widget_no_esta_en_paginas_de_invitado():
    for pagina in ("login.html", "registro.html", "index.html"):
        html = _leer(pagina)
        assert "reportar-problema.js" not in html, f"{pagina} no debería incluir el widget"


def test_dashboard_link_a_reportes_oculto_por_default_y_gateado_por_admin():
    html = _leer("dashboard.html")
    assert 'id="link-reportes-admin"' in html
    inicio = html.index('id="link-reportes-admin"')
    etiqueta = html[inicio:html.index(">", inicio)]
    assert "hidden" in etiqueta
    assert "link-reportes-admin').hidden = !u.es_admin" in html


def test_reportes_html_existe_y_requiere_auth():
    html = _leer("reportes.html")
    assert "requireAuth()" in html
    assert "listarReportesProblema" in html
