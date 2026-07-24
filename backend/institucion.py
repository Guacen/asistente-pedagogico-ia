"""
Endpoints multi-institución (Issue #5).

Estructura de rutas:
- GET  /api/institucion/                          → datos de mi institución (cualquier rol)
- PUT  /api/institucion/                          → editar (solo rector)
- GET  /api/institucion/docentes                  → lista docentes (admin)
- POST /api/institucion/invitar                   → invitar por email (admin)
- PUT  /api/institucion/docentes/{id}/rol         → cambiar rol (solo rector)
- DELETE /api/institucion/docentes/{id}           → remover (solo rector)

Los endpoints de agregados (dashboard, grupos consolidados, PIARs
consolidados) viven en dashboard_institucional.py — subtask 5.

Contrato de errores:
- 403 → rol insuficiente o plan no institucional
- 404 → recurso no visible (docente/institución ajena)
- 400 → validación de body (email inválido, rol inválido, etc.)
- 409 → conflicto de estado (invitar docente ya en institución compartida,
        cambiar propio rol, etc.)
"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from auth import get_current_docente
from database import get_db
from models import Docente, Institucion
from permisos import (
    PLAN_INSTITUCIONAL,
    ROL_COORDINADOR,
    ROL_DOCENTE,
    ROL_RECTOR,
    ROLES_ADMIN,
    ROLES_VALIDOS,
    es_admin_institucion,
    es_rector,
    get_institucion_o_404,
    require_admin_institucion,
    require_rector,
    rol_de,
)

router = APIRouter(prefix="/api/institucion", tags=["institucion"])


# ═══════════════════════════════════════════════════════════════
# SCHEMAS
# ═══════════════════════════════════════════════════════════════

class InstitucionOut(BaseModel):
    id_institucion: str
    nombre: str
    nit: Optional[str] = None
    ciudad: Optional[str] = None
    departamento: Optional[str] = None
    plan: str
    total_docentes: int

    model_config = {"from_attributes": True}


class InstitucionUpdate(BaseModel):
    nombre: Optional[str] = Field(default=None, min_length=1, max_length=200)
    nit: Optional[str] = Field(default=None, max_length=50)
    ciudad: Optional[str] = Field(default=None, max_length=100)
    departamento: Optional[str] = Field(default=None, max_length=100)


class DocenteInstitucionOut(BaseModel):
    id_docente: str
    nombre_completo: str
    email: str
    rol: str
    total_grupos: int

    model_config = {"from_attributes": True}


class InvitarDocenteRequest(BaseModel):
    email: EmailStr


class CambiarRolRequest(BaseModel):
    rol: str = Field(..., description="'docente' | 'coordinador' | 'rector'")


# ═══════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════

def _cuenta_grupos(db: Session, id_docente: str) -> int:
    from models import Grupo
    return db.query(Grupo).filter(Grupo.id_docente == id_docente).count()


def _institucion_out(inst: Institucion, db: Session) -> InstitucionOut:
    total = db.query(Docente).filter(Docente.id_institucion == inst.id_institucion).count()
    return InstitucionOut(
        id_institucion=inst.id_institucion,
        nombre=inst.nombre,
        nit=inst.nit,
        ciudad=inst.ciudad,
        departamento=inst.departamento,
        plan=inst.plan,
        total_docentes=total,
    )


def _docente_out(d: Docente, db: Session) -> DocenteInstitucionOut:
    return DocenteInstitucionOut(
        id_docente=d.id_docente,
        nombre_completo=d.nombre_completo,
        email=d.email,
        rol=rol_de(d),
        total_grupos=_cuenta_grupos(db, d.id_docente),
    )


def _validar_plan_para_rol_admin(inst: Institucion) -> None:
    """
    Regla del sprint: solo se puede asignar rol coordinador/rector si la
    institución tiene plan='institucional'. Se llama antes de promover.
    """
    if inst.plan != PLAN_INSTITUCIONAL:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="El plan actual no incluye roles administrativos.",
        )


# ═══════════════════════════════════════════════════════════════
# ENDPOINTS — DATOS DE LA INSTITUCIÓN
# ═══════════════════════════════════════════════════════════════

@router.get("/", response_model=InstitucionOut)
def obtener_mi_institucion(
    docente: Docente = Depends(get_current_docente),
    db: Session = Depends(get_db),
):
    """Datos básicos de mi institución. Cualquier rol autenticado puede leerla."""
    inst = get_institucion_o_404(docente, db)
    return _institucion_out(inst, db)


@router.put("/", response_model=InstitucionOut)
def actualizar_institucion(
    body: InstitucionUpdate,
    docente: Docente = Depends(require_rector),
    db: Session = Depends(get_db),
):
    """Editar datos de la institución. Solo rector."""
    inst = get_institucion_o_404(docente, db)
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=400, detail="Sin campos para actualizar.")
    for k, v in changes.items():
        setattr(inst, k, v)
    db.commit()
    db.refresh(inst)
    return _institucion_out(inst, db)


# ═══════════════════════════════════════════════════════════════
# ENDPOINTS — GESTIÓN DE DOCENTES
# ═══════════════════════════════════════════════════════════════

@router.get("/docentes", response_model=List[DocenteInstitucionOut])
def listar_docentes(
    docente: Docente = Depends(require_admin_institucion),
    db: Session = Depends(get_db),
):
    """Lista docentes de mi institución. Solo coordinador/rector."""
    inst = get_institucion_o_404(docente, db)
    docs = (
        db.query(Docente)
        .filter(Docente.id_institucion == inst.id_institucion)
        .order_by(Docente.nombre_completo)
        .all()
    )
    return [_docente_out(d, db) for d in docs]


@router.post("/invitar", response_model=DocenteInstitucionOut, status_code=201)
def invitar_docente(
    body: InvitarDocenteRequest,
    docente: Docente = Depends(require_admin_institucion),
    db: Session = Depends(get_db),
):
    """
    Invita un docente por email. Debe estar ya registrado en la plataforma.
    Regla (aprobada por owner): el invitado debe ser el único docente en
    su institución actual (institución uni-personal). Si ya está en una
    institución compartida → 409.
    Al mover al docente, su institución uni-personal huérfana se borra
    (nadie más quedaba en ella).
    """
    inst_actual = get_institucion_o_404(docente, db)
    _validar_plan_para_rol_admin(inst_actual)

    email_norm = body.email.lower().strip()
    invitado = db.query(Docente).filter(Docente.email == email_norm).first()
    if not invitado:
        raise HTTPException(
            status_code=404,
            detail="El docente debe registrarse primero en la plataforma.",
        )

    if invitado.id_docente == docente.id_docente:
        raise HTTPException(status_code=400, detail="No puedes invitarte a ti mismo.")

    if invitado.id_institucion == inst_actual.id_institucion:
        raise HTTPException(
            status_code=409,
            detail="El docente ya pertenece a esta institución.",
        )

    # Contar cuántos docentes hay en la institución actual del invitado
    inst_previa_id = invitado.id_institucion
    otros_en_su_inst = (
        db.query(Docente)
        .filter(
            Docente.id_institucion == inst_previa_id,
            Docente.id_docente != invitado.id_docente,
        )
        .count()
    )
    if otros_en_su_inst > 0:
        raise HTTPException(
            status_code=409,
            detail=(
                "El docente ya pertenece a otra institución compartida. "
                "Debe salir de ella antes de aceptar la invitación."
            ),
        )

    # Mover al invitado a la nueva institución con rol 'docente' por default
    invitado.id_institucion = inst_actual.id_institucion
    invitado.rol = ROL_DOCENTE

    # Borrar la institución uni-personal huérfana (nadie más quedaba)
    if inst_previa_id and inst_previa_id != inst_actual.id_institucion:
        inst_previa = db.query(Institucion).filter(
            Institucion.id_institucion == inst_previa_id,
        ).first()
        if inst_previa:
            db.delete(inst_previa)

    db.commit()
    db.refresh(invitado)
    return _docente_out(invitado, db)


@router.put("/docentes/{id_docente_target}/rol", response_model=DocenteInstitucionOut)
def cambiar_rol(
    id_docente_target: str,
    body: CambiarRolRequest,
    docente: Docente = Depends(require_rector),
    db: Session = Depends(get_db),
):
    """
    Cambiar rol de otro docente de la institución. Solo rector.
    Reglas:
    - No puede cambiar su propio rol.
    - El target debe estar en la misma institución.
    - Rol debe ser válido.
    - Promover a coordinador/rector requiere plan institucional.
    """
    if id_docente_target == docente.id_docente:
        raise HTTPException(
            status_code=409,
            detail="No puedes cambiar tu propio rol.",
        )

    rol_nuevo = body.rol.lower().strip()
    if rol_nuevo not in ROLES_VALIDOS:
        raise HTTPException(
            status_code=400,
            detail=f"Rol inválido. Válidos: {sorted(ROLES_VALIDOS)}",
        )

    inst = get_institucion_o_404(docente, db)
    target = db.query(Docente).filter(
        Docente.id_docente == id_docente_target,
        Docente.id_institucion == inst.id_institucion,
    ).first()
    if not target:
        raise HTTPException(status_code=404, detail="Docente no encontrado en tu institución.")

    if rol_nuevo in ROLES_ADMIN:
        _validar_plan_para_rol_admin(inst)

    target.rol = rol_nuevo
    db.commit()
    db.refresh(target)
    return _docente_out(target, db)


@router.delete("/docentes/{id_docente_target}", status_code=204)
def remover_docente(
    id_docente_target: str,
    docente: Docente = Depends(require_rector),
    db: Session = Depends(get_db),
):
    """
    Remueve un docente de la institución. Solo rector.
    Reglas:
    - No puede removerse a sí mismo (el rector debe transferir la
      institución antes o eliminar su cuenta).
    - El docente removido queda con id_institucion=null; sus grupos
      siguen siendo suyos (no se transfieren).
    - Su rol se resetea a 'docente' para consistencia.
    - Al primer login, el backfill del startup NO le crea nueva
      institución automáticamente porque no corre en runtime.
      Alternativa MVP: crearle una institución uni-personal nueva al
      salir (para que siga teniendo acceso a la app).
    """
    if id_docente_target == docente.id_docente:
        raise HTTPException(
            status_code=409,
            detail="El rector no puede removerse a sí mismo de la institución.",
        )

    inst = get_institucion_o_404(docente, db)
    target = db.query(Docente).filter(
        Docente.id_docente == id_docente_target,
        Docente.id_institucion == inst.id_institucion,
    ).first()
    if not target:
        raise HTTPException(status_code=404, detail="Docente no encontrado en tu institución.")

    # Crear institución uni-personal para el docente removido — sigue
    # teniendo acceso a sus grupos y a los endpoints básicos.
    nueva_inst = Institucion(
        nombre=f"Institución de {target.nombre_completo}",
        plan="free",
    )
    db.add(nueva_inst)
    db.flush()
    target.id_institucion = nueva_inst.id_institucion
    target.rol = ROL_DOCENTE
    db.commit()
