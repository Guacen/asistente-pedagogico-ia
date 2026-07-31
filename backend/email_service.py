"""
email_service.py — Envío de correo con adapter mixto (fallback automático).

Provider selection (elegido en tiempo de envío, no en import):
    1. SendGrid  — si `SENDGRID_API_KEY` está definida.
    2. SMTP      — si `SMTP_HOST` está definido (aunque haya SendGrid roto).
    3. LogOnly   — si nada está configurado. Imprime el link por consola;
                   en dev local esto es suficiente para probar el flujo.

Los import de SendGrid y smtplib son LAZY — no cuesta nada si el provider
no está en uso, y el módulo importa aunque sendgrid no esté instalado.

El adapter devuelve `True` cuando el envío fue confirmado; `False` si el
provider falló. La razón NO se propaga al caller: el flujo de registro
crea el docente aunque el correo falle (el docente puede pedir reenviar
después), y logueamos el error server-side para debugging.
"""
from __future__ import annotations

import logging
from typing import Optional, Protocol

from config import settings


logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# Protocol + implementaciones
# ═══════════════════════════════════════════════════════════════

class EmailProvider(Protocol):
    """Contrato de un provider de correo."""
    nombre: str

    def enviar(self, to_email: str, to_name: str, asunto: str,
               html: str, texto: str) -> bool:
        ...


class SendGridProvider:
    """SendGrid via Web API. Requiere `pip install sendgrid`."""
    nombre = "sendgrid"

    def enviar(self, to_email: str, to_name: str, asunto: str,
               html: str, texto: str) -> bool:
        try:
            # Import lazy — el paquete puede no estar instalado en dev.
            from sendgrid import SendGridAPIClient
            from sendgrid.helpers.mail import Mail
        except ImportError:
            logger.warning("sendgrid no instalado — omitiendo provider")
            return False

        try:
            message = Mail(
                from_email=(settings.FROM_EMAIL, settings.FROM_NAME),
                to_emails=(to_email, to_name),
                subject=asunto,
                plain_text_content=texto,
                html_content=html,
            )
            client = SendGridAPIClient(settings.SENDGRID_API_KEY)
            response = client.send(message)
            # 202 = Accepted (SendGrid confirma que encoló). Cualquier otra
            # cosa se considera fallo aunque el SDK no tire excepción.
            if 200 <= response.status_code < 300:
                logger.info("Correo enviado vía SendGrid a %s (status=%s)",
                            to_email, response.status_code)
                return True
            logger.error("SendGrid devolvió status=%s body=%s",
                         response.status_code, getattr(response, "body", ""))
            return False
        except Exception:
            logger.exception("Error enviando correo vía SendGrid a %s", to_email)
            return False


class SmtpProvider:
    """SMTP genérico (Gmail, Mailgun, AWS SES SMTP, servidor propio)."""
    nombre = "smtp"

    def enviar(self, to_email: str, to_name: str, asunto: str,
               html: str, texto: str) -> bool:
        # smtplib es stdlib, pero mantenemos el import local por consistencia.
        import smtplib
        from email.message import EmailMessage

        try:
            msg = EmailMessage()
            msg["Subject"] = asunto
            msg["From"] = f"{settings.FROM_NAME} <{settings.FROM_EMAIL}>"
            msg["To"] = f"{to_name} <{to_email}>"
            msg.set_content(texto)
            msg.add_alternative(html, subtype="html")

            with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10) as smtp:
                if settings.SMTP_TLS:
                    smtp.starttls()
                if settings.SMTP_USER:
                    smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                smtp.send_message(msg)
            logger.info("Correo enviado vía SMTP a %s", to_email)
            return True
        except Exception:
            logger.exception("Error enviando correo vía SMTP a %s", to_email)
            return False


class LogOnlyProvider:
    """
    Fallback de desarrollo: no envía, solo imprime el link por consola.
    Deja el flujo end-to-end funcional en dev sin cuentas de correo.
    """
    nombre = "log_only"

    def enviar(self, to_email: str, to_name: str, asunto: str,
               html: str, texto: str) -> bool:
        print("=" * 70)
        print(f"📧 [DEV email_service] Correo simulado para {to_name} <{to_email}>")
        print(f"   Asunto: {asunto}")
        print("   Texto plano:")
        for line in texto.splitlines():
            print(f"     {line}")
        print("=" * 70)
        return True


# ═══════════════════════════════════════════════════════════════
# Selector — se llama en cada envío para captar rebuild de settings
# ═══════════════════════════════════════════════════════════════

def _elegir_provider() -> EmailProvider:
    """Aplica la cascada SendGrid > SMTP > LogOnly."""
    if settings.SENDGRID_API_KEY:
        return SendGridProvider()
    if settings.SMTP_HOST:
        return SmtpProvider()
    return LogOnlyProvider()


# ═══════════════════════════════════════════════════════════════
# API pública
# ═══════════════════════════════════════════════════════════════

def enviar_correo_verificacion(
    email: str,
    nombre: str,
    link_verificacion: str,
    provider: Optional[EmailProvider] = None,
) -> bool:
    """
    Envía el correo de verificación al docente recién registrado.

    `link_verificacion` debe ser la URL absoluta (incluyendo el token) que
    apunta a `/verificar-email?token=XXX` en el frontend.

    Devuelve True si el provider confirmó el envío; False si falló. El
    caller no debe abortar el registro por un False — el docente puede
    pedir reenviar.

    `provider` es un parámetro opcional para inyectar un doble en tests.
    """
    prov = provider or _elegir_provider()
    asunto = "Verifica tu correo en Maestr.ia"
    texto = (
        f"Hola {nombre},\n\n"
        f"Gracias por registrarte en Maestr.ia. Para activar tu cuenta, "
        f"por favor confirma tu correo haciendo clic en el siguiente enlace "
        f"(válido por 24 horas):\n\n"
        f"{link_verificacion}\n\n"
        f"Si no fuiste tú quien creó esta cuenta, puedes ignorar este correo.\n\n"
        f"— El equipo de Maestr.ia"
    )
    html = _plantilla_html_verificacion(nombre, link_verificacion)
    return prov.enviar(email, nombre, asunto, html, texto)


def _plantilla_html_verificacion(nombre: str, link: str) -> str:
    """HTML minimal, inline styles, safe para clientes de correo."""
    # Escapamos el nombre del docente por precaución (fuente: form de registro).
    from html import escape
    nombre_esc = escape(nombre)
    link_esc = escape(link, quote=True)
    return f"""<!DOCTYPE html>
<html lang="es">
<head><meta charset="UTF-8"></head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #F5F7FA; margin: 0; padding: 32px 16px;">
  <div style="max-width: 520px; margin: 0 auto; background: #FFFFFF; border-radius: 12px; overflow: hidden; box-shadow: 0 2px 8px rgba(0,0,0,0.06);">
    <div style="background: #1D9E75; padding: 24px 32px; color: #FFFFFF;">
      <h1 style="margin: 0; font-size: 22px; font-weight: 600;">Maestr.ia</h1>
    </div>
    <div style="padding: 32px;">
      <p style="font-size: 16px; color: #1F2937; margin: 0 0 16px;">Hola {nombre_esc},</p>
      <p style="font-size: 15px; color: #374151; line-height: 1.55;">
        Gracias por registrarte en Maestr.ia. Para activar tu cuenta, confirma tu correo con el botón de abajo. El enlace es válido por <strong>24 horas</strong>.
      </p>
      <div style="text-align: center; margin: 28px 0;">
        <a href="{link_esc}" style="display: inline-block; background: #1D9E75; color: #FFFFFF; padding: 12px 28px; border-radius: 8px; text-decoration: none; font-weight: 600; font-size: 15px;">
          Verificar mi correo
        </a>
      </div>
      <p style="font-size: 13px; color: #6B7280; line-height: 1.5;">
        Si el botón no funciona, copia y pega este enlace en tu navegador:<br>
        <span style="word-break: break-all; color: #1D9E75;">{link_esc}</span>
      </p>
      <hr style="border: none; border-top: 1px solid #E5E7EB; margin: 24px 0;">
      <p style="font-size: 12px; color: #9CA3AF; margin: 0;">
        Si no fuiste tú quien creó esta cuenta, puedes ignorar este correo.
      </p>
    </div>
  </div>
</body>
</html>"""
