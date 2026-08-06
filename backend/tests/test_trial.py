"""
Sprint trial-7-dias — prueba gratuita self-service sin tarjeta.

Cubre lo pedido en la Tarea 8 del sprint:
- Registro crea docente con trial_ends_at = now()+7d.
- Trial activo: request pasa normalmente (y trae X-Trial-Days-Left).
- Trial expirado: 402 con detail="trial_expirado" (y auto-flip a plan='expirado').
- plan='activo' (legacy/pago) nunca se bloquea aunque trial_ends_at sea NULL.

`GET /api/grupos` se usa como endpoint representativo "de producto"
(gateado por verify_trial_active) — no importa cuál, sólo el status code.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from config import settings
from models import Docente


def test_registro_crea_docente_con_trial_7_dias(client_no_auth):
    r = client_no_auth.post("/api/auth/register", json={
        "nombre_completo": "Docente Nuevo",
        "email": "nuevo-trial@test.com",
        "password": "clave1234",
        "consentimiento_datos": True,
    })
    assert r.status_code == 201
    body = r.json()
    docente = body["docente"]

    assert docente["plan"] == "trial"
    assert docente["trial_ends_at"] is not None
    assert docente["dias_restantes"] == settings.TRIAL_DIAS

    vencimiento = datetime.fromisoformat(docente["trial_ends_at"])
    esperado = datetime.utcnow() + timedelta(days=settings.TRIAL_DIAS)
    # Tolerancia por el tiempo que tarda la request — no comparamos exacto.
    assert abs((vencimiento - esperado).total_seconds()) < 30


def test_trial_activo_deja_pasar_y_manda_header_dias_restantes(client, seed_docente, db_session):
    docente = seed_docente["docente"]
    docente.plan = "trial"
    docente.trial_ends_at = datetime.utcnow() + timedelta(days=5)
    db_session.commit()

    r = client.get("/api/grupos")
    assert r.status_code == 200
    assert r.headers.get("x-trial-days-left") == "5"


def test_trial_vencido_devuelve_402(client, seed_docente, db_session):
    docente = seed_docente["docente"]
    docente.plan = "trial"
    docente.trial_ends_at = datetime.utcnow() - timedelta(days=1)
    db_session.commit()

    r = client.get("/api/grupos")
    assert r.status_code == 402
    assert r.json()["detail"] == "trial_expirado"

    # Efecto lateral: el plan quedó marcado como 'expirado' en DB.
    db_session.refresh(docente)
    assert docente.plan == "expirado"


def test_plan_expirado_sigue_bloqueado_aunque_trial_ends_at_sea_futuro(client, seed_docente, db_session):
    """
    Una vez que el plan pasó a 'expirado' (p.ej. por el auto-flip de
    arriba), queda bloqueado aunque alguien manipule trial_ends_at a
    futuro sin volver a poner plan='trial' — el estado 'expirado' manda.
    """
    docente = seed_docente["docente"]
    docente.plan = "expirado"
    docente.trial_ends_at = datetime.utcnow() + timedelta(days=5)
    db_session.commit()

    r = client.get("/api/grupos")
    assert r.status_code == 402
    assert r.json()["detail"] == "trial_expirado"


def test_plan_activo_nunca_se_bloquea_aunque_trial_ends_at_sea_null(client, seed_docente, db_session):
    docente = seed_docente["docente"]
    docente.plan = "activo"
    docente.trial_ends_at = None
    db_session.commit()

    r = client.get("/api/grupos")
    assert r.status_code == 200
    # Sin trial, no debe venir el header de días restantes.
    assert "x-trial-days-left" not in r.headers


def test_plan_activo_con_trial_ends_at_vencido_tampoco_se_bloquea(client, seed_docente, db_session):
    """plan='activo' manda por encima de cualquier valor de trial_ends_at."""
    docente = seed_docente["docente"]
    docente.plan = "activo"
    docente.trial_ends_at = datetime.utcnow() - timedelta(days=100)
    db_session.commit()

    r = client.get("/api/grupos")
    assert r.status_code == 200


def test_endpoint_perfil_plan_funciona_incluso_con_trial_vencido(client, seed_docente, db_session):
    """
    /api/perfil/plan es la excepción explícita del sprint — debe
    responder 200 con expirado=true en vez de 402, para que el frontend
    pueda enterarse y redirigir a la pantalla de bloqueo.
    """
    docente = seed_docente["docente"]
    docente.plan = "trial"
    docente.trial_ends_at = datetime.utcnow() - timedelta(days=1)
    db_session.commit()

    r = client.get("/api/perfil/plan")
    assert r.status_code == 200
    body = r.json()
    assert body["expirado"] is True
    assert body["dias_restantes"] == 0


def test_endpoint_suscripciones_no_se_bloquea_con_trial_vencido(client, seed_docente, db_session):
    """
    Un docente con trial vencido debe poder seguir viendo /suscripciones
    para poder pagar y reactivarse — si esto también diera 402, quedaría
    sin salida dentro de la app.
    """
    docente = seed_docente["docente"]
    docente.plan = "trial"
    docente.trial_ends_at = datetime.utcnow() - timedelta(days=1)
    db_session.commit()

    r = client.get("/api/suscripciones/mi-suscripcion")
    assert r.status_code == 200
