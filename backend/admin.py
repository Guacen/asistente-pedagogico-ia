"""
admin.py — Endpoints de mantenimiento restringidos a docentes con
`es_admin=True` (mismo flag que ya existe para bypasear el rate limit
diario — se activa manualmente por SQL:
    UPDATE docentes SET es_admin = TRUE WHERE email = '<email>';

Sprint: reset de límites por período académico. `RateLimitCounter` es
un contador diario (clave: docente+fecha+modo) que ya "rota" solo día
a día, pero las filas viejas se acumulan para siempre sin limpiarse.
Este endpoint las purga por completo — pensado para llamarse a mano o
desde un cron externo (Railway Cron Job / GitHub Actions scheduled
workflow) al iniciar cada período académico (bimestre/trimestre) o
cada mes, según decida la institución. La cadencia es una decisión de
infraestructura (qué tan seguido se llama el endpoint), no algo
hardcodeado en el código.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from auth import get_current_docente
from database import get_db
from models import Docente, RateLimitCounter

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _requerir_admin(docente: Docente = Depends(get_current_docente)) -> Docente:
    if not docente.es_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Requiere permisos de administrador.",
        )
    return docente


@router.post("/reset-limites-periodo")
def reset_limites_periodo(
    _admin: Docente = Depends(_requerir_admin),
    db: Session = Depends(get_db),
):
    """
    Purga todos los contadores de `rate_limit_counter`. Los docentes
    vuelven a tener su cupo diario completo por modo desde la próxima
    generación, sin esperar a que la fecha cambie sola.

    No toca `UsoMensual` (cupo mensual del plan) ni `periodo_actual` de
    los grupos — esos son otros contadores con su propio ciclo de vida.
    """
    borrados = db.query(RateLimitCounter).delete()
    db.commit()
    return {"contadores_eliminados": borrados}
