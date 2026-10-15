"""
Sprint H, Parte A/C — acceso beta por código de invitación.

Cubre:
- Un código inválido, vencido o agotado NUNCA otorga plan='beta' — el
  registro se rechaza entero, no cae en silencio a trial normal.
- Un código válido otorga plan='beta', copia beta_vencimiento tal cual
  estaba el día del registro, e incrementa usos_actuales atómicamente.
- /api/suscripciones/mi-suscripcion reporta plan='beta' con los límites
  de config.LIMITES_PLAN["beta"] — es el dato real del que depende que
  dashboard.html/cuenta.html oculten el upgrade (verificación
  obligatoria #1: "un plan='beta' no ve ningún elemento de upgrade").
- /api/perfil/plan NUNCA marca expirado=True para un docente beta, ni
  siquiera con la beta vencida — eso es lo que evita el redirect al
  muro de trial-expirado.html (pensado para el embudo de pago, Wompi
  sigue en sandbox).
- Beta vencida: GET sigue pasando (lectura), escritura (POST) se
  bloquea con 403 code="beta_vencida" — nunca un 402 ni "elige un plan".
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from auth import get_current_docente, hash_password
from config import LIMITES_PLAN
from database import get_db
from models import CodigoInvitacion, Docente


def _client_como(app, db_session, docente):
    def _override_get_db():
        try:
            yield db_session
        finally:
            pass
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_docente] = lambda: docente
    return TestClient(app)


@pytest.fixture
def client_fresh_factory(db_session):
    """
    Factory para crear un docente a medida (plan/beta_vencimiento/lo
    que haga falta) ya autenticado contra un TestClient, sin pasar por
    el flujo real de login/JWT — mismo patrón que
    test_admin_reset_limites.py::_client_como, parametrizado.
    """
    from main import app

    contador = {"n": 0}

    def _factory(**overrides):
        contador["n"] += 1
        docente = Docente(
            nombre_completo="Docente Beta",
            email=f"beta-factory-{contador['n']}@test.com",
            password_hash=hash_password("x"),
            plan="beta",
        )
        for campo, valor in overrides.items():
            setattr(docente, campo, valor)
        db_session.add(docente)
        db_session.commit()
        db_session.refresh(docente)
        return _client_como(app, db_session, docente), docente

    yield _factory
    app.dependency_overrides.clear()


def _crear_codigo(db_session, **kwargs):
    defaults = dict(
        codigo="PILOTO-TEST",
        fecha_expiracion=datetime.utcnow() + timedelta(days=30),
        fecha_vencimiento_beta=datetime.utcnow() + timedelta(days=90),
        usos_maximos=1,
        usos_actuales=0,
        activo=True,
    )
    defaults.update(kwargs)
    codigo = CodigoInvitacion(**defaults)
    db_session.add(codigo)
    db_session.commit()
    return codigo


def _payload_registro(email: str, codigo: str | None = None) -> dict:
    payload = {
        "nombre_completo": "Docente Piloto",
        "email": email,
        "password": "Password123!",
        "consentimiento_datos": True,
    }
    if codigo is not None:
        payload["codigo_invitacion"] = codigo
    return payload


# ─── Código inválido/vencido/agotado NUNCA otorga beta ─────────────────

def test_codigo_inexistente_rechaza_el_registro(client_no_auth, db_session):
    r = client_no_auth.post(
        "/api/auth/register",
        json=_payload_registro("sin-codigo-valido@test.com", "NO-EXISTE"),
    )
    assert r.status_code == 400
    assert db_session.query(Docente).filter_by(email="sin-codigo-valido@test.com").first() is None


def test_codigo_vencido_rechaza_el_registro(client_no_auth, db_session):
    _crear_codigo(
        db_session, codigo="VENCIDO",
        fecha_expiracion=datetime.utcnow() - timedelta(days=1),
    )
    r = client_no_auth.post(
        "/api/auth/register",
        json=_payload_registro("codigo-vencido@test.com", "VENCIDO"),
    )
    assert r.status_code == 400
    assert db_session.query(Docente).filter_by(email="codigo-vencido@test.com").first() is None


def test_codigo_agotado_rechaza_el_registro(client_no_auth, db_session):
    _crear_codigo(db_session, codigo="AGOTADO", usos_maximos=1, usos_actuales=1)
    r = client_no_auth.post(
        "/api/auth/register",
        json=_payload_registro("codigo-agotado@test.com", "AGOTADO"),
    )
    assert r.status_code == 400
    assert db_session.query(Docente).filter_by(email="codigo-agotado@test.com").first() is None


def test_codigo_desactivado_rechaza_el_registro(client_no_auth, db_session):
    _crear_codigo(db_session, codigo="INACTIVO", activo=False)
    r = client_no_auth.post(
        "/api/auth/register",
        json=_payload_registro("codigo-inactivo@test.com", "INACTIVO"),
    )
    assert r.status_code == 400
    assert db_session.query(Docente).filter_by(email="codigo-inactivo@test.com").first() is None


# ─── Código válido SÍ otorga beta, correctamente ────────────────────────

def test_codigo_valido_otorga_plan_beta(client_no_auth, db_session):
    vencimiento = datetime.utcnow() + timedelta(days=90)
    _crear_codigo(db_session, codigo="VALIDO1", fecha_vencimiento_beta=vencimiento)

    r = client_no_auth.post(
        "/api/auth/register",
        json=_payload_registro("codigo-valido@test.com", "valido1"),  # minúsculas a propósito
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["docente"]["plan"] == "beta"

    docente = db_session.query(Docente).filter_by(email="codigo-valido@test.com").first()
    assert docente is not None
    assert docente.plan == "beta"
    assert docente.trial_ends_at is None
    assert docente.beta_vencimiento is not None

    codigo = db_session.query(CodigoInvitacion).filter_by(codigo="VALIDO1").first()
    assert codigo.usos_actuales == 1


def test_registro_sin_codigo_sigue_siendo_trial_normal(client_no_auth, db_session):
    """Sanity check: el flujo sin código no cambió."""
    r = client_no_auth.post(
        "/api/auth/register",
        json=_payload_registro("sin-codigo-del-todo@test.com"),
    )
    assert r.status_code == 201, r.text
    assert r.json()["docente"]["plan"] == "trial"


# ─── Verificación obligatoria #1: beta nunca ve upgrade/Wompi ──────────

def test_beta_reporta_plan_beta_en_mi_suscripcion(client_fresh_factory):
    """
    /api/suscripciones/mi-suscripcion es el dato real del que dependen
    dashboard.html (sidebar) y cuenta.html (pestaña suscripción) para
    decidir si muestran el botón de upgrade. Si esto reporta 'beta' con
    los límites correctos, el resto de la UI (ya verificada a mano) se
    apoya en un dato correcto — y nunca en 'free', que dispararía el
    branch de upgrade.
    """
    client, docente = client_fresh_factory(plan="beta")
    r = client.get("/api/suscripciones/mi-suscripcion")
    assert r.status_code == 200
    body = r.json()
    assert body["plan"] == "beta"
    assert body["mensajes_limite_mes"] == LIMITES_PLAN["beta"]["mensajes"]
    assert body["grupos_limite"] == LIMITES_PLAN["beta"]["grupos"]


def test_perfil_plan_nunca_expirado_true_para_beta_vencida(client_fresh_factory):
    """
    expirado=True dispara el redirect de página completa a
    trial-expirado.html (pensado para el embudo de pago) — una beta
    vencida NUNCA debe disparar eso (Parte C: conserva lectura/
    exportación). beta_vencida es la señal aparte, no bloqueante.
    """
    client, docente = client_fresh_factory(
        plan="beta", beta_vencimiento=datetime.utcnow() - timedelta(days=1),
    )
    r = client.get("/api/perfil/plan")
    assert r.status_code == 200
    body = r.json()
    assert body["expirado"] is False
    assert body["beta_vencida"] is True
    assert body["plan"] == "beta"


def test_perfil_plan_beta_vigente_no_marca_vencida(client_fresh_factory):
    client, docente = client_fresh_factory(
        plan="beta", beta_vencimiento=datetime.utcnow() + timedelta(days=30),
    )
    r = client.get("/api/perfil/plan")
    body = r.json()
    assert body["expirado"] is False
    assert body["beta_vencida"] is False
    assert body["dias_restantes_beta"] > 0


# ─── Beta vencida: lectura sigue, escritura se bloquea (Parte C) ───────

def test_beta_vencida_permite_lectura(client_fresh_factory):
    client, docente = client_fresh_factory(
        plan="beta", beta_vencimiento=datetime.utcnow() - timedelta(days=1),
    )
    r = client.get("/api/grupos")
    assert r.status_code == 200


def test_beta_vencida_bloquea_escritura_con_403_no_402(client_fresh_factory):
    client, docente = client_fresh_factory(
        plan="beta", beta_vencimiento=datetime.utcnow() - timedelta(days=1),
    )
    r = client.post("/api/grupos", json={
        "nombre_grupo": "Grupo nuevo", "grado": "5", "asignatura": "Matematicas",
        "anio_lectivo": 2026, "periodo_actual": 1, "cantidad_estudiantes": 20,
    })
    assert r.status_code == 403
    detail = r.json()["detail"]
    assert detail["code"] == "beta_vencida"


def test_beta_vigente_permite_escritura(client_fresh_factory):
    client, docente = client_fresh_factory(
        plan="beta", beta_vencimiento=datetime.utcnow() + timedelta(days=30),
    )
    r = client.post("/api/grupos", json={
        "nombre_grupo": "Grupo nuevo", "grado": "5", "asignatura": "Matematicas",
        "anio_lectivo": 2026, "periodo_actual": 1, "cantidad_estudiantes": 20,
    })
    assert r.status_code == 201


# ─── Análisis estático: el código que oculta upgrade/Wompi sigue ahí ──
# Complementa los tests de arriba (que prueban el DATO del que depende
# la UI) con una verificación directa de que el código fuente todavía
# tiene la rama que oculta esos elementos — mismo estilo que
# test_frontend_css_fallbacks.py (análisis de texto, sin navegador).
# Si alguien borra `esBeta`/`beta-section` en un cambio futuro, esto lo
# atrapa aunque el dato del backend siga siendo correcto.

from pathlib import Path  # noqa: E402

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


def _leer_frontend(nombre: str) -> str:
    ruta = FRONTEND_DIR / nombre
    assert ruta.exists(), f"{nombre} no existe en {FRONTEND_DIR}"
    return ruta.read_text(encoding="utf-8")


def test_dashboard_oculta_upgrade_link_para_beta():
    html = _leer_frontend("dashboard.html")
    assert "esBeta" in html, "dashboard.html perdió la rama de plan beta en renderPlan()"
    assert "upg.classList.add('hidden')" in html


def test_cuenta_oculta_upgrade_section_para_beta():
    html = _leer_frontend("cuenta.html")
    assert "esBeta" in html, "cuenta.html perdió la rama de plan beta en renderSuscripcion()"
    assert "'upgrade-section'" in html and "esPro || esBeta" in html


def test_chat_no_redirige_a_pantalla_de_pago_en_beta_vencida():
    html = _leer_frontend("chat.html")
    assert "beta_vencida" in html, "chat.html perdió el manejo de code=beta_vencida"
    # El bloque de trial_expirado SÍ redirige — confirmamos que el de
    # beta_vencida está en un bloque separado que NO llama a
    # window.location.href hacia trial-expirado.html.
    idx = html.index("'beta_vencida'")
    bloque = html[idx:idx + 300]
    assert "trial-expirado.html" not in bloque
