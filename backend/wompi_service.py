"""
wompi_service.py — Firmas y utilidades del checkout Wompi. Sprint
wompi-pagos.

Usa `settings` (config.py / Pydantic Settings) en vez de `os.getenv`
directo — así WOMPI_PUBLIC_KEY etc. se leen igual que el resto del
proyecto (Stripe, Resend, SendGrid...) y quedan mockeables en tests
vía `monkeypatch.setattr(settings, ...)`, mismo patrón que
test_suscripciones.py usa para Stripe.

IMPORTANTE — corrección sobre el spec original del sprint:
El spec pedía `verificar_firma_evento` como
`sha256(payload_raw + WOMPI_EVENTS_SECRET)`. Se verificó contra la
documentación oficial de Wompi (docs.wompi.co/eventos) antes de
implementar: el algoritmo real NO es ese. Es:

    sha256(concat(valores de signature.properties, en orden)
           + signature.timestamp + WOMPI_EVENTS_SECRET)

donde `signature.properties` es una lista de paths (ej.
"transaction.id", "transaction.status") a resolver contra `data` en
el body del evento — varía por tipo de evento, nunca se hardcodea.
Con la fórmula del spec, el 100% de los webhooks reales de Wompi
habría fallado la verificación (401 permanente) — se implementa acá
la fórmula real, documentada, en vez de la del spec.

También se verificó `calcular_firma_integridad` (para el widget/
checkout, endpoint distinto) contra la documentación — esa sí coincide
con lo que pedía el spec: sha256(referencia + monto + moneda + secret).
"""
import hashlib
import hmac
from datetime import datetime
from typing import Optional

from config import settings


def generar_referencia(docente_id: str, plan: str) -> str:
    """Referencia única enviada a Wompi: MAES-{plan}-{docente_id[:8]}-{timestamp}."""
    timestamp = int(datetime.utcnow().timestamp())
    return f"MAES-{plan}-{docente_id[:8]}-{timestamp}"


def calcular_firma_integridad(referencia: str, monto_centavos: int, moneda: str = "COP") -> str:
    """
    Firma de integridad del checkout (signature:integrity) — verificada
    contra la doc de Wompi: sha256(referencia + monto + moneda + secret).
    """
    cadena = f"{referencia}{monto_centavos}{moneda}{settings.WOMPI_INTEGRITY_SECRET}"
    return hashlib.sha256(cadena.encode()).hexdigest()


def _resolver_propiedad(data: dict, path: str) -> Optional[str]:
    """Resuelve un path tipo 'transaction.id' contra el dict `data` del evento."""
    valor = data
    for parte in path.split("."):
        if not isinstance(valor, dict) or parte not in valor:
            return None
        valor = valor[parte]
    return str(valor)


def verificar_firma_evento(evento: dict, checksum_header: str) -> bool:
    """
    Verifica que un webhook venga realmente de Wompi.

    `evento` es el body ya parseado como JSON (debe incluir
    evento["signature"]["properties"]/["timestamp"] y evento["data"]).
    `checksum_header` es el valor del header `X-Event-Checksum`.
    """
    if not checksum_header or not settings.WOMPI_EVENTS_SECRET:
        return False

    firma = evento.get("signature") or {}
    propiedades = firma.get("properties") or []
    timestamp = firma.get("timestamp")
    if not propiedades or timestamp is None:
        return False

    data = evento.get("data") or {}
    valores = []
    for path in propiedades:
        valor = _resolver_propiedad(data, path)
        if valor is None:
            return False
        valores.append(valor)

    cadena = "".join(valores) + str(timestamp) + settings.WOMPI_EVENTS_SECRET
    esperado = hashlib.sha256(cadena.encode()).hexdigest()
    return hmac.compare_digest(esperado, checksum_header)
