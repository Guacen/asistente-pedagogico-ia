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

from auth import verify_trial_active
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
    docente: Docente = Depends(verify_trial_active),
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

    # Mover al invitado a la nueva institución con rol 'docente' por default.
    invitado.id_institucion = inst_actual.id_institucion
    invitado.rol = ROL_DOCENTE
    # Flush ANTES del delete para que SQLAlchemy vea el nuevo FK del invitado
    # y no lo nule al eliminar la institución previa (cascade implícito por
    # la colección Institucion.docentes cuando el hijo aún se considera del
    # parent original).
    db.flush()
    db.refresh(invitado)

    # Borrar la institución uni-personal huérfana (nadie más quedaba).
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


# ═══════════════════════════════════════════════════════════════
# ENDPOINTS — AGREGADOS INSTITUCIONALES (coordinador+rector)
# ═══════════════════════════════════════════════════════════════

class DashboardInstitucionalOut(BaseModel):
    id_institucion: str
    nombre_institucion: str
    plan: str
    total_docentes: int
    total_grupos: int
    total_estudiantes: int
    estudiantes_con_piar: int
    total_piar: int
    piar_por_estado: dict
    top_grupos_con_piar: list[dict]


class GrupoInstitucionalOut(BaseModel):
    id_grupo: str
    nombre_grupo: str
    grado: str
    asignatura: str
    anio_lectivo: int
    periodo_actual: int
    cantidad_estudiantes: int
    id_docente: str
    docente_nombre: str


class PIARInstitucionalOut(BaseModel):
    id_piar: str
    id_estudiante: str
    codigo_estudiante: str
    id_grupo: str
    nombre_grupo: str
    id_docente: str
    docente_nombre: str
    periodo: int
    anio: int
    version: int
    estado: str
    creado_en: object  # datetime — pydantic maneja el serialize


@router.get("/dashboard", response_model=DashboardInstitucionalOut)
def dashboard_institucional(
    docente: Docente = Depends(require_admin_institucion),
    db: Session = Depends(get_db),
):
    """
    KPIs consolidados de la institución. Solo coordinador/rector.
    Incluye: totales, distribución de PIARs, top 5 grupos con más PIARs.
    """
    from models import Grupo, Estudiante, PIAR

    inst = get_institucion_o_404(docente, db)
    ids_docentes = [
        d.id_docente
        for d in db.query(Docente).filter(
            Docente.id_institucion == inst.id_institucion,
        ).all()
    ]

    if not ids_docentes:
        return DashboardInstitucionalOut(
            id_institucion=inst.id_institucion,
            nombre_institucion=inst.nombre,
            plan=inst.plan,
            total_docentes=0,
            total_grupos=0,
            total_estudiantes=0,
            estudiantes_con_piar=0,
            total_piar=0,
            piar_por_estado={"borrador": 0, "aprobado": 0},
            top_grupos_con_piar=[],
        )

    grupos = db.query(Grupo).filter(Grupo.id_docente.in_(ids_docentes)).all()
    ids_grupos = [g.id_grupo for g in grupos]

    total_est = 0
    est_con_piar = 0
    piar_por_grupo: dict[str, int] = {}
    if ids_grupos:
        estudiantes = db.query(Estudiante).filter(
            Estudiante.id_grupo.in_(ids_grupos),
        ).all()
        total_est = len(estudiantes)
        for e in estudiantes:
            if e.tiene_piar:
                est_con_piar += 1
                piar_por_grupo[e.id_grupo] = piar_por_grupo.get(e.id_grupo, 0) + 1

    piars = (
        db.query(PIAR)
        .filter(PIAR.id_docente.in_(ids_docentes))
        .all()
    )
    piar_estado: dict[str, int] = {"borrador": 0, "aprobado": 0}
    for p in piars:
        piar_estado[p.estado] = piar_estado.get(p.estado, 0) + 1

    grupos_por_id = {g.id_grupo: g for g in grupos}
    top_grupos = sorted(
        piar_por_grupo.items(), key=lambda x: x[1], reverse=True,
    )[:5]
    top_out = []
    for gid, count in top_grupos:
        g = grupos_por_id.get(gid)
        if not g:
            continue
        top_out.append({
            "id_grupo": gid,
            "nombre_grupo": g.nombre_grupo,
            "grado": g.grado,
            "estudiantes_con_piar": count,
        })

    return DashboardInstitucionalOut(
        id_institucion=inst.id_institucion,
        nombre_institucion=inst.nombre,
        plan=inst.plan,
        total_docentes=len(ids_docentes),
        total_grupos=len(grupos),
        total_estudiantes=total_est,
        estudiantes_con_piar=est_con_piar,
        total_piar=len(piars),
        piar_por_estado=piar_estado,
        top_grupos_con_piar=top_out,
    )


@router.get("/grupos", response_model=List[GrupoInstitucionalOut])
def listar_grupos_institucion(
    docente: Docente = Depends(require_admin_institucion),
    db: Session = Depends(get_db),
):
    """Todos los grupos de la institución con info del docente dueño."""
    from models import Grupo

    inst = get_institucion_o_404(docente, db)
    docs_por_id = {
        d.id_docente: d
        for d in db.query(Docente).filter(
            Docente.id_institucion == inst.id_institucion,
        ).all()
    }
    if not docs_por_id:
        return []
    grupos = (
        db.query(Grupo)
        .filter(Grupo.id_docente.in_(list(docs_por_id.keys())))
        .order_by(Grupo.grado, Grupo.asignatura, Grupo.nombre_grupo)
        .all()
    )
    out: list[GrupoInstitucionalOut] = []
    for g in grupos:
        dueño = docs_por_id.get(g.id_docente)
        out.append(GrupoInstitucionalOut(
            id_grupo=g.id_grupo,
            nombre_grupo=g.nombre_grupo,
            grado=g.grado,
            asignatura=g.asignatura,
            anio_lectivo=g.anio_lectivo,
            periodo_actual=g.periodo_actual or 1,
            cantidad_estudiantes=g.cantidad_estudiantes,
            id_docente=g.id_docente,
            docente_nombre=dueño.nombre_completo if dueño else "—",
        ))
    return out


@router.get("/piar", response_model=List[PIARInstitucionalOut])
def listar_piars_institucion(
    estado: Optional[str] = None,
    id_estudiante: Optional[str] = None,
    limit: int = 50,
    docente: Docente = Depends(require_admin_institucion),
    db: Session = Depends(get_db),
):
    """
    Todos los PIARs de la institución. Coord/rector — para seguimiento
    de cumplimiento legal Decreto 1421. Últimos 50 desc por creado_en.
    Filtros opcionales: ?estado=borrador|aprobado, ?id_estudiante=X
    """
    from models import Estudiante, Grupo, PIAR

    inst = get_institucion_o_404(docente, db)
    docs_por_id = {
        d.id_docente: d
        for d in db.query(Docente).filter(
            Docente.id_institucion == inst.id_institucion,
        ).all()
    }
    if not docs_por_id:
        return []

    q = db.query(PIAR).filter(PIAR.id_docente.in_(list(docs_por_id.keys())))
    if estado:
        if estado not in ("borrador", "aprobado"):
            raise HTTPException(
                status_code=400,
                detail="Estado inválido. Válidos: 'borrador', 'aprobado'.",
            )
        q = q.filter(PIAR.estado == estado)
    if id_estudiante:
        q = q.filter(PIAR.id_estudiante == id_estudiante)

    piars = q.order_by(PIAR.creado_en.desc()).limit(max(1, min(limit, 200))).all()

    # Pre-cargar estudiantes y grupos necesarios en batch para evitar N+1
    est_ids = {p.id_estudiante for p in piars}
    grp_ids = {p.id_grupo for p in piars}
    est_por_id = {
        e.id_estudiante: e
        for e in db.query(Estudiante).filter(Estudiante.id_estudiante.in_(est_ids)).all()
    } if est_ids else {}
    grp_por_id = {
        g.id_grupo: g
        for g in db.query(Grupo).filter(Grupo.id_grupo.in_(grp_ids)).all()
    } if grp_ids else {}

    out: list[PIARInstitucionalOut] = []
    for p in piars:
        est = est_por_id.get(p.id_estudiante)
        g = grp_por_id.get(p.id_grupo)
        dueño = docs_por_id.get(p.id_docente)
        out.append(PIARInstitucionalOut(
            id_piar=p.id_piar,
            id_estudiante=p.id_estudiante,
            codigo_estudiante=est.codigo_estudiante if est else "—",
            id_grupo=p.id_grupo,
            nombre_grupo=g.nombre_grupo if g else "—",
            id_docente=p.id_docente,
            docente_nombre=dueño.nombre_completo if dueño else "—",
            periodo=p.periodo,
            anio=p.anio,
            version=p.version,
            estado=p.estado,
            creado_en=p.creado_en,
        ))
    return out
