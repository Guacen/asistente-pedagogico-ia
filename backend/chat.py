from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from auth import get_current_docente
from database import get_db
from models import Grupo, Mensaje
from prompts import MODOS_ACTIVOS
from schemas import MensajeOut

router = APIRouter(prefix="/api", tags=["chat"])


@router.get("/grupos/{grupo_id}/chat/historial", response_model=List[MensajeOut])
def get_historial(
    grupo_id: str,
    limit: int = Query(default=50, le=200),
    modo: Optional[str] = Query(
        default=None,
        description=(
            "Filtra el historial al modo indicado (planeacion|socioemocional|"
            "calificacion|piar). Si se omite, devuelve todo el historial."
        ),
    ),
    docente=Depends(get_current_docente),
    db: Session = Depends(get_db),
):
    # Verificar que el grupo pertenece al docente
    grupo = db.query(Grupo).filter(
        Grupo.id_grupo == grupo_id,
        Grupo.id_docente == docente.id_docente,
    ).first()
    if not grupo:
        raise HTTPException(status_code=404, detail="Grupo no encontrado")

    q = db.query(Mensaje).filter(Mensaje.id_grupo == grupo_id)

    if modo is not None:
        # Aceptamos modos activos y también 'piar' aunque aún no sea funcional
        # — si mañana hay historial legacy con ese modo, el filtro lo verá.
        modo_norm = modo.strip().lower()
        modos_validos = set(MODOS_ACTIVOS) | {"piar"}
        if modo_norm not in modos_validos:
            raise HTTPException(
                status_code=400,
                detail=f"Modo inválido: '{modo}'. Válidos: {sorted(modos_validos)}",
            )
        q = q.filter(Mensaje.modo == modo_norm)

    mensajes = q.order_by(Mensaje.timestamp.desc()).limit(limit).all()
    return list(reversed(mensajes))
