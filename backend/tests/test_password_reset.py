"""
Sprint password-reset — recuperación de contraseña.

Mismo patrón que test_email_verification_consent.py:
- /api/auth/forgot-password no filtra si el email existe (privacidad).
- Token de 1h TTL, un solo uso.
- /api/auth/reset-password consume el token y cambia password_hash.
- Login con la contraseña vieja falla después del reset; con la nueva funciona.
"""
from __future__ import annotations

from datetime import datetime, timedelta


# ═══════════════════════════════════════════════════════════════
# email_service — provider inyectado (mismo contrato que verificación)
# ═══════════════════════════════════════════════════════════════

def test_enviar_correo_reset_password_acepta_provider_inyectado():
    from email_service import enviar_correo_reset_password

    class Doble:
        nombre = "doble"
        def __init__(self):
            self.llamadas = []
        def enviar(self, to_email, to_name, asunto, html, texto):
            self.llamadas.append({"to": to_email, "asunto": asunto, "texto": texto})
            return True

    doble = Doble()
    ok = enviar_correo_reset_password(
        "docente@test.com", "Docente Test",
        "https://app.example.com/nueva-password.html?token=XYZ",
        provider=doble,
    )
    assert ok is True
    assert len(doble.llamadas) == 1
    assert "XYZ" in doble.llamadas[0]["texto"]


# ═══════════════════════════════════════════════════════════════
# /api/auth/forgot-password
# ═══════════════════════════════════════════════════════════════

def test_forgot_password_email_existente_crea_token(client_no_auth, db_session, seed_docente):
    from models import PasswordResetToken

    r = client_no_auth.post("/api/auth/forgot-password", json={
        "email": seed_docente["docente"].email,
    })
    assert r.status_code == 200

    token_row = db_session.query(PasswordResetToken).filter_by(
        id_docente=seed_docente["docente"].id_docente
    ).first()
    assert token_row is not None
    assert token_row.token
    assert token_row.used_at is None
    delta = token_row.expires_at - datetime.utcnow()
    assert timedelta(minutes=50) < delta < timedelta(minutes=70)


def test_forgot_password_email_inexistente_no_filtra_y_no_crea_token(client_no_auth, db_session):
    """Contrato de privacidad: mismo 200 con mensaje genérico, sin token creado."""
    from models import PasswordResetToken

    r = client_no_auth.post("/api/auth/forgot-password", json={
        "email": "no-existe@test.com",
    })
    assert r.status_code == 200
    assert db_session.query(PasswordResetToken).count() == 0


# ═══════════════════════════════════════════════════════════════
# /api/auth/reset-password
# ═══════════════════════════════════════════════════════════════

def test_reset_password_con_token_valido_cambia_contrasena(client_no_auth, db_session, seed_docente):
    from models import PasswordResetToken
    from auth import verify_password

    client_no_auth.post("/api/auth/forgot-password", json={
        "email": seed_docente["docente"].email,
    })
    token_row = db_session.query(PasswordResetToken).filter_by(
        id_docente=seed_docente["docente"].id_docente
    ).first()

    r = client_no_auth.post(
        f"/api/auth/reset-password?token={token_row.token}",
        json={"password_nuevo": "nuevaClaveSegura123"},
    )
    assert r.status_code == 200

    db_session.refresh(seed_docente["docente"])
    assert verify_password("nuevaClaveSegura123", seed_docente["docente"].password_hash)
    assert not verify_password(seed_docente["password"], seed_docente["docente"].password_hash)

    db_session.refresh(token_row)
    assert token_row.used_at is not None


def test_reset_password_login_con_clave_vieja_falla_y_con_nueva_funciona(
    client_no_auth, db_session, seed_docente,
):
    from models import PasswordResetToken

    client_no_auth.post("/api/auth/forgot-password", json={
        "email": seed_docente["docente"].email,
    })
    token_row = db_session.query(PasswordResetToken).filter_by(
        id_docente=seed_docente["docente"].id_docente
    ).first()
    client_no_auth.post(
        f"/api/auth/reset-password?token={token_row.token}",
        json={"password_nuevo": "otraClaveNueva456"},
    )

    r_vieja = client_no_auth.post("/api/auth/login", data={
        "username": seed_docente["docente"].email,
        "password": seed_docente["password"],
    })
    assert r_vieja.status_code == 401

    r_nueva = client_no_auth.post("/api/auth/login", data={
        "username": seed_docente["docente"].email,
        "password": "otraClaveNueva456",
    })
    assert r_nueva.status_code == 200


def test_reset_password_token_usado_dos_veces_falla_la_segunda(
    client_no_auth, db_session, seed_docente,
):
    from models import PasswordResetToken

    client_no_auth.post("/api/auth/forgot-password", json={
        "email": seed_docente["docente"].email,
    })
    token_row = db_session.query(PasswordResetToken).filter_by(
        id_docente=seed_docente["docente"].id_docente
    ).first()

    r1 = client_no_auth.post(
        f"/api/auth/reset-password?token={token_row.token}",
        json={"password_nuevo": "primeraClave123"},
    )
    assert r1.status_code == 200

    r2 = client_no_auth.post(
        f"/api/auth/reset-password?token={token_row.token}",
        json={"password_nuevo": "segundaClave456"},
    )
    assert r2.status_code == 404


def test_reset_password_token_expirado_devuelve_410(client_no_auth, db_session, seed_docente):
    from models import PasswordResetToken

    expirado = PasswordResetToken(
        id_docente=seed_docente["docente"].id_docente,
        token="token-viejo-expirado",
        expires_at=datetime.utcnow() - timedelta(hours=1),
    )
    db_session.add(expirado)
    db_session.commit()

    r = client_no_auth.post(
        "/api/auth/reset-password?token=token-viejo-expirado",
        json={"password_nuevo": "nuevaClave789"},
    )
    assert r.status_code == 410
    assert "token_expirado" in r.text


def test_reset_password_token_inexistente_devuelve_404(client_no_auth):
    r = client_no_auth.post(
        "/api/auth/reset-password?token=no-existe-xxx",
        json={"password_nuevo": "cualquierClave"},
    )
    assert r.status_code == 404
