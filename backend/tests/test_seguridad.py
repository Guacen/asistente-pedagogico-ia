"""
Sprint seguridad-avanzada — cobertura de las protecciones nuevas:
- Rate limiting en /api/auth/login (5/15min por IP).
- Logout blacklistea el access token — 401 en el siguiente request.
- Sanitización de inputs (XSS) en campos de texto libre.
- CORS rechaza orígenes no permitidos.
- Política de contraseñas rechaza contraseñas débiles con 422.
"""
from __future__ import annotations


def _login(client, username, password):
    return client.post(
        "/api/auth/login",
        data={"username": username, "password": password},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )


# ─── TAREA 3 — Rate limiting ────────────────────────────────────────────────

def test_rate_limit_login(client_no_auth):
    """6 intentos de login (aunque las credenciales sean inválidas) →
    el 6to debe ser bloqueado con 429 y header Retry-After."""
    for _ in range(5):
        r = _login(client_no_auth, "nadie@test.com", "wrong-password")
        assert r.status_code == 401

    r = _login(client_no_auth, "nadie@test.com", "wrong-password")
    assert r.status_code == 429
    assert "retry-after" in {k.lower() for k in r.headers.keys()}


# ─── TAREA 2 — logout blacklistea el token ──────────────────────────────────

def test_logout_blacklist(client_no_auth, seed_docente):
    r_login = _login(client_no_auth, seed_docente["docente"].email, seed_docente["password"])
    assert r_login.status_code == 200, r_login.text
    token = r_login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # El token funciona antes de logout.
    r_me = client_no_auth.get("/api/auth/me", headers=headers)
    assert r_me.status_code == 200

    r_logout = client_no_auth.post("/api/auth/logout", headers=headers)
    assert r_logout.status_code == 200, r_logout.text

    # El MISMO token ya no debe servir.
    r_me_2 = client_no_auth.get("/api/auth/me", headers=headers)
    assert r_me_2.status_code == 401


# ─── TAREA 4 — sanitización XSS ─────────────────────────────────────────────

def test_xss_input(client):
    """Un nombre de grupo con <script> debe guardarse sin la etiqueta."""
    r = client.post("/api/grupos", json={
        "nombre_grupo": "<script>alert(1)</script>Mi Grupo",
        "grado": "8°",
        "asignatura": "matematicas",
        "anio_lectivo": 2026,
        "cantidad_estudiantes": 10,
    })
    assert r.status_code == 201, r.text
    nombre_guardado = r.json()["nombre_grupo"]
    assert "<script>" not in nombre_guardado
    assert "alert(1)" not in nombre_guardado or "<" not in nombre_guardado
    assert "Mi Grupo" in nombre_guardado


# ─── TAREA 5 — CORS restrictivo ─────────────────────────────────────────────

def test_cors_rejected(client_no_auth):
    """Preflight desde un origen no permitido debe ser rechazado."""
    r = client_no_auth.options(
        "/api/auth/login",
        headers={
            "Origin": "https://evil-sitio-no-permitido.com",
            "Access-Control-Request-Method": "POST",
        },
    )
    # Starlette's CORSMiddleware devuelve 400 en el preflight cuando el
    # origen no está en la whitelist, y en cualquier caso NUNCA debe
    # reflejar el origen en Access-Control-Allow-Origin.
    assert r.headers.get("access-control-allow-origin") != "https://evil-sitio-no-permitido.com"
    assert r.status_code == 400 or "access-control-allow-origin" not in {
        k.lower() for k in r.headers.keys()
    }


# ─── TAREA 6 — política de contraseñas ──────────────────────────────────────

def test_password_weak(client_no_auth):
    r = client_no_auth.post("/api/auth/register", json={
        "nombre_completo": "Docente Débil",
        "email": "debil@test.com",
        "password": "abcdefgh",  # sin mayúscula ni número
        "consentimiento_datos": True,
    })
    assert r.status_code == 422, r.text
    body = r.json()
    assert "detail" in body
