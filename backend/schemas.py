from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, EmailStr


# ============================================================
# AUTH
# ============================================================

class DocenteCreate(BaseModel):
    nombre_completo: str
    email: EmailStr
    password: str


class DocenteUpdate(BaseModel):
    nombre_completo: Optional[str] = None
    institucion: Optional[str] = None
    ciudad: Optional[str] = None
    departamento: Optional[str] = None


class DocenteOut(BaseModel):
    id_docente: str
    nombre_completo: str
    email: str
    institucion: Optional[str]
    ciudad: Optional[str]
    departamento: Optional[str]
    fecha_registro: datetime

    model_config = {"from_attributes": True}


class ChangePassword(BaseModel):
    password_actual: str
    password_nuevo: str


class Token(BaseModel):
    access_token: str
    token_type: str
    docente: DocenteOut


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
