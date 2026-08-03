from datetime import datetime

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from auth import get_current_docente
from config import LIMITES_PLAN, settings
from database import get_db
from models import Docente, Grupo, Suscripcion, UsoMensual
from schemas import CheckoutCreate, SuscripcionOut

router = APIRouter(tags=["suscripciones"])

stripe.api_key = settings.STRIPE_SECRET_KEY

# Sprint stripe-colombia — Price IDs en COP por plan de checkout. El
# docente elige uno de los dos al pagar; ambos activan el mismo plan
# interno "pro" en el webhook (no se tocó esa lógica en este sprint).
PRICE_IDS_CHECKOUT_COP = {
    "docente": lambda: settings.STRIPE_PRICE_ID_DOCENTE_COP,
    "pro": lambda: settings.STRIPE_PRICE_ID_PRO_COP,
}


def _get_uso_mes_actual(docente_id: str, db: Session) -> UsoMensual:
    """Obtiene o crea el registro de uso del mes actual."""
    ahora = datetime.utcnow()
    uso = db.query(UsoMensual).filter(
        UsoMensual.id_docente == docente_id,
        UsoMensual.mes == ahora.month,
        UsoMensual.anio == ahora.year,
    ).first()

    if not uso:
        uso = UsoMensual(
            id_docente=docente_id,
            mes=ahora.month,
            anio=ahora.year,
        )
        db.add(uso)
        db.commit()
        db.refresh(uso)
    return uso


@router.get("/api/suscripciones/mi-suscripcion", response_model=SuscripcionOut)
def get_suscripcion(
    docente: Docente = Depends(get_current_docente),
    db: Session = Depends(get_db),
):
    plan = docente.suscripcion.plan if docente.suscripcion else "free"
    limites = LIMITES_PLAN.get(plan, LIMITES_PLAN["free"])

    uso = _get_uso_mes_actual(docente.id_docente, db)
    grupos_count = db.query(Grupo).filter(Grupo.id_docente == docente.id_docente).count()

    return SuscripcionOut(
        plan=plan,
        estado=docente.suscripcion.estado if docente.suscripcion else "activa",
        mensajes_usados_mes=uso.mensajes_ia_usados,
        mensajes_limite_mes=limites["mensajes"],
        grupos_usados=grupos_count,
        grupos_limite=limites["grupos"],
        fecha_inicio=docente.suscripcion.fecha_inicio if docente.suscripcion else None,
        fecha_fin=docente.suscripcion.fecha_fin if docente.suscripcion else None,
    )


@router.post("/api/suscripciones/checkout")
def create_checkout(
    data: CheckoutCreate,
    docente: Docente = Depends(get_current_docente),
    db: Session = Depends(get_db),
):
    price_id_getter = PRICE_IDS_CHECKOUT_COP.get(data.plan)
    price_id = price_id_getter() if price_id_getter else None

    if not settings.STRIPE_SECRET_KEY or not price_id:
        raise HTTPException(status_code=503, detail="Stripe no configurado")

    try:
        # Crear o recuperar customer de Stripe
        suscripcion = docente.suscripcion
        customer_id = suscripcion.stripe_customer_id if suscripcion else None

        if not customer_id:
            customer = stripe.Customer.create(
                email=docente.email,
                name=docente.nombre_completo,
                metadata={"docente_id": docente.id_docente},
            )
            customer_id = customer.id
            if suscripcion:
                suscripcion.stripe_customer_id = customer_id
                db.commit()

        # Crear Checkout Session — el precio ya viene en COP desde el
        # Price ID (Stripe fija la moneda en el Price del Dashboard, no
        # se puede pasar `currency` acá cuando se referencia un Price
        # existente por id: Stripe rechaza la Session con
        # "invalid_request_error" si se intenta combinar ambos).
        # PSE y Nequi requieren una cuenta Stripe con Colombia habilitado
        # (Dashboard) — si no está habilitado, Stripe devuelve un error
        # al crear la Session, no es un bug de este código.
        session = stripe.checkout.Session.create(
            customer=customer_id,
            payment_method_types=["card", "pse", "nequi"],
            payment_method_options={
                "pse": {"setup_future_usage": "none"},
            },
            line_items=[{"price": price_id, "quantity": 1}],
            mode="subscription",
            success_url=data.success_url,
            cancel_url=data.cancel_url,
            metadata={"docente_id": docente.id_docente},
            locale="es",
        )

        return {"checkout_url": session.url, "session_id": session.id}

    except stripe.StripeError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/api/suscripciones/cancelar")
def cancelar_suscripcion(
    docente: Docente = Depends(get_current_docente),
    db: Session = Depends(get_db),
):
    suscripcion = docente.suscripcion
    if not suscripcion or suscripcion.plan == "free":
        raise HTTPException(status_code=400, detail="No tienes suscripción activa")

    try:
        if suscripcion.stripe_subscription_id:
            stripe.Subscription.modify(
                suscripcion.stripe_subscription_id,
                cancel_at_period_end=True,
            )
        suscripcion.estado = "cancelada"
        db.commit()
        return {"mensaje": "Suscripción cancelada. Activa hasta fin del período."}
    except stripe.StripeError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/webhook/stripe")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    """Webhook de Stripe para actualizar suscripciones automáticamente."""
    if not settings.STRIPE_WEBHOOK_SECRET:
        raise HTTPException(status_code=503, detail="Webhook no configurado")

    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
        )
    except stripe.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Firma inválida")

    # Suscripción activada
    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        docente_id = session.get("metadata", {}).get("docente_id")
        if docente_id:
            suscripcion = db.query(Suscripcion).filter(
                Suscripcion.id_docente == docente_id
            ).first()
            if suscripcion:
                suscripcion.plan = "pro"
                suscripcion.estado = "activa"
                suscripcion.stripe_subscription_id = session.get("subscription")
                db.commit()

    # Suscripción eliminada o vencida
    elif event["type"] in ("customer.subscription.deleted", "customer.subscription.updated"):
        stripe_sub = event["data"]["object"]
        suscripcion = db.query(Suscripcion).filter(
            Suscripcion.stripe_subscription_id == stripe_sub["id"]
        ).first()
        if suscripcion:
            if stripe_sub["status"] in ("canceled", "unpaid", "past_due"):
                suscripcion.plan = "free"
                suscripcion.estado = "cancelada"
            db.commit()

    return {"ok": True}
