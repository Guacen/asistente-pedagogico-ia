"""
Sprint auto-refresh-jwt-frontend, Parte B — verificación estática de
chat.html (no hay runner de JS con DOM real en este repo para un
archivo tan grande — ver tests/js/ para la lógica async de api.js/
auth.js, que sí corre de verdad). Mismo nivel de garantía que ya usa
test_xss_host_header.py para este mismo archivo: confirma que el código
real que se sirve tiene el wiring correcto, no que un navegador lo
ejecuta.

Cubre el requisito "mostrar un mensaje claro con opción de reintentar,
nunca un spinner mudo indefinido":
- El banner de error+reintentar existe y arranca oculto.
- ia_error (el evento que dispara el backend en timeout u otros
  errores) llama a mostrarErrorConReintentar en su rama genérica.
- El botón de reintentar reenvía el último payload sin pisar el texto
  que el docente ya escribió (el input se vació al enviar).
"""
from __future__ import annotations

from pathlib import Path

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


def _chat_html() -> str:
    path = FRONTEND_DIR / "chat.html"
    assert path.exists()
    return path.read_text(encoding="utf-8")


def test_banner_error_reintentar_existe_oculto_por_default():
    html = _chat_html()
    assert 'id="chat-error-retry"' in html
    inicio = html.index('id="chat-error-retry"')
    etiqueta_completa = html[inicio:html.index(">", inicio)]
    assert "hidden" in etiqueta_completa
    assert 'id="chat-error-retry-msg"' in html
    assert 'id="btn-reintentar-mensaje"' in html


def test_ia_error_muestra_el_banner_de_reintentar_en_el_caso_generico():
    html = _chat_html()
    inicio = html.index("socket.on('ia_error'")
    fin = html.index("});", inicio)
    cuerpo = html[inicio:fin]
    assert "mostrarErrorConReintentar(" in cuerpo


def test_boton_reintentar_reenvia_el_ultimo_payload():
    html = _chat_html()
    assert "let _ultimoPayloadEnviado = null;" in html
    assert "_ultimoPayloadEnviado = payload;" in html
    inicio = html.index("btn-reintentar-mensaje').addEventListener")
    fin = html.index("});", inicio)
    cuerpo = html[inicio:fin]
    assert "_ultimoPayloadEnviado" in cuerpo
    assert "_enviarPayload(" in cuerpo


def test_mostrar_y_ocultar_error_reintentar_existen():
    html = _chat_html()
    assert "function mostrarErrorConReintentar(msg)" in html
    assert "function ocultarErrorConReintentar()" in html
