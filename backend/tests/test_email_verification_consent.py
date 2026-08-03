"""
Sprint email-verification-consent — cobertura del flujo end-to-end.

- Registro con y sin consentimiento (Ley 1581).
- Verificación de email por token (24h TTL, expirado, inexistente).
- /me bloqueado (401 code=email_no_verificado) hasta verificar.
- Reenvío de verificación (endpoint no filtra si el email existe).
- Aceptación grandfathered de consentimiento.
- email_service adapter — cascada de providers.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient


# ═══════════════════════════════════════════════════════════════
# email_service — cascada de providers
# ═══════════════════════════════════════════════════════════════

def test_email_service_sin_config_usa_log_only(monkeypatch):
    from config import settings
    import email_service

    monkeypatch.setattr(settings, "SENDGRID_API_KEY", "")
    monkeypatch.setattr(settings, "SMTP_HOST", "")

    prov = email_service._elegir_provider()
    assert prov.nombre == "log_only"


def test_email_service_con_smtp_prefiere_smtp(monkeypatch):
    from config import settings
    import email_service

    monkeypatch.setattr(settings, "SENDGRID_API_KEY", "")
    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.example.com")

    prov = email_service._elegir_provider()
    assert prov.nombre == "smtp"


def test_email_service_con_sendgrid_prefiere_sendgrid(monkeypatch):
    from config import settings
    import email_service

    monkeypatch.setattr(settings, "SENDGRID_API_KEY", "SG.dummy")
    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.example.com")  # ambos!

    prov = email_service._elegir_provider()
    # SendGrid gana la cascada
    assert prov.nombre == "sendgrid"


def test_log_only_provider_no_falla_ni_conecta_nada():
    """El LogOnly debe funcionar sin red / sin credenciales."""
    from email_service import LogOnlyProvider
    prov = LogOnlyProvider()
    ok = prov.enviar("t@t.com", "Test", "Asunto", "<b>html</b>", "texto")
    assert ok is True


def test_enviar_correo_verificacion_acepta_provider_inyectado():
    """El API público permite doblar el provider para tests."""
    from email_service import enviar_correo_verificacion

    class Doble:
        nombre = "doble"
        def __init__(self):
            self.llamadas = []
        def enviar(self, to_email, to_name, asunto, html, texto):
            self.llamadas.append({"to": to_email, "asunto": asunto, "texto": texto})
            return True

    doble = Doble()
    ok = enviar_correo_verificacion(
        "docente@test.com", "Docente Test",
        "https://app.example.com/verificar-email.html?token=ABC",
        provider=doble,
    )
    assert ok is True
    assert len(doble.llamadas) == 1
    llamada = doble.llamadas[0]
    assert llamada["to"] == "docente@test.com"
    assert "Verifica" in llamada["asunto"]
    assert "ABC" in llamada["texto"]  # el link con el token va en el cuerpo


# ═══════════════════════════════════════════════════════════════
# /api/auth/register — consentimiento requerido
# ═══════════════════════════════════════════════════════════════

def test_register_sin_consentimiento_devuelve_400(client_no_auth):
    r = client_no_auth.post("/api/auth/register", json={
        "nombre_completo": "Sin Consentimiento",
        "email": "sin@test.com",
        "password": "supersegura",
        # consentimiento_datos ausente → default False
    })
    assert r.status_code == 400
    assert "consentimiento" in r.text.lower() or "política" in r.text.lower() or "politica" in r.text.lower()


def test_register_con_consentimiento_crea_docente_no_verificado(
    client_no_auth, db_session,
):
    """
    Un registro nuevo persiste consentimiento_datos=True + fecha + IP y
    deja email_verificado=False. La respuesta debe reflejar ambos flags.
    """
    from models import Docente

    r = client_no_auth.post("/api/auth/register", json={
        "nombre_completo": "Con Consentimiento",
        "email": "con@test.com",
        "password": "supersegura",
        "consentimiento_datos": True,
    })
    assert r.status_code in (200, 201), r.text
    body = r.json()
    assert body["docente"]["email_verificado"] is False
    assert body["docente"]["consentimiento_datos"] is True

    # En DB también debe reflejar
    doc = db_session.query(Docente).filter_by(email="con@test.com").first()
    assert doc is not None
    assert doc.consentimiento_datos is True
    assert doc.fecha_consentimiento is not None
    assert doc.email_verificado is False


def test_register_crea_token_verificacion_con_24h_ttl(client_no_auth, db_session):
    """Debe crearse una fila EmailVerification asociada al nuevo docente."""
    from models import Docente, EmailVerification

    r = client_no_auth.post("/api/auth/register", json={
        "nombre_completo": "Token TTL", "email": "ttl@test.com",
        "password": "supersegura", "consentimiento_datos": True,
    })
    assert r.status_code in (200, 201)
    doc = db_session.query(Docente).filter_by(email="ttl@test.com").first()
    verif = db_session.query(EmailVerification).filter_by(id_docente=doc.id_docente).first()
    assert verif is not None
    assert verif.token
    # Expira entre ~23.5h y ~24.5h desde ahora (margen por tiempo de test).
    delta = verif.expires_at - datetime.utcnow()
    assert timedelta(hours=23) < delta < timedelta(hours=25)
    assert verif.verified_at is None


# ═══════════════════════════════════════════════════════════════
# /api/auth/me bloqueado hasta verificar
# ═══════════════════════════════════════════════════════════════

def test_me_bloqueado_si_email_no_verificado(client_no_auth):
    """Después del registro, /me devuelve 401 con code=email_no_verificado."""
    r_reg = client_no_auth.post("/api/auth/register", json={
        "nombre_completo": "Bloqueado", "email": "bloq@test.com",
        "password": "supersegura", "consentimiento_datos": True,
    })
    token = r_reg.json()["access_token"]

    r_me = client_no_auth.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r_me.status_code == 401
    # El detail debe incluir el code para que el frontend lo distinga de
    # un token expirado normal.
    assert "email_no_verificado" in r_me.text


def test_me_raw_funciona_aunque_no_verificado(client_no_auth):
    """/me-raw es la variante para la landing de verificación."""
    r_reg = client_no_auth.post("/api/auth/register", json={
        "nombre_completo": "Raw", "email": "raw@test.com",
        "password": "supersegura", "consentimiento_datos": True,
    })
    token = r_reg.json()["access_token"]

    r_me = client_no_auth.get("/api/auth/me-raw", headers={"Authorization": f"Bearer {token}"})
    assert r_me.status_code == 200
    assert r_me.json()["email"] == "raw@test.com"
    assert r_me.json()["email_verificado"] is False


# ═══════════════════════════════════════════════════════════════
# /api/auth/verificar-email
# ═══════════════════════════════════════════════════════════════

def test_verificar_email_con_token_valido_marca_verificado(client_no_auth, db_session):
    from models import Docente, EmailVerification

    client_no_auth.post("/api/auth/register", json={
        "nombre_completo": "Verif OK", "email": "vok@test.com",
        "password": "supersegura", "consentimiento_datos": True,
    })
    doc = db_session.query(Docente).filter_by(email="vok@test.com").first()
    verif = db_session.query(EmailVerification).filter_by(id_docente=doc.id_docente).first()

    r = client_no_auth.get(f"/api/auth/verificar-email?token={verif.token}")
    assert r.status_code == 200
    body = r.json()
    assert body["verificado"] is True
    assert body["email"] == "vok@test.com"

    db_session.refresh(doc)
    db_session.refresh(verif)
    assert doc.email_verificado is True
    assert doc.fecha_verificacion is not None
    assert verif.verified_at is not None


def test_verificar_email_dos_veces_es_idempotente(client_no_auth, db_session):
    from models import Docente, EmailVerification

    client_no_auth.post("/api/auth/register", json={
        "nombre_completo": "Idem", "email": "idem@test.com",
        "password": "supersegura", "consentimiento_datos": True,
    })
    doc = db_session.query(Docente).filter_by(email="idem@test.com").first()
    verif = db_session.query(EmailVerification).filter_by(id_docente=doc.id_docente).first()

    r1 = client_no_auth.get(f"/api/auth/verificar-email?token={verif.token}")
    r2 = client_no_auth.get(f"/api/auth/verificar-email?token={verif.token}")
    assert r1.status_code == 200
    assert r2.status_code == 200  # segunda vez también OK


def test_verificar_email_token_inexistente_devuelve_404(client_no_auth):
    r = client_no_auth.get("/api/auth/verificar-email?token=no-existe-xxx")
    assert r.status_code == 404


def test_verificar_email_token_expirado_devuelve_410(client_no_auth, db_session):
    from models import Docente, EmailVerification

    client_no_auth.post("/api/auth/register", json={
        "nombre_completo": "Expirado", "email": "exp@test.com",
        "password": "supersegura", "consentimiento_datos": True,
    })
    doc = db_session.query(Docente).filter_by(email="exp@test.com").first()
    verif = db_session.query(EmailVerification).filter_by(id_docente=doc.id_docente).first()

    # Forzamos que el token ya haya expirado
    verif.expires_at = datetime.utcnow() - timedelta(hours=1)
    db_session.commit()

    r = client_no_auth.get(f"/api/auth/verificar-email?token={verif.token}")
    assert r.status_code == 410
    assert "token_expirado" in r.text


def test_me_pasa_despues_de_verificar(client_no_auth, db_session):
    from models import Docente, EmailVerification

    r_reg = client_no_auth.post("/api/auth/register", json={
        "nombre_completo": "Ya Verificó", "email": "yav@test.com",
        "password": "supersegura", "consentimiento_datos": True,
    })
    token = r_reg.json()["access_token"]
    doc = db_session.query(Docente).filter_by(email="yav@test.com").first()
    verif = db_session.query(EmailVerification).filter_by(id_docente=doc.id_docente).first()

    client_no_auth.get(f"/api/auth/verificar-email?token={verif.token}")
    # SQLite in-memory + StaticPool comparte estado entre requests

    r_me = client_no_auth.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r_me.status_code == 200, r_me.text
    assert r_me.json()["email_verificado"] is True


# ═══════════════════════════════════════════════════════════════
# /api/auth/reenviar-verificacion
# ═══════════════════════════════════════════════════════════════

def test_reenviar_verificacion_email_conocido_crea_nuevo_token(client_no_auth, db_session):
    from models import Docente, EmailVerification

    client_no_auth.post("/api/auth/register", json={
        "nombre_completo": "Reenviar", "email": "reenv@test.com",
        "password": "supersegura", "consentimiento_datos": True,
    })
    doc = db_session.query(Docente).filter_by(email="reenv@test.com").first()

    tokens_antes = db_session.query(EmailVerification).filter_by(id_docente=doc.id_docente).count()
    r = client_no_auth.post("/api/auth/reenviar-verificacion", json={"email": "reenv@test.com"})
    assert r.status_code == 200
    tokens_despues = db_session.query(EmailVerification).filter_by(id_docente=doc.id_docente).count()
    assert tokens_despues == tokens_antes + 1


def test_reenviar_verificacion_email_desconocido_devuelve_200_sin_filtrar(client_no_auth):
    """
    Privacidad: no debemos exponer si un email está registrado o no.
    Devolvemos 200 con el mismo mensaje sea el caso que sea.
    """
    r = client_no_auth.post("/api/auth/reenviar-verificacion", json={"email": "no-existe@test.com"})
    assert r.status_code == 200
    body = r.json()
    # Mensaje genérico — no revela si el email existía
    assert "Si el correo" in body["mensaje"] or "si el correo" in body["mensaje"].lower()


def test_reenviar_verificacion_email_ya_verificado_no_crea_token(client_no_auth, db_session):
    """Si el docente ya está verificado, no debemos generar tokens nuevos."""
    from models import Docente, EmailVerification

    client_no_auth.post("/api/auth/register", json={
        "nombre_completo": "Ya", "email": "ya@test.com",
        "password": "supersegura", "consentimiento_datos": True,
    })
    doc = db_session.query(Docente).filter_by(email="ya@test.com").first()
    doc.email_verificado = True
    db_session.commit()

    tokens_antes = db_session.query(EmailVerification).filter_by(id_docente=doc.id_docente).count()
    r = client_no_auth.post("/api/auth/reenviar-verificacion", json={"email": "ya@test.com"})
    assert r.status_code == 200  # respuesta genérica igual
    tokens_despues = db_session.query(EmailVerification).filter_by(id_docente=doc.id_docente).count()
    assert tokens_despues == tokens_antes  # NO se creó token nuevo


# ═══════════════════════════════════════════════════════════════
# /api/auth/aceptar-consentimiento — grandfathered
# ═══════════════════════════════════════════════════════════════

def test_aceptar_consentimiento_grandfathered(client, db_session, seed_docente):
    """
    Docente grandfathered (consentimiento_datos=None) acepta la política.
    Después del POST: TRUE + fecha + IP.
    """
    docente = seed_docente["docente"]
    assert docente.consentimiento_datos is None  # estado grandfathered

    r = client.post("/api/auth/aceptar-consentimiento", json={"aceptado": True})
    assert r.status_code == 200
    body = r.json()
    assert body["consentimiento_datos"] is True

    db_session.refresh(docente)
    assert docente.consentimiento_datos is True
    assert docente.fecha_consentimiento is not None


def test_aceptar_consentimiento_rechazado_devuelve_400(client, seed_docente):
    """Enviar aceptado=False es rechazo — 400, no cambia estado."""
    r = client.post("/api/auth/aceptar-consentimiento", json={"aceptado": False})
    assert r.status_code == 400


def test_aceptar_consentimiento_requiere_auth(client_no_auth):
    """Sin token → 401."""
    r = client_no_auth.post("/api/auth/aceptar-consentimiento", json={"aceptado": True})
    assert r.status_code == 401
