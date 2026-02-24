from typing import List

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from auth import get_current_docente
from database import get_db
from models import Grupo, Mensaje
from schemas import MensajeOut

router = APIRouter(prefix="/api", tags=["chat"])


@router.get("/grupos/{grupo_id}/chat/historial", response_model=List[MensajeOut])
def get_historial(
    grupo_id: str,
    limit: int = Query(default=50, le=200),
    docente=Depends(get_current_docente),
    db: Session = Depends(get_db),
):
    # Verificar que el grupo pertenece al docente
    grupo = db.query(Grupo).filter(
        Grupo.id_grupo == grupo_id,
        Grupo.id_docente == docente.id_docente,
    ).first()
    if not grupo:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Grupo no encontrado")

    mensajes = (
        db.query(Mensaje)
        .filter(Mensaje.id_grupo == grupo_id)
        .order_by(Mensaje.timestamp.desc())
        .limit(limit)
        .all()
    )
    return list(reversed(mensajes))
