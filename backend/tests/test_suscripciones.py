"""
Sprint stripe-colombia — cobertura del módulo de pagos (antes sin tests).

Toda llamada real a la red de Stripe está mockeada con unittest.mock:
- stripe.checkout.Session.create
- stripe.Customer.create
- stripe.Webhook.construct_event

No se testea contra la API real de Stripe ni se necesitan credenciales.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from config import settings
from models import Suscripcion


def test_mi_suscripcion_free_devuelve_limites_correctos(client, seed_docente):
    """Docente recién sembrado no tiene Suscripcion — plan free por default."""
    r = client.get("/api/suscripciones/mi-suscripcion")
    assert r.status_code == 200
    body = r.json()
    assert body["plan"] == "free"
    assert body["mensajes_limite_mes"] == 10
    assert body["grupos_limite"] == 1


def test_usuario_sin_suscripcion_tiene_plan_free_por_defecto(client, seed_docente, db_session):
    """Sin fila en `suscripciones`, el endpoint no debe romper — cae a free."""
    assert seed_docente["docente"].suscripcion is None

    r = client.get("/api/suscripciones/mi-suscripcion")
    assert r.status_code == 200
    assert r.json()["plan"] == "free"
    assert r.json()["estado"] == "activa"


def test_checkout_crea_session_con_currency_cop(client, seed_docente, monkeypatch):
    """
    El checkout usa el Price ID en COP correspondiente al plan pedido —
    la moneda la fija ese Price en el Dashboard de Stripe, no se pasa
    `currency` en la Session (Stripe la rechaza si se combina con un
    Price ID existente).
    """
    import suscripciones

    monkeypatch.setattr(settings, "STRIPE_SECRET_KEY", "sk_test_dummy")
    monkeypatch.setattr(settings, "STRIPE_PRICE_ID_PRO_COP", "price_pro_cop_123")

    fake_customer = MagicMock(id="cus_123")
    fake_session = MagicMock(url="https://checkout.stripe.com/pay/cs_123", id="cs_123")

    with patch.object(suscripciones.stripe.Customer, "create", return_value=fake_customer) as mock_customer, \
         patch.object(suscripciones.stripe.checkout.Session, "create", return_value=fake_session) as mock_session:

        r = client.post("/api/suscripciones/checkout", json={
            "plan": "pro",
            "success_url": "https://app.example.com/ok",
            "cancel_url": "https://app.example.com/cancel",
        })

    assert r.status_code == 200
    assert r.json()["checkout_url"] == "https://checkout.stripe.com/pay/cs_123"

    mock_customer.assert_called_once()
    kwargs = mock_session.call_args.kwargs
    assert kwargs["line_items"] == [{"price": "price_pro_cop_123", "quantity": 1}]
    assert "pse" in kwargs["payment_method_types"]
    assert "nequi" in kwargs["payment_method_types"]
    assert kwargs["payment_method_options"]["pse"] == {"setup_future_usage": "none"}
    assert kwargs["locale"] == "es"
    assert "currency" not in kwargs


def test_checkout_sin_price_id_configurado_devuelve_503(client, seed_docente, monkeypatch):
    monkeypatch.setattr(settings, "STRIPE_SECRET_KEY", "sk_test_dummy")
    monkeypatch.setattr(settings, "STRIPE_PRICE_ID_PRO_COP", "")

    r = client.post("/api/suscripciones/checkout", json={
        "plan": "pro",
        "success_url": "https://app.example.com/ok",
        "cancel_url": "https://app.example.com/cancel",
    })
    assert r.status_code == 503


def test_webhook_checkout_completado_activa_plan_pro(client, seed_docente, db_session, monkeypatch):
    import suscripciones

    monkeypatch.setattr(settings, "STRIPE_WEBHOOK_SECRET", "whsec_dummy")

    suscripcion = Suscripcion(id_docente=seed_docente["docente"].id_docente, plan="free")
    db_session.add(suscripcion)
    db_session.commit()

    fake_event = {
        "type": "checkout.session.completed",
        "data": {"object": {
            "metadata": {"docente_id": seed_docente["docente"].id_docente},
            "subscription": "sub_activa_123",
        }},
    }

    with patch.object(suscripciones.stripe.Webhook, "construct_event", return_value=fake_event):
        r = client.post(
            "/webhook/stripe",
            content=b"{}",
            headers={"stripe-signature": "t=1,v1=fake"},
        )

    assert r.status_code == 200
    db_session.refresh(suscripcion)
    assert suscripcion.plan == "pro"
    assert suscripcion.estado == "activa"
    assert suscripcion.stripe_subscription_id == "sub_activa_123"


def test_webhook_checkout_completado_desbloquea_trial_vencido(client, seed_docente, db_session, monkeypatch):
    """
    Bonus fix (bundleado con el sprint wompi-pagos): un docente con
    trial vencido que paga por Stripe debe quedar desbloqueado igual
    que si hubiera pagado por Wompi — antes de este fix, el webhook de
    Stripe sólo tocaba Suscripcion.plan y dejaba Docente.plan intacto,
    así que verify_trial_active seguía devolviendo 402 aunque el pago
    hubiera pasado.
    """
    import suscripciones

    monkeypatch.setattr(settings, "STRIPE_WEBHOOK_SECRET", "whsec_dummy")

    docente = seed_docente["docente"]
    docente.plan = "expirado"
    docente.trial_ends_at = datetime.utcnow() - timedelta(days=1)
    db_session.commit()

    fake_event = {
        "type": "checkout.session.completed",
        "data": {"object": {
            "metadata": {"docente_id": docente.id_docente},
            "subscription": "sub_reactivacion_789",
        }},
    }

    with patch.object(suscripciones.stripe.Webhook, "construct_event", return_value=fake_event):
        r = client.post(
            "/webhook/stripe",
            content=b"{}",
            headers={"stripe-signature": "t=1,v1=fake"},
        )

    assert r.status_code == 200
    db_session.refresh(docente)
    assert docente.plan == "activo"
    assert docente.trial_ends_at is None


def test_webhook_subscription_deleted_revierte_a_free(client, seed_docente, db_session, monkeypatch):
    import suscripciones

    monkeypatch.setattr(settings, "STRIPE_WEBHOOK_SECRET", "whsec_dummy")

    suscripcion = Suscripcion(
        id_docente=seed_docente["docente"].id_docente,
        plan="pro", estado="activa",
        stripe_subscription_id="sub_a_cancelar_456",
    )
    db_session.add(suscripcion)
    db_session.commit()

    fake_event = {
        "type": "customer.subscription.deleted",
        "data": {"object": {"id": "sub_a_cancelar_456", "status": "canceled"}},
    }

    with patch.object(suscripciones.stripe.Webhook, "construct_event", return_value=fake_event):
        r = client.post(
            "/webhook/stripe",
            content=b"{}",
            headers={"stripe-signature": "t=1,v1=fake"},
        )

    assert r.status_code == 200
    db_session.refresh(suscripcion)
    assert suscripcion.plan == "free"
    assert suscripcion.estado == "cancelada"


def test_cancelar_suscripcion_marca_cancel_at_period_end(client, seed_docente, db_session):
    import suscripciones

    suscripcion = Suscripcion(
        id_docente=seed_docente["docente"].id_docente,
        plan="pro", estado="activa",
        stripe_subscription_id="sub_activa_789",
    )
    db_session.add(suscripcion)
    db_session.commit()

    with patch.object(suscripciones.stripe.Subscription, "modify") as mock_modify:
        r = client.post("/api/suscripciones/cancelar")

    assert r.status_code == 200
    mock_modify.assert_called_once_with("sub_activa_789", cancel_at_period_end=True)
    db_session.refresh(suscripcion)
    assert suscripcion.estado == "cancelada"
