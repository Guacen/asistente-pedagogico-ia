"""
perfil.py — Estado de plan/trial del docente. Sprint trial-7-dias.

Vive en su propio router (no dentro de auth.py) porque conceptualmente
es distinto de gestión de cuenta: es lo que el frontend consulta para
decidir qué banner mostrar y, sobre todo, lo que la pantalla de trial
vencido usa para saber en qué estado quedó el docente.

GET /api/perfil/plan es la ÚNICA salida de este router y deliberadamente
NO pasa por verify_trial_active — si lo hiciera, un docente con trial
vencido nunca podría enterarse de que venció (recibiría 402 en el mismo
endpoint que debería explicarle el 402).
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from auth import get_current_docente, trial_vencido
from database import get_db
from models import Docente
from schemas import PlanStatusOut, _dias_restantes_trial

router = APIRouter(prefix="/api/perfil", tags=["perfil"])


@router.get("/plan", response_model=PlanStatusOut)
def get_plan(
    docente: Docente = Depends(get_current_docente),
    db: Session = Depends(get_db),
):
    # Mismo self-heal que verify_trial_active: si nadie pegó a un
    # endpoint gateado desde que venció el trial, `plan` en DB puede
    # seguir en 'trial' aunque la fecha ya pasó. Lo corregimos acá
    # también para que la respuesta (y el banner) reflejen la realidad.
    expirado = trial_vencido(docente, db)
    return PlanStatusOut(
        plan=docente.plan,
        trial_ends_at=docente.trial_ends_at,
        dias_restantes=_dias_restantes_trial(docente.plan, docente.trial_ends_at),
        expirado=expirado,
    )
