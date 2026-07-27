"""
Endpoints REST para sesiones temáticas de chat.

Contexto: el chat pasó de "hilo infinito por modo" a "conversaciones
separadas con título propio". Cada sesión pertenece a (grupo, modo) y
opcionalmente a un estudiante (para modo PIAR — un PIAR por estudiante).

Contrato:
- POST   /api/grupos/{id_grupo}/sesiones          → crear sesión
- GET    /api/grupos/{id_grupo}/sesiones?modo=    → listar del modo
- PUT    /api/sesiones/{id_sesion}/archivar       → archivar
- PUT    /api/sesiones/{id_sesion}/titulo         → actualizar título

Permisos (retro-compat Issue #5):
- El docente dueño del grupo siempre puede.
- Coordinador/rector de la institución del docente-dueño puede LEER
  (GET listar) pero no puede escribir (POST/PUT/archivar). El sprint
  original de sesiones no dio contexto explícito de esto, así que
  aplicamos la regla conservadora "escribe sólo el dueño".
- Cualquier otro → 404.
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from auth import get_current_docente
from database import get_db
from grupos import _get_grupo_or_404
from models import ChatSesion, Docente, Estudiante
from prompts import normalizar_modo

router = APIRouter(tags=["sesiones"])


# ═══════════════════════════════════════════════════════════════
# SCHEMAS
# ═══════════════════════════════════════════════════════════════

class SesionCreate(BaseModel):
    modo: str = Field(..., description="planeacion | socioemocional | calificacion | piar")
    titulo: Optional[str] = Field(default=None, max_length=80)
    id_estudiante: Optional[str] = None


class SesionOut(BaseModel):
    id_sesion: str
    id_grupo: str
    id_docente: str
    modo: str
    titulo: str
    id_estudiante: Optional[str]
    creado_en: datetime
    ultimo_mensaje_en: datetime
    archivada: bool

    model_config = {"from_attributes": True}


class TituloUpdate(BaseModel):
    titulo: str = Field(..., min_length=1, max_length=80)


# ═══════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════

def _titulo_provisional() -> str:
    return "Sesión " + datetime.utcnow().strftime("%d/%m/%Y %H:%M")


def _get_sesion_para_escribir(id_sesion: str, docente: Docente, db: Session) -> ChatSesion:
    """404 si la sesión no existe o no es del docente autenticado."""
    ses = db.query(ChatSesion).filter(
        ChatSesion.id_sesion == id_sesion,
        ChatSesion.id_docente == docente.id_docente,
    ).first()
    if not ses:
        raise HTTPException(status_code=404, detail="Sesión no encontrada")
    return ses


def _validar_estudiante_piar(
    modo: str, id_estudiante: Optional[str], id_grupo: str, db: Session,
) -> None:
    """
    Para modo PIAR el estudiante es obligatorio, debe pertenecer al grupo
    y tener tiene_piar=True. Para otros modos, id_estudiante debe ser None.
    """
    if modo == "piar":
        if not id_estudiante:
            raise HTTPException(
                status_code=400,
                detail="El modo PIAR requiere un id_estudiante.",
            )
        est = db.query(Estudiante).filter(
            Estudiante.id_estudiante == id_estudiante,
            Estudiante.id_grupo == id_grupo,
        ).first()
        if not est:
            raise HTTPException(
                status_code=404,
                detail="Estudiante no encontrado en este grupo.",
            )
        if not est.tiene_piar:
            raise HTTPException(
                status_code=400,
                detail="El estudiante no tiene PIAR activo.",
            )
    elif id_estudiante:
        raise HTTPException(
            status_code=400,
            detail="id_estudiante solo se admite en modo PIAR.",
        )


# ═══════════════════════════════════════════════════════════════
# ENDPOINTS — por grupo
# ═══════════════════════════════════════════════════════════════

@router.post(
    "/api/grupos/{id_grupo}/sesiones",
    response_model=SesionOut,
    status_code=status.HTTP_201_CREATED,
)
def crear_sesion(
    id_grupo: str,
    body: SesionCreate,
    docente: Docente = Depends(get_current_docente),
    db: Session = Depends(get_db),
):
    """
    Crea una sesión temática nueva. La escritura queda reservada al
    dueño del grupo (coordinador/rector no crean sesiones ajenas).
    """
    _get_grupo_or_404(id_grupo, docente, db, permitir_admin_institucion=False)

    modo = normalizar_modo(body.modo)
    _validar_estudiante_piar(modo, body.id_estudiante, id_grupo, db)

    ahora = datetime.utcnow()
    sesion = ChatSesion(
        id_grupo=id_grupo,
        id_docente=docente.id_docente,
        modo=modo,
        titulo=(body.titulo or _titulo_provisional())[:80],
        id_estudiante=body.id_estudiante if modo == "piar" else None,
        creado_en=ahora,
        ultimo_mensaje_en=ahora,
        archivada=False,
    )
    db.add(sesion)
    db.commit()
    db.refresh(sesion)
    return sesion


@router.get(
    "/api/grupos/{id_grupo}/sesiones",
    response_model=List[SesionOut],
)
def listar_sesiones(
    id_grupo: str,
    modo: Optional[str] = Query(default=None),
    incluir_archivadas: bool = Query(default=False),
    id_estudiante: Optional[str] = Query(default=None),
    docente: Docente = Depends(get_current_docente),
    db: Session = Depends(get_db),
):
    """
    Lista sesiones del grupo. Filtros:
    - modo: si se pasa, sólo del modo indicado.
    - id_estudiante: útil para modo PIAR — cada estudiante con PIAR
      tiene sus propias sesiones aunque compartan grupo y modo.
    - incluir_archivadas=False (default): sólo activas al frente;
      True devuelve todas para renderizar el accordion "archivadas".

    Lectura permitida al dueño y a coord/rector de la institución
    (permitir_admin_institucion=True es el default de _get_grupo_or_404).
    """
    _get_grupo_or_404(id_grupo, docente, db)

    q = db.query(ChatSesion).filter(ChatSesion.id_grupo == id_grupo)
    if modo:
        q = q.filter(ChatSesion.modo == normalizar_modo(modo))
    if id_estudiante:
        q = q.filter(ChatSesion.id_estudiante == id_estudiante)
    if not incluir_archivadas:
        q = q.filter(ChatSesion.archivada.is_(False))

    return q.order_by(ChatSesion.ultimo_mensaje_en.desc()).all()


# ═══════════════════════════════════════════════════════════════
# ENDPOINTS — por sesión
# ═══════════════════════════════════════════════════════════════

@router.put("/api/sesiones/{id_sesion}/archivar", response_model=SesionOut)
def archivar_sesion(
    id_sesion: str,
    docente: Docente = Depends(get_current_docente),
    db: Session = Depends(get_db),
):
    """Toggle archivada=True. Idempotente: archivar dos veces no rompe."""
    ses = _get_sesion_para_escribir(id_sesion, docente, db)
    ses.archivada = True
    db.commit()
    db.refresh(ses)
    return ses


@router.put("/api/sesiones/{id_sesion}/titulo", response_model=SesionOut)
def actualizar_titulo(
    id_sesion: str,
    body: TituloUpdate,
    docente: Docente = Depends(get_current_docente),
    db: Session = Depends(get_db),
):
    """Renombra la sesión (manual del docente o llamada interna del bot)."""
    ses = _get_sesion_para_escribir(id_sesion, docente, db)
    ses.titulo = body.titulo.strip()[:80]
    db.commit()
    db.refresh(ses)
    return ses
