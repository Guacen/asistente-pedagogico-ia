"""
Sprint xss-host-header — AUDITORIA-BETA.md #1 y #3: corta los dos
primeros eslabones de la cadena "CSV sin sanitizar → nombre inyectado →
marked.parse sin DOMPurify lo ejecuta → roba el JWT de localStorage", más
el hallazgo independiente de Host header sin validar en los links de
verificación/reset (CVE-2026-48710 / PYSEC-2026-161).

Este archivo cubre:
- TrustedHostMiddleware rechaza un Host falsificado (transporte).
- Los links de verificación/reset se arman desde settings.BASE_URL, NUNCA
  desde el header Host de la request — verificado incluso con un Host
  que SÍ está en la allowlist (testserver), para probar que ni siquiera
  un host "confiable pero distinto" se filtra al link.
- /health sigue respondiendo 200 con el middleware activo (la duda
  explícita del sprint: no romper el healthcheck de Railway).
- Verificación estática de que frontend/chat.html:
    · Carga DOMPurify localmente (no CDN).
    · NUNCA pasa marked.parse(...) a innerHTML sin envolver en
      DOMPurify.sanitize(...) primero.
    · La allowlist de DOMPurify no incluye tags/atributos peligrosos.
  (No hay runner de JS en este repo — pytest no ejecuta el navegador;
  éste es el mismo nivel de garantía que ya usa test_security_headers.py
  para el CSP: estático, sobre el archivo real que se sirve.)
"""
from __future__ import annotations

from pathlib import Path

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


# ═══════════════════════════════════════════════════════════════
# TrustedHostMiddleware
# ═══════════════════════════════════════════════════════════════

def test_host_falsificado_es_rechazado(client_no_auth):
    r = client_no_auth.get("/health", headers={"Host": "evil.test"})
    assert r.status_code == 400


def test_host_permitido_sigue_funcionando(client_no_auth):
    """testserver es el Host que manda TestClient por default — debe
    seguir en la allowlist o TODA la suite se rompería, no sólo este test."""
    r = client_no_auth.get("/health")
    assert r.status_code == 200


def test_health_check_sigue_respondiendo_200_con_middleware_activo(client_no_auth):
    r = client_no_auth.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "healthy"


# ═══════════════════════════════════════════════════════════════
# Los links de verificación/reset usan BASE_URL, no el header Host
# ═══════════════════════════════════════════════════════════════

def test_link_verificacion_usa_base_url_no_el_host_de_la_request(client_no_auth, monkeypatch):
    import auth
    from config import settings

    capturado = {}

    def _spy(email, nombre, link, **kwargs):
        capturado["link"] = link
        return True

    monkeypatch.setattr(auth, "enviar_correo_verificacion", _spy)

    r = client_no_auth.post("/api/auth/register", json={
        "email": "nuevo-xss-host@test.com",
        "password": "Passw0rd123",
        "nombre_completo": "Nuevo Docente",
        "consentimiento_datos": True,
    })
    assert r.status_code == 201, r.text
    assert "link" in capturado, "enviar_correo_verificacion no se llamó"
    link = capturado["link"]
    # El Host real de la request en este test es "testserver" (default de
    # TestClient) — si el link lo reflejara, empezaría con eso. No debe.
    assert link.startswith(settings.BASE_URL), link
    assert "testserver" not in link
    assert "/verificar-email.html?token=" in link


def test_link_reset_password_usa_base_url_no_el_host_de_la_request(client_no_auth, monkeypatch, seed_docente):
    import auth
    from config import settings

    capturado = {}

    def _spy(email, nombre, link, **kwargs):
        capturado["link"] = link
        return True

    monkeypatch.setattr(auth, "enviar_correo_reset_password", _spy)

    r = client_no_auth.post("/api/auth/forgot-password", json={
        "email": seed_docente["docente"].email,
    })
    assert r.status_code == 200, r.text
    assert "link" in capturado, "enviar_correo_reset_password no se llamó"
    link = capturado["link"]
    assert link.startswith(settings.BASE_URL), link
    assert "testserver" not in link
    assert "/nueva-password.html?token=" in link


def test_reenvio_verificacion_tambien_usa_base_url(client_no_auth, monkeypatch, db_session):
    """Mismo helper que /register, camino distinto (reenviar-verificacion)."""
    import auth
    from config import settings
    from models import Docente

    docente = Docente(
        email="reenvio-xss-host@test.com",
        password_hash="x",
        nombre_completo="Doc Reenvio",
        email_verificado=False,
        consentimiento_datos=True,
    )
    db_session.add(docente)
    db_session.commit()

    capturado = {}

    def _spy(email, nombre, link, **kwargs):
        capturado["link"] = link
        return True

    monkeypatch.setattr(auth, "enviar_correo_verificacion", _spy)

    r = client_no_auth.post("/api/auth/reenviar-verificacion", json={"email": docente.email})
    assert r.status_code == 200, r.text
    assert capturado["link"].startswith(settings.BASE_URL)


# ═══════════════════════════════════════════════════════════════
# chat.html — DOMPurify local + marked.parse siempre sanitizado
# (verificación estática del archivo real, ver docstring del módulo)
# ═══════════════════════════════════════════════════════════════

def _chat_html() -> str:
    path = FRONTEND_DIR / "chat.html"
    assert path.exists(), "frontend/chat.html no existe"
    return path.read_text(encoding="utf-8")


def test_dompurify_se_sirve_local_no_desde_cdn():
    html = _chat_html()
    assert 'src="js/vendor/dompurify.min.js"' in html
    # Ningún <script> de chat.html debe traer dompurify desde una URL externa.
    for linea in html.splitlines():
        if "dompurify" in linea.lower() and "<script" in linea.lower():
            assert "http://" not in linea and "https://" not in linea, \
                f"DOMPurify no debe cargarse desde CDN: {linea.strip()!r}"


def test_dompurify_vendored_existe_y_es_la_libreria_real():
    vendor = FRONTEND_DIR / "js" / "vendor" / "dompurify.min.js"
    assert vendor.exists(), "falta frontend/js/vendor/dompurify.min.js"
    contenido = vendor.read_text(encoding="utf-8")
    assert "DOMPurify" in contenido
    assert len(contenido) > 5000  # no es un stub vacío


def test_marked_parse_nunca_va_directo_a_innerhtml_sin_sanitizar():
    """Los dos únicos usos de marked.parse() en el chat deben pasar por
    renderMarkdownSeguro (que envuelve en DOMPurify.sanitize). Si alguien
    reintroduce `innerHTML = marked.parse(...)` directo, este test debe
    reventar."""
    html = _chat_html()
    assert "marked.parse(" in html, "sanity check: el archivo cambió de forma inesperada"
    for linea in html.splitlines():
        codigo = linea.strip()
        if codigo.startswith("//") or codigo.startswith("*") or codigo.startswith("<!--"):
            continue  # comentarios pueden mencionar "marked.parse(" en prosa
        if "marked.parse(" in codigo:
            # La única línea de CÓDIGO con marked.parse() debe ser la
            # que arma `html` dentro de renderMarkdownSeguro, nunca una
            # asignación directa a innerHTML.
            assert "const html = marked.parse" in codigo, \
                f"marked.parse() usado fuera de renderMarkdownSeguro: {codigo!r}"
    assert "innerHTML = marked.parse(" not in html
    assert ".innerHTML = renderMarkdownSeguro(" in html


def test_dompurify_config_no_permite_tags_peligrosos():
    html = _chat_html()
    assert "DOMPURIFY_CONFIG_MARKDOWN" in html
    inicio = html.index("DOMPURIFY_CONFIG_MARKDOWN")
    bloque = html[inicio:inicio + 800]
    for tag_prohibido in ("script", "iframe", "object", "embed", "style", "svg", "img", "form", "input"):
        assert f"'{tag_prohibido}'" not in bloque, f"'{tag_prohibido}' no debería estar en ALLOWED_TAGS"


def test_dompurify_config_no_permite_atributos_peligrosos():
    html = _chat_html()
    inicio = html.index("DOMPURIFY_CONFIG_MARKDOWN")
    bloque = html[inicio:inicio + 800]
    assert "ALLOWED_ATTR" in bloque
    linea_attr = [l for l in bloque.splitlines() if "ALLOWED_ATTR" in l][0]
    assert "onerror" not in linea_attr and "onclick" not in linea_attr and "style" not in linea_attr


def test_nombre_estudiante_y_notas_se_escapan_en_el_sidebar_del_chat():
    """Segundo render-site del mismo dato (además del propio chat de IA):
    el sidebar de estudiantes/notas también usa innerHTML — debe escapar."""
    html = _chat_html()
    assert "${escapeHtml(e.codigo_estudiante)}" in html
    assert "${escapeHtml(n.contenido)}" in html
