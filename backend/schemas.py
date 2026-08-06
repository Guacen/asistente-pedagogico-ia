import math
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, EmailStr, computed_field


# ============================================================
# AUTH
# ============================================================

class DocenteCreate(BaseModel):
    nombre_completo: str
    email: EmailStr
    password: str
    # Sprint email-verification-consent — Ley 1581.
    # Requerido para nuevos registros. El caller (auth.register) valida
    # que sea True antes de crear el docente. Docentes existentes al
    # momento del deploy quedan con NULL y aceptan via banner post-login.
    consentimiento_datos: bool = False


class DocenteUpdate(BaseModel):
    nombre_completo: Optional[str] = None
    institucion: Optional[str] = None
    ciudad: Optional[str] = None
    departamento: Optional[str] = None


def _dias_restantes_trial(plan: str, trial_ends_at: Optional[datetime]) -> int:
    """
    Días enteros que faltan para que expire el trial (redondeado hacia
    arriba — quedan "2 días" tanto si faltan 2 días 1 hora como 2 días
    23 horas). 0 si no aplica (plan != 'trial') o si ya venció.
    """
    if plan != "trial" or not trial_ends_at:
        return 0
    restante = (trial_ends_at - datetime.utcnow()).total_seconds()
    return max(0, math.ceil(restante / 86400))


class DocenteOut(BaseModel):
    id_docente: str
    nombre_completo: str
    email: str
    institucion: Optional[str]
    ciudad: Optional[str]
    departamento: Optional[str]
    fecha_registro: datetime
    email_verificado: bool = False
    consentimiento_datos: Optional[bool] = None
    # ── Prueba gratuita 7 días — sprint trial-7-dias ──
    plan: str = "activo"
    trial_ends_at: Optional[datetime] = None

    model_config = {"from_attributes": True}

    @computed_field
    @property
    def dias_restantes(self) -> int:
        return _dias_restantes_trial(self.plan, self.trial_ends_at)


class ChangePassword(BaseModel):
    password_actual: str
    password_nuevo: str


class Token(BaseModel):
    access_token: str
    token_type: str
    docente: DocenteOut


# ── Sprint trial-7-dias ──
class PlanStatusOut(BaseModel):
    plan: str
    trial_ends_at: Optional[datetime] = None
    dias_restantes: int
    expirado: bool


# ── Sprint email-verification-consent ──
# Aceptación de política de datos por docentes existentes (grandfathered)
# que loguearon después del deploy y todavía tienen consentimiento_datos=NULL.
class AceptarConsentimiento(BaseModel):
    aceptado: bool  # el frontend siempre manda True; falso se rechaza en el endpoint


class ReenviarVerificacion(BaseModel):
    email: EmailStr


# ── Sprint password-reset ──
class ForgotPassword(BaseModel):
    email: EmailStr


class ResetPassword(BaseModel):
    password_nuevo: str


# ============================================================
# GRUPOS
# ============================================================

class GrupoCreate(BaseModel):
    nombre_grupo: str
    grado: str
    asignatura: str
    anio_lectivo: int
    periodo_actual: int = 1
    cantidad_estudiantes: int
    recursos_disponibles: Optional[List[str]] = []
    # Estudiantes iniciales — creados en la misma transacción atómica que
    # el grupo. Opcional para retro-compat: si no viene o viene [], solo
    # se crea el grupo (comportamiento pre-fix).
    estudiantes: List["EstudianteCreate"] = []


class GrupoUpdate(BaseModel):
    nombre_grupo: Optional[str] = None
    grado: Optional[str] = None
    asignatura: Optional[str] = None
    anio_lectivo: Optional[int] = None
    periodo_actual: Optional[int] = None
    cantidad_estudiantes: Optional[int] = None
    recursos_disponibles: Optional[List[str]] = None


class GrupoOut(BaseModel):
    id_grupo: str
    id_docente: str
    nombre_grupo: str
    grado: str
    asignatura: str
    anio_lectivo: int
    periodo_actual: int
    cantidad_estudiantes: int
    recursos_disponibles: Optional[Any]
    fecha_creacion: datetime

    model_config = {"from_attributes": True}


# ============================================================
# ESTUDIANTES
# ============================================================

class EstudianteCreate(BaseModel):
    codigo_estudiante: str
    genero: Optional[str] = None
    tiene_piar: bool = False
    diagnostico: Optional[str] = None
    ajustes: Optional[str] = None


class EstudianteUpdate(BaseModel):
    codigo_estudiante: Optional[str] = None
    genero: Optional[str] = None
    tiene_piar: Optional[bool] = None
    diagnostico: Optional[str] = None
    ajustes: Optional[str] = None


class EstudianteOut(BaseModel):
    id_estudiante: str
    id_grupo: str
    codigo_estudiante: str
    genero: Optional[str]
    tiene_piar: bool
    diagnostico: Optional[str]
    ajustes: Optional[str]
    fecha_agregado: datetime

    model_config = {"from_attributes": True}


# ============================================================
# MENSAJES / CHAT
# ============================================================

class MensajeOut(BaseModel):
    id_mensaje: str
    id_grupo: str
    remitente: str
    contenido: str
    modo: str = "planeacion"   # default por retro-compat con mensajes legacy
    id_estudiante: Optional[str] = None  # solo poblado en modo piar
    id_sesion: Optional[str] = None      # sprint sesiones — NULL en mensajes legacy
    timestamp: datetime

    model_config = {"from_attributes": True}


# ============================================================
# NOTAS
# ============================================================

class NotaCreate(BaseModel):
    contenido: str


class NotaOut(BaseModel):
    id_nota: str
    id_grupo: str
    contenido: str
    fecha_creacion: datetime

    model_config = {"from_attributes": True}


# ============================================================
# ARCHIVOS
# ============================================================

class ArchivoOut(BaseModel):
    id_archivo: str
    id_grupo: str
    nombre_archivo: str
    ruta_archivo: str
    tamanio: Optional[int]
    tipo_mime: Optional[str]
    fecha_subida: datetime

    model_config = {"from_attributes": True}


# ============================================================
# CALIFICACIONES
# ============================================================

class CalificacionCreate(BaseModel):
    id_estudiante: str
    periodo: int = 1
    tipo: Optional[str] = None
    descripcion: Optional[str] = None
    valor: Optional[float] = None
    porcentaje: Optional[float] = None


class CalificacionUpdate(BaseModel):
    tipo: Optional[str] = None
    descripcion: Optional[str] = None
    valor: Optional[float] = None
    porcentaje: Optional[float] = None


class CalificacionOut(BaseModel):
    id_calificacion: str
    id_estudiante: str
    id_grupo: str
    id_columna: Optional[str]
    periodo: int
    tipo: Optional[str]
    descripcion: Optional[str]
    valor: Optional[float]
    porcentaje: Optional[float]
    fecha: datetime

    model_config = {"from_attributes": True}


# Upsert: crear o actualizar la nota de un estudiante en una columna
class CalificacionUpsert(BaseModel):
    id_estudiante: str
    id_columna: str
    valor: Optional[float] = None
    periodo: int = 1


# ============================================================
# COLUMNAS DE EVALUACIÓN
# ============================================================

class EvaluacionColumnaCreate(BaseModel):
    nombre: str
    periodo: int = 1
    tipo: Optional[str] = "taller"
    porcentaje: Optional[float] = None
    orden: Optional[int] = 0


class EvaluacionColumnaUpdate(BaseModel):
    nombre: Optional[str] = None
    tipo: Optional[str] = None
    porcentaje: Optional[float] = None
    orden: Optional[int] = None


class EvaluacionColumnaOut(BaseModel):
    id_columna: str
    id_grupo: str
    periodo: int
    nombre: str
    tipo: Optional[str]
    porcentaje: Optional[float]
    orden: int
    fecha_creacion: datetime

    model_config = {"from_attributes": True}


# ============================================================
# SUSCRIPCIONES
# ============================================================

class SuscripcionOut(BaseModel):
    plan: str
    estado: str
    mensajes_usados_mes: int
    mensajes_limite_mes: int
    grupos_usados: int
    grupos_limite: int
    fecha_inicio: Optional[datetime]
    fecha_fin: Optional[datetime]


class CheckoutCreate(BaseModel):
    plan: str
    success_url: str
    cancel_url: str


# Forward reference resolution — GrupoCreate.estudiantes: List["EstudianteCreate"]
# necesita rebuild ahora que EstudianteCreate ya fue definido arriba.
GrupoCreate.model_rebuild()
