"""
pagos.py — Checkout Wompi (PSE/Nequi/tarjeta) y webhook de confirmación.
Sprint wompi-pagos.

Nombrado `pagos.py` (no `pagos_router.py` como pedía el spec) — todos
los routers de este repo son archivos planos nombrados por dominio sin
sufijo (auth.py, chat.py, malla.py, perfil.py, suscripciones.py...).

`/api/pagos/iniciar` y `/api/pagos/estado/{referencia}` usan
get_current_docente (NO verify_trial_active) a propósito — igual
criterio que /api/suscripciones/*: si estuvieran gateados por el
trial, un docente con trial vencido jamás podría pagar para
reactivarse. Ver auth.py (verify_trial_active) para el razonamiento
completo.
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from auth import get_current_docente
from config import PRECIOS_WOMPI_COP, settings
from database import get_db
from models import Docente, Suscripcion, TransaccionPago
from schemas import EstadoPagoOut, IniciarPagoOut, IniciarPagoRequest
from wompi_service import calcular_firma_integridad, generar_referencia, verificar_firma_evento

router = APIRouter(prefix="/api/pagos", tags=["pagos"])


@router.post("/iniciar", response_model=IniciarPagoOut)
def iniciar_pago(
    body: IniciarPagoRequest,
    request: Request,
    docente: Docente = Depends(get_current_docente),
    db: Session = Depends(get_db),
):
    monto_centavos = PRECIOS_WOMPI_COP.get(body.plan)
    if monto_centavos is None:
        raise HTTPException(status_code=400, detail="Plan inválido. Usa 'docente' o 'pro'.")
    if not settings.WOMPI_PUBLIC_KEY or not settings.WOMPI_INTEGRITY_SECRET:
        raise HTTPException(status_code=503, detail="Wompi no configurado")

    referencia = generar_referencia(docente.id_docente, body.plan)
    db.add(TransaccionPago(
        id_docente=docente.id_docente,
        referencia=referencia,
        plan=body.plan,
        monto_centavos=monto_centavos,
        estado="pendiente",
    ))
    db.commit()

    firma = calcular_firma_integridad(referencia, monto_centavos, "COP")

    # URL absoluta derivada del request actual (no hardcodeada) — funciona
    # igual en dev local, Railway staging y producción sin cambiar código,
    # mismo patrón que _crear_token_verificacion en auth.py.
    base = str(request.base_url).rstrip("/")

    return IniciarPagoOut(
        public_key=settings.WOMPI_PUBLIC_KEY,
        referencia=referencia,
        monto_centavos=monto_centavos,
        moneda="COP",
        firma_integridad=firma,
        redirect_url=f"{base}/pago-resultado.html",
    )


@router.post("/webhook")
async def webhook_wompi(request: Request, db: Session = Depends(get_db)):
    """
    Wompi llama acá cuando cambia el estado de una transacción. Siempre
    devuelve 200 (salvo firma inválida) — Wompi reintenta hasta 3 veces
    en 24h si no recibe 200, y no tiene sentido reintentar un evento que
    ya procesamos o que nunca vamos a poder verificar.
    """
    payload_raw = await request.body()
    checksum = request.headers.get("x-event-checksum", "")

    try:
        evento = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Body inválido")

    if not verificar_firma_evento(evento, checksum):
        raise HTTPException(status_code=401, detail="Firma inválida")

    transaccion_wompi = (evento.get("data") or {}).get("transaction") or {}
    referencia = transaccion_wompi.get("reference")
    if not referencia:
        return {"ok": True}  # evento sin referencia reconocible — nada que hacer

    tx = db.query(TransaccionPago).filter(TransaccionPago.referencia == referencia).first()
    if not tx:
        return {"ok": True}  # referencia que no generamos nosotros — se ignora

    estado_wompi = transaccion_wompi.get("status")
    tx.wompi_id = transaccion_wompi.get("id")
    tx.actualizado_en = datetime.utcnow()

    if estado_wompi == "APPROVED":
        tx.estado = "aprobado"
        docente = db.query(Docente).filter(Docente.id_docente == tx.id_docente).first()
        if docente:
            docente.plan = "activo"
            docente.trial_ends_at = None
            # Mismo criterio que el webhook de Stripe (suscripciones.py):
            # "docente" y "pro" son dos precios distintos que activan el
            # mismo plan interno "pro" a nivel de Suscripcion — no se
            # inventa un tercer tier ahí, LIMITES_PLAN sólo conoce
            # 'free'/'pro'.
            suscripcion = docente.suscripcion
            if suscripcion:
                suscripcion.plan = "pro"
                suscripcion.estado = "activa"
            else:
                db.add(Suscripcion(id_docente=docente.id_docente, plan="pro", estado="activa"))
    elif estado_wompi == "DECLINED":
        tx.estado = "declinado"
    elif estado_wompi in ("ERROR", "VOIDED"):
        tx.estado = "error"

    db.commit()
    return {"ok": True}


@router.get("/estado/{referencia}", response_model=EstadoPagoOut)
def estado_pago(
    referencia: str,
    docente: Docente = Depends(get_current_docente),
    db: Session = Depends(get_db),
):
    tx = db.query(TransaccionPago).filter(
        TransaccionPago.referencia == referencia,
        TransaccionPago.id_docente == docente.id_docente,
    ).first()
    if not tx:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transacción no encontrada")
    return EstadoPagoOut(
        referencia=tx.referencia,
        plan=tx.plan,
        estado=tx.estado,
        monto_centavos=tx.monto_centavos,
        creado_en=tx.creado_en,
    )
