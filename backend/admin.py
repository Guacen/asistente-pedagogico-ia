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

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from auth import get_current_docente
from database import get_db
from models import (
    AuditLog, CodigoInvitacion, Docente, Estudiante, Grupo, Mensaje,
    RateLimitCounter,
)

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


# ============================================================
# SPRINT H, PARTE A — CÓDIGOS DE INVITACIÓN A LA BETA
# ============================================================

class CodigoInvitacionCreate(BaseModel):
    codigo: str = Field(max_length=50)
    descripcion: Optional[str] = Field(default=None, max_length=200)
    fecha_expiracion: datetime
    fecha_vencimiento_beta: Optional[datetime] = None
    usos_maximos: int = Field(default=1, ge=1)


class CodigoInvitacionUpdate(BaseModel):
    # Único campo editable después de creado — "desactivar" (y su
    # inverso, reactivar) es la única operación que pidió el spec.
    # Cambiar fechas/usos de un código ya repartido es más fácil de
    # hacer bien borrándolo y creando uno nuevo que editando a medias
    # uno que alguien ya puede estar usando.
    activo: bool


class CodigoInvitacionOut(BaseModel):
    codigo: str
    descripcion: Optional[str]
    fecha_expiracion: datetime
    fecha_vencimiento_beta: Optional[datetime]
    usos_maximos: int
    usos_actuales: int
    activo: bool
    creado_en: datetime

    model_config = {"from_attributes": True}


@router.post("/codigos", response_model=CodigoInvitacionOut, status_code=status.HTTP_201_CREATED)
def crear_codigo_invitacion(
    data: CodigoInvitacionCreate,
    _admin: Docente = Depends(_requerir_admin),
    db: Session = Depends(get_db),
):
    codigo_normalizado = data.codigo.strip().upper()
    if not codigo_normalizado:
        raise HTTPException(status_code=400, detail="El código no puede estar vacío.")
    if db.query(CodigoInvitacion).filter(CodigoInvitacion.codigo == codigo_normalizado).first():
        raise HTTPException(status_code=400, detail="Ya existe un código con ese nombre.")

    codigo = CodigoInvitacion(
        codigo=codigo_normalizado,
        descripcion=data.descripcion,
        fecha_expiracion=data.fecha_expiracion,
        fecha_vencimiento_beta=data.fecha_vencimiento_beta,
        usos_maximos=data.usos_maximos,
    )
    db.add(codigo)
    db.commit()
    db.refresh(codigo)
    return codigo


@router.get("/codigos", response_model=List[CodigoInvitacionOut])
def listar_codigos_invitacion(
    _admin: Docente = Depends(_requerir_admin),
    db: Session = Depends(get_db),
):
    return (
        db.query(CodigoInvitacion)
        .order_by(CodigoInvitacion.creado_en.desc())
        .all()
    )


@router.patch("/codigos/{codigo}", response_model=CodigoInvitacionOut)
def actualizar_codigo_invitacion(
    codigo: str,
    data: CodigoInvitacionUpdate,
    _admin: Docente = Depends(_requerir_admin),
    db: Session = Depends(get_db),
):
    obj = db.query(CodigoInvitacion).filter(
        CodigoInvitacion.codigo == codigo.strip().upper()
    ).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Código no encontrado.")
    obj.activo = data.activo
    db.commit()
    db.refresh(obj)
    return obj


# ============================================================
# SPRINT H, PARTE B — TABLERO DE COHORTE BETA
# ============================================================
#
# REGLA INVIOLABLE: esta vista NO expone ningún dato de estudiantes —
# ni nombres, ni códigos, ni contenido de planeaciones u observaciones.
# Sólo conteos (int) y metadatos del DOCENTE (correo, fechas, estados).
# Nada de lo que sigue hace SELECT sobre columnas de contenido de
# Estudiante/Mensaje/Observacion — sólo COUNT(*).
#
# Deliberadamente sin pipeline de eventos ni curvas de retención — son
# 2 a 20 docentes, no cientos. Una fila por docente alcanza.

class CohorteDocenteOut(BaseModel):
    id_docente: str
    email: str
    fecha_registro: datetime
    email_verificado: bool
    onboarding_estado: str
    grupos_creados: int
    estudiantes_agregados: int
    planeaciones_generadas: int
    ultimo_acceso: Optional[datetime]
    activado: bool


class CohorteResumenOut(BaseModel):
    invitados: int
    registrados: int
    verificados: int
    activados: int


class CohorteOut(BaseModel):
    resumen: CohorteResumenOut
    docentes: List[CohorteDocenteOut]


def _docente_activado(db: Session, id_docente: str) -> bool:
    """
    Grupo real (es_ejemplo=False) + al menos una planeación real
    (Mensaje remitente='sistema', modo='planeacion', en un grupo real
    de ese docente) — misma definición de "activación" que el resto
    del proyecto viene usando desde que se introdujo es_ejemplo
    (sprint primer-uso, Parte D3).
    """
    tiene_grupo_real = (
        db.query(Grupo.id_grupo)
        .filter(Grupo.id_docente == id_docente, Grupo.es_ejemplo.is_(False))
        .first()
        is not None
    )
    if not tiene_grupo_real:
        return False
    tiene_planeacion_real = (
        db.query(Mensaje.id_mensaje)
        .join(Grupo, Mensaje.id_grupo == Grupo.id_grupo)
        .filter(
            Grupo.id_docente == id_docente,
            Grupo.es_ejemplo.is_(False),
            Mensaje.remitente == "sistema",
            Mensaje.modo == "planeacion",
        )
        .first()
        is not None
    )
    return tiene_planeacion_real


@router.get("/cohorte", response_model=CohorteOut)
def get_cohorte_beta(
    _admin: Docente = Depends(_requerir_admin),
    db: Session = Depends(get_db),
):
    docentes_beta = (
        db.query(Docente)
        .filter(Docente.plan == "beta")
        .order_by(Docente.fecha_registro.asc())
        .all()
    )

    filas: List[CohorteDocenteOut] = []
    activados = 0
    verificados = 0
    for d in docentes_beta:
        grupos_creados = db.query(func.count(Grupo.id_grupo)).filter(
            Grupo.id_docente == d.id_docente
        ).scalar() or 0
        estudiantes_agregados = (
            db.query(func.count(Estudiante.id_estudiante))
            .join(Grupo, Estudiante.id_grupo == Grupo.id_grupo)
            .filter(Grupo.id_docente == d.id_docente)
            .scalar() or 0
        )
        planeaciones_generadas = (
            db.query(func.count(Mensaje.id_mensaje))
            .join(Grupo, Mensaje.id_grupo == Grupo.id_grupo)
            .filter(
                Grupo.id_docente == d.id_docente,
                Mensaje.remitente == "sistema",
                Mensaje.modo == "planeacion",
            )
            .scalar() or 0
        )
        ultimo_acceso = (
            db.query(func.max(AuditLog.timestamp))
            .filter(AuditLog.id_docente == d.id_docente, AuditLog.accion == "login")
            .scalar()
        )
        activado = _docente_activado(db, d.id_docente)

        if d.email_verificado:
            verificados += 1
        if activado:
            activados += 1

        filas.append(CohorteDocenteOut(
            id_docente=d.id_docente,
            email=d.email,
            fecha_registro=d.fecha_registro,
            email_verificado=d.email_verificado,
            onboarding_estado=d.onboarding_estado,
            grupos_creados=grupos_creados,
            estudiantes_agregados=estudiantes_agregados,
            planeaciones_generadas=planeaciones_generadas,
            ultimo_acceso=ultimo_acceso,
            activado=activado,
        ))

    # "Invitados" = capacidad total de invitación extendida hasta ahora
    # (suma de usos_maximos de TODOS los códigos creados, activos o no
    # — desactivar un código no borra el cupo que ya se había ofrecido).
    invitados = db.query(func.coalesce(func.sum(CodigoInvitacion.usos_maximos), 0)).scalar() or 0

    return CohorteOut(
        resumen=CohorteResumenOut(
            invitados=invitados,
            registrados=len(docentes_beta),
            verificados=verificados,
            activados=activados,
        ),
        docentes=filas,
    )
