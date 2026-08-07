"""
Sprint wompi-pagos — checkout Wompi (PSE/Nequi/tarjeta) + webhook.

Las firmas de los eventos se calculan con la fórmula REAL de Wompi
(sha256(concat(properties) + timestamp + secret) — ver wompi_service.py
para la corrección sobre el spec original, que traía una fórmula
distinta que nunca habría verificado un webhook real).
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta

from config import settings
from models import Suscripcion, TransaccionPago


def _firma_evento(properties_values: list[str], timestamp: int, secret: str) -> str:
    cadena = "".join(properties_values) + str(timestamp) + secret
    return hashlib.sha256(cadena.encode()).hexdigest()


def _evento_transaccion(referencia: str, status: str, monto_centavos: int, secret: str, wompi_id: str = "01-abc-123"):
    timestamp = 1700000000
    properties = ["transaction.id", "transaction.status", "transaction.amount_in_cents"]
    valores = [wompi_id, status, str(monto_centavos)]
    checksum = _firma_evento(valores, timestamp, secret)
    evento = {
        "event": "transaction.updated",
        "data": {"transaction": {
            "id": wompi_id, "status": status,
            "amount_in_cents": monto_centavos, "reference": referencia,
            "currency": "COP",
        }},
        "signature": {"properties": properties, "timestamp": timestamp, "checksum": checksum},
    }
    return evento, checksum


def test_iniciar_pago_trial_activo(client, seed_docente, db_session, monkeypatch):
    monkeypatch.setattr(settings, "WOMPI_PUBLIC_KEY", "pub_test_dummy")
    monkeypatch.setattr(settings, "WOMPI_INTEGRITY_SECRET", "integridad_dummy")

    docente = seed_docente["docente"]
    docente.plan = "trial"
    docente.trial_ends_at = datetime.utcnow() + timedelta(days=5)
    db_session.commit()

    r = client.post("/api/pagos/iniciar", json={"plan": "docente"})
    assert r.status_code == 200
    body = r.json()
    assert body["public_key"] == "pub_test_dummy"
    assert body["monto_centavos"] == 2_500_000  # $25.000 COP — precio real de precios.html
    assert body["moneda"] == "COP"
    assert body["referencia"].startswith(f"MAES-docente-{docente.id_docente[:8]}-")
    assert len(body["firma_integridad"]) == 64  # hexdigest sha256

    tx = db_session.query(TransaccionPago).filter_by(referencia=body["referencia"]).first()
    assert tx is not None
    assert tx.id_docente == docente.id_docente
    assert tx.estado == "pendiente"
    assert tx.plan == "docente"


def test_webhook_aprobado(client, seed_docente, db_session, monkeypatch):
    monkeypatch.setattr(settings, "WOMPI_EVENTS_SECRET", "eventos_dummy")

    docente = seed_docente["docente"]
    docente.plan = "expirado"
    docente.trial_ends_at = datetime.utcnow() - timedelta(days=1)
    tx = TransaccionPago(
        id_docente=docente.id_docente, referencia="MAES-docente-abcd1234-1700000000",
        plan="docente", monto_centavos=2_500_000, estado="pendiente",
    )
    db_session.add(tx)
    db_session.commit()

    evento, checksum = _evento_transaccion(tx.referencia, "APPROVED", 2_500_000, "eventos_dummy")

    r = client.post("/api/pagos/webhook", json=evento, headers={"x-event-checksum": checksum})
    assert r.status_code == 200

    db_session.refresh(docente)
    db_session.refresh(tx)
    assert docente.plan == "activo"
    assert docente.trial_ends_at is None
    assert tx.estado == "aprobado"
    assert tx.wompi_id == "01-abc-123"

    suscripcion = db_session.query(Suscripcion).filter_by(id_docente=docente.id_docente).first()
    assert suscripcion is not None
    assert suscripcion.plan == "pro"


def test_webhook_firma_invalida(client, seed_docente, db_session, monkeypatch):
    monkeypatch.setattr(settings, "WOMPI_EVENTS_SECRET", "eventos_dummy")

    docente = seed_docente["docente"]
    docente.plan = "trial"
    tx = TransaccionPago(
        id_docente=docente.id_docente, referencia="MAES-docente-abcd1234-1700000001",
        plan="docente", monto_centavos=2_500_000, estado="pendiente",
    )
    db_session.add(tx)
    db_session.commit()

    evento, _checksum_real = _evento_transaccion(tx.referencia, "APPROVED", 2_500_000, "eventos_dummy")

    r = client.post("/api/pagos/webhook", json=evento, headers={"x-event-checksum": "checksum-falso"})
    assert r.status_code == 401

    db_session.refresh(docente)
    db_session.refresh(tx)
    assert docente.plan == "trial"  # no cambió
    assert tx.estado == "pendiente"  # no cambió


def test_webhook_declinado(client, seed_docente, db_session, monkeypatch):
    monkeypatch.setattr(settings, "WOMPI_EVENTS_SECRET", "eventos_dummy")

    docente = seed_docente["docente"]
    docente.plan = "trial"
    tx = TransaccionPago(
        id_docente=docente.id_docente, referencia="MAES-pro-abcd1234-1700000002",
        plan="pro", monto_centavos=4_500_000, estado="pendiente",
    )
    db_session.add(tx)
    db_session.commit()

    evento, checksum = _evento_transaccion(tx.referencia, "DECLINED", 4_500_000, "eventos_dummy")

    r = client.post("/api/pagos/webhook", json=evento, headers={"x-event-checksum": checksum})
    assert r.status_code == 200

    db_session.refresh(docente)
    db_session.refresh(tx)
    assert tx.estado == "declinado"
    assert docente.plan == "trial"  # no se activó


def test_estado_pago_requiere_ser_dueno(client, seed_docente, db_session):
    """GET /api/pagos/estado/{referencia} de una transacción ajena → 404."""
    otro_id = "otro-docente-id-no-existe"
    tx = TransaccionPago(
        id_docente=otro_id, referencia="MAES-pro-ajena00-1700000003",
        plan="pro", monto_centavos=4_500_000, estado="pendiente",
    )
    db_session.add(tx)
    db_session.commit()

    r = client.get(f"/api/pagos/estado/{tx.referencia}")
    assert r.status_code == 404
