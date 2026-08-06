"""
Helpers de permisos multi-institución (Issue #5).

Modelo de roles:
- 'docente'      → default; ve/edita SÓLO sus propios grupos y estudiantes.
                   Comportamiento retro-compatible al pre-sprint.
- 'coordinador'  → ve todos los grupos/estudiantes/PIARs de SU institución.
                   NO puede crear grupos ni editar calificaciones.
- 'rector'       → todo lo del coordinador + puede cambiar roles de docentes
                   de su institución (no puede tocar su propio rol).

Regla de plan:
- Los roles 'coordinador' y 'rector' sólo pueden asignarse si la
  institución tiene plan='institucional'. Bajar el plan NO revoca roles
  automáticamente (decisión operativa del owner).

Contrato de error:
- 404 Not Found para recursos que el docente actual no puede ver (no se
  revela la existencia del recurso).
- 403 Forbidden cuando el rol del caller no permite la acción aunque
  el recurso existe (ej. coordinador intentando crear grupo).
"""
from __future__ import annotations

from typing import Iterable

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from auth import verify_trial_active
from database import get_db
from models import Docente, Grupo, Institucion


# ─────────────────────────────────────────────────────────────
# Constantes de rol
# ─────────────────────────────────────────────────────────────

ROL_DOCENTE = "docente"
ROL_COORDINADOR = "coordinador"
ROL_RECTOR = "rector"

ROLES_VALIDOS = frozenset({ROL_DOCENTE, ROL_COORDINADOR, ROL_RECTOR})
ROLES_ADMIN = frozenset({ROL_COORDINADOR, ROL_RECTOR})

PLAN_INSTITUCIONAL = "institucional"


# ─────────────────────────────────────────────────────────────
# Predicados de rol / institución
# ─────────────────────────────────────────────────────────────

def rol_de(docente: Docente) -> str:
    """Devuelve el rol del docente, cae a 'docente' si el campo no está poblado."""
    return (getattr(docente, "rol", None) or ROL_DOCENTE).lower()


def es_solo_docente(docente: Docente) -> bool:
    return rol_de(docente) == ROL_DOCENTE


def es_admin_institucion(docente: Docente) -> bool:
    """True si el docente tiene rol coordinador o rector."""
    return rol_de(docente) in ROLES_ADMIN


def es_rector(docente: Docente) -> bool:
    return rol_de(docente) == ROL_RECTOR


def puede_ver_grupo(grupo: Grupo, docente_actual: Docente) -> bool:
    """
    True si el docente actual puede leer el grupo:
    - Es el docente dueño, O
    - Es admin (coordinador/rector) de la misma institución que el docente dueño.
    """
    if grupo.id_docente == docente_actual.id_docente:
        return True
    if not es_admin_institucion(docente_actual):
        return False
    if not docente_actual.id_institucion:
        return False
    # Cargar el docente dueño para comparar institución
    dueño = grupo.docente
    if dueño is None:
        # Fallback lazy (no debería pasar con relationship configurada)
        return False
    return dueño.id_institucion == docente_actual.id_institucion


def puede_editar_grupo(grupo: Grupo, docente_actual: Docente) -> bool:
    """
    Edición siempre requiere ser el docente dueño. Coordinadores y rectores
    ven pero NO editan (regla explícita del sprint).
    """
    return grupo.id_docente == docente_actual.id_docente


# ─────────────────────────────────────────────────────────────
# Dependency helpers para FastAPI
# ─────────────────────────────────────────────────────────────

def require_rol(roles_permitidos: Iterable[str]):
    """
    Factory de dependency que valida que el docente autenticado tenga uno
    de los roles permitidos. Usar como:

        @router.get("/algo")
        def endpoint(docente = Depends(require_rol([ROL_RECTOR]))):
            ...

    Retorna 403 con mensaje explícito si el rol no matchea.
    """
    permitidos = {r.lower() for r in roles_permitidos}

    def _dep(docente: Docente = Depends(verify_trial_active)) -> Docente:
        if rol_de(docente) not in permitidos:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Rol '{rol_de(docente)}' no autorizado para esta acción. "
                    f"Roles permitidos: {sorted(permitidos)}."
                ),
            )
        return docente
    return _dep


def require_admin_institucion(docente: Docente = Depends(verify_trial_active)) -> Docente:
    """Coordinador o rector."""
    if not es_admin_institucion(docente):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Requiere rol coordinador o rector. "
                "Contactá al rector de tu institución si necesitás acceso."
            ),
        )
    return docente


def require_rector(docente: Docente = Depends(verify_trial_active)) -> Docente:
    """Solo rector — para acciones que cambian estructura de la institución."""
    if not es_rector(docente):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo el rector de la institución puede realizar esta acción.",
        )
    return docente


def get_institucion_o_404(
    docente: Docente,
    db: Session,
) -> Institucion:
    """
    Devuelve la Institucion del docente actual. 404 si no tiene una
    asignada (caso raro post-migración — indicaría datos inconsistentes).
    """
    if not docente.id_institucion:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="El docente no está asignado a ninguna institución.",
        )
    inst = db.query(Institucion).filter(
        Institucion.id_institucion == docente.id_institucion,
    ).first()
    if not inst:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Institución no encontrada.",
        )
    return inst


def require_plan_institucional(
    docente: Docente = Depends(verify_trial_active),
    db: Session = Depends(get_db),
) -> Docente:
    """
    Guardia para acciones que requieren que la institución del docente
    tenga plan='institucional'. Usar como Depends() en endpoints que
    activan features institucionales (asignar rol, dashboard consolidado).
    """
    if not docente.id_institucion:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="El plan actual no incluye roles administrativos.",
        )
    inst = db.query(Institucion).filter(
        Institucion.id_institucion == docente.id_institucion,
    ).first()
    if not inst or inst.plan != PLAN_INSTITUCIONAL:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="El plan actual no incluye roles administrativos.",
        )
    return docente


# ─────────────────────────────────────────────────────────────
# Query helpers
# ─────────────────────────────────────────────────────────────

def ids_docentes_institucion(id_institucion: str, db: Session) -> list[str]:
    """
    Lista los id_docente de todos los docentes que pertenecen a la
    institución dada. Uso: filtros para queries de agregados (grupos,
    PIARs, dashboards) que necesitan cross-docente pero mismo colegio.
    """
    if not id_institucion:
        return []
    rows = db.query(Docente.id_docente).filter(
        Docente.id_institucion == id_institucion,
    ).all()
    return [r[0] for r in rows]
