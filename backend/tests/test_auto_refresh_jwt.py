"""
Sprint auto-refresh-jwt-frontend — P0 de la auditoría: el access token
dura 60 minutos y requireAuth() desloguea sin intentar refrescar. La
orquestación de reintento/dedup vive en frontend/js/api.js (ver
tests/js/test_api_refresh.js — no es Python, no puede probarse acá) y
frontend/js/auth.js. Este archivo cubre la parte que SÍ vive en el
backend: el contrato real de /api/auth/refresh y /api/auth/logout que
esa orquestación necesita para funcionar bien.

Cubre:
- /refresh no rota el refresh_token (ya lo garantizaba el código, se
  confirma con test explícito — la orquestación del frontend depende
  de que llamar refresh varias veces con el mismo token no lo invalide).
- /refresh con un refresh_token blacklisteado (revocado) → 401, nunca
  emite un access token nuevo.
- /refresh no blacklistea NADA — un access token emitido antes del
  refresh sigue siendo válido después (dos sesiones/pestañas no se
  pisan entre sí).
- /logout con refresh_token en el body blacklistea AMBOS — el
  siguiente /refresh con ese mismo refresh_token ya no funciona.
- /logout sin refresh_token en el body (clientes viejos, o el request
  best-effort falla a mitad) sigue blacklisteando el access token igual
  — nunca bloquea el logout por el campo opcional.
- Un refresh_token con formato inválido en el body de /logout no rompe
  el logout del access token (best-effort, nunca lanza 500).
"""
from __future__ import annotations


def _login(client, username, password):
    return client.post(
        "/api/auth/login",
        data={"username": username, "password": password},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )


def test_refresh_no_rota_el_refresh_token(client_no_auth, seed_docente):
    r_login = _login(client_no_auth, seed_docente["docente"].email, seed_docente["password"])
    refresh_token = r_login.json()["refresh_token"]

    r1 = client_no_auth.post("/api/auth/refresh", json={"refresh_token": refresh_token})
    assert r1.status_code == 200, r1.text
    assert r1.json()["refresh_token"] == refresh_token

    # Reusar el MISMO refresh_token una segunda vez debe seguir sirviendo
    # — la orquestación del frontend (varias pestañas, requireAuth +
    # 401 reactivo) puede terminar llamando /refresh más de una vez con
    # el mismo token guardado en localStorage.
    r2 = client_no_auth.post("/api/auth/refresh", json={"refresh_token": refresh_token})
    assert r2.status_code == 200, r2.text
    assert r2.json()["refresh_token"] == refresh_token


def test_refresh_con_token_revocado_devuelve_401(client_no_auth, seed_docente, db_session):
    from models import TokenBlacklist
    from jose import jwt
    from config import settings

    r_login = _login(client_no_auth, seed_docente["docente"].email, seed_docente["password"])
    refresh_token = r_login.json()["refresh_token"]
    payload = jwt.decode(refresh_token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])

    db_session.add(TokenBlacklist(
        jti=payload["jti"],
        expires_at=__import__("datetime").datetime.utcfromtimestamp(payload["exp"]),
    ))
    db_session.commit()

    r = client_no_auth.post("/api/auth/refresh", json={"refresh_token": refresh_token})
    assert r.status_code == 401


def test_refresh_no_invalida_un_access_token_vigente(client_no_auth, seed_docente):
    """Dos pestañas del mismo docente: una sigue usando su access token
    viejo (todavía no vencido) mientras la otra pide uno nuevo — el
    refresh de la segunda NO debe afectar a la primera."""
    r_login = _login(client_no_auth, seed_docente["docente"].email, seed_docente["password"])
    access_token_original = r_login.json()["access_token"]
    refresh_token = r_login.json()["refresh_token"]
    headers_originales = {"Authorization": f"Bearer {access_token_original}"}

    # El access token original funciona antes del refresh.
    assert client_no_auth.get("/api/auth/me", headers=headers_originales).status_code == 200

    r_refresh = client_no_auth.post("/api/auth/refresh", json={"refresh_token": refresh_token})
    assert r_refresh.status_code == 200, r_refresh.text

    # Y sigue funcionando DESPUÉS — /refresh nunca blacklistea el access
    # token con el que se lo llamó, ni ningún otro.
    assert client_no_auth.get("/api/auth/me", headers=headers_originales).status_code == 200


def test_logout_con_refresh_token_blacklistea_ambos(client_no_auth, seed_docente):
    r_login = _login(client_no_auth, seed_docente["docente"].email, seed_docente["password"])
    access_token = r_login.json()["access_token"]
    refresh_token = r_login.json()["refresh_token"]
    headers = {"Authorization": f"Bearer {access_token}"}

    r_logout = client_no_auth.post(
        "/api/auth/logout", headers=headers, json={"refresh_token": refresh_token},
    )
    assert r_logout.status_code == 200, r_logout.text

    # El access token ya no sirve (comportamiento pre-existente).
    assert client_no_auth.get("/api/auth/me", headers=headers).status_code == 401

    # Y AHORA el refresh_token tampoco — antes de este sprint, éste era
    # el hueco: "el refresh token asociado sigue vivo".
    r_refresh = client_no_auth.post("/api/auth/refresh", json={"refresh_token": refresh_token})
    assert r_refresh.status_code == 401, (
        "logout debe invalidar también el refresh_token, no sólo el access token"
    )


def test_logout_sin_refresh_token_en_el_body_sigue_funcionando(client_no_auth, seed_docente):
    """Compat: un cliente que no mande refresh_token (versión vieja del
    frontend, o el best-effort simplemente no lo incluyó) igual debe
    poder cerrar sesión del access token — el campo es opcional."""
    r_login = _login(client_no_auth, seed_docente["docente"].email, seed_docente["password"])
    access_token = r_login.json()["access_token"]
    headers = {"Authorization": f"Bearer {access_token}"}

    r_logout = client_no_auth.post("/api/auth/logout", headers=headers)
    assert r_logout.status_code == 200, r_logout.text
    assert client_no_auth.get("/api/auth/me", headers=headers).status_code == 401


def test_logout_con_refresh_token_invalido_no_rompe_el_logout(client_no_auth, seed_docente):
    """Un refresh_token con formato basura en el body no debe tumbar el
    logout del access token — best-effort, nunca 500."""
    r_login = _login(client_no_auth, seed_docente["docente"].email, seed_docente["password"])
    access_token = r_login.json()["access_token"]
    headers = {"Authorization": f"Bearer {access_token}"}

    r_logout = client_no_auth.post(
        "/api/auth/logout", headers=headers, json={"refresh_token": "esto-no-es-un-jwt"},
    )
    assert r_logout.status_code == 200, r_logout.text
    assert client_no_auth.get("/api/auth/me", headers=headers).status_code == 401


def test_logout_con_access_token_como_refresh_token_no_lo_blacklistea_dos_veces_por_error(
    client_no_auth, seed_docente,
):
    """Si por error el body de /logout trae un access_token en vez de un
    refresh_token, el chequeo type == 'refresh' evita blacklistear un
    jti con semántica equivocada silenciosamente — igual el logout no
    debe romperse."""
    r_login = _login(client_no_auth, seed_docente["docente"].email, seed_docente["password"])
    access_token = r_login.json()["access_token"]
    headers = {"Authorization": f"Bearer {access_token}"}

    r_logout = client_no_auth.post(
        "/api/auth/logout", headers=headers, json={"refresh_token": access_token},
    )
    assert r_logout.status_code == 200, r_logout.text
