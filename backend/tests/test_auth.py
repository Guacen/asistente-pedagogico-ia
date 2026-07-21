"""
Tests del endpoint de autenticación:
- Login válido → 200 + token + docente en respuesta
- Password incorrecta → 401
- Email inexistente → 401
- Registro nuevo (idempotencia + no duplicados)
- Token expirado → 401
- Token malformado → 401
- GET /me sin token → 401
- GET /me con token válido → 200
"""
from __future__ import annotations

from datetime import datetime, timedelta

from jose import jwt


def _login(client, username, password):
    return client.post(
        "/api/auth/login",
        data={"username": username, "password": password},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )


# ─── LOGIN ────────────────────────────────────────────────────────────────

def test_login_valido_devuelve_token_y_docente(client_no_auth, seed_docente):
    r = _login(client_no_auth, seed_docente["docente"].email, seed_docente["password"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert "access_token" in body
    assert body["token_type"] == "bearer"
    assert body["docente"]["email"] == seed_docente["docente"].email
    assert body["docente"]["nombre_completo"] == seed_docente["docente"].nombre_completo
    # No debe filtrar el password_hash
    assert "password_hash" not in body["docente"]


def test_login_password_incorrecta_devuelve_401(client_no_auth, seed_docente):
    r = _login(client_no_auth, seed_docente["docente"].email, "wrong-password")
    assert r.status_code == 401
    assert "access_token" not in r.text


def test_login_email_inexistente_devuelve_401(client_no_auth):
    r = _login(client_no_auth, "no-existe@test.com", "cualquiera")
    assert r.status_code == 401


# ─── /me ──────────────────────────────────────────────────────────────────

def test_get_me_sin_token_devuelve_401(client_no_auth):
    r = client_no_auth.get("/api/auth/me")
    assert r.status_code == 401


def test_get_me_con_token_valido_devuelve_docente(client_no_auth, seed_docente):
    r_login = _login(client_no_auth, seed_docente["docente"].email, seed_docente["password"])
    token = r_login.json()["access_token"]
    r = client_no_auth.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    assert r.json()["email"] == seed_docente["docente"].email


def test_get_me_con_token_malformado_devuelve_401(client_no_auth):
    r = client_no_auth.get(
        "/api/auth/me",
        headers={"Authorization": "Bearer no-es-un-jwt-valido"},
    )
    assert r.status_code == 401


def test_get_me_con_token_expirado_devuelve_401(client_no_auth, seed_docente):
    """Genera un JWT con exp en el pasado y verifica que el backend lo rechace."""
    from config import settings
    payload = {
        "sub": seed_docente["docente"].id_docente,
        "exp": datetime.utcnow() - timedelta(hours=1),
    }
    expired_token = jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    r = client_no_auth.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {expired_token}"},
    )
    assert r.status_code == 401


def test_get_me_con_docente_id_inexistente_devuelve_401(client_no_auth):
    """
    Un token válidamente firmado pero cuyo sub no corresponde a un docente
    real de la DB debe rechazarse (defensa contra tokens de docentes borrados).
    """
    from config import settings
    payload = {
        "sub": "00000000-0000-0000-0000-000000000000",  # UUID que no existe
        "exp": datetime.utcnow() + timedelta(hours=1),
    }
    token = jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    r = client_no_auth.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 401


# ─── REGISTRO ─────────────────────────────────────────────────────────────

def test_registro_nuevo_docente(client_no_auth):
    r = client_no_auth.post("/api/auth/register", json={
        "nombre_completo": "Nuevo Docente",
        "email": "nuevo@test.com",
        "password": "supersegura",
    })
    assert r.status_code in (200, 201), r.text
    # Ahora puede loguearse
    r_login = _login(client_no_auth, "nuevo@test.com", "supersegura")
    assert r_login.status_code == 200


def test_registro_con_email_duplicado_falla(client_no_auth, seed_docente):
    r = client_no_auth.post("/api/auth/register", json={
        "nombre_completo": "Otro Docente",
        "email": seed_docente["docente"].email,  # ya existe
        "password": "cualquiera",
    })
    assert r.status_code >= 400, f"Debería fallar por email duplicado, obtuvo {r.status_code}"
