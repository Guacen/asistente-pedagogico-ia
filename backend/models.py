import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean, Column, DateTime, Float, ForeignKey,
    Integer, JSON, String, Text
)
from sqlalchemy.orm import relationship

from database import Base


def new_uuid() -> str:
    return str(uuid.uuid4())


class Docente(Base):
    __tablename__ = "docentes"

    id_docente = Column(String(36), primary_key=True, default=new_uuid)
    nombre_completo = Column(String(200), nullable=False)
    email = Column(String(200), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    institucion = Column(String(200))
    ciudad = Column(String(100))
    departamento = Column(String(100))
    fecha_registro = Column(DateTime, default=datetime.utcnow)

    # Relaciones
    grupos = relationship("Grupo", back_populates="docente", cascade="all, delete")
    suscripcion = relationship("Suscripcion", back_populates="docente", uselist=False, cascade="all, delete")
    uso_mensual = relationship("UsoMensual", back_populates="docente", cascade="all, delete")


class Suscripcion(Base):
    __tablename__ = "suscripciones"

    id_suscripcion = Column(String(36), primary_key=True, default=new_uuid)
    id_docente = Column(String(36), ForeignKey("docentes.id_docente"), nullable=False)
    plan = Column(String(20), nullable=False, default="free")  # 'free' o 'pro'
    stripe_customer_id = Column(String(100))
    stripe_subscription_id = Column(String(100))
    estado = Column(String(20), default="activa")  # 'activa', 'cancelada', 'vencida'
    fecha_inicio = Column(DateTime, default=datetime.utcnow)
    fecha_fin = Column(DateTime)

    docente = relationship("Docente", back_populates="suscripcion")


class UsoMensual(Base):
    __tablename__ = "uso_mensual"

    id_uso = Column(String(36), primary_key=True, default=new_uuid)
    id_docente = Column(String(36), ForeignKey("docentes.id_docente"), nullable=False)
    mes = Column(Integer, nullable=False)
    anio = Column(Integer, nullable=False)
    mensajes_ia_usados = Column(Integer, default=0)

    docente = relationship("Docente", back_populates="uso_mensual")


class Grupo(Base):
    __tablename__ = "grupos"

    id_grupo = Column(String(36), primary_key=True, default=new_uuid)
    id_docente = Column(String(36), ForeignKey("docentes.id_docente"), nullable=False)
    nombre_grupo = Column(String(100), nullable=False)
    grado = Column(String(10), nullable=False)
    asignatura = Column(String(50), nullable=False)
    anio_lectivo = Column(Integer, nullable=False)
    periodo_actual = Column(Integer, default=1)
    cantidad_estudiantes = Column(Integer, nullable=False)
    recursos_disponibles = Column(JSON)
    fecha_creacion = Column(DateTime, default=datetime.utcnow)

    # Relaciones
    docente = relationship("Docente", back_populates="grupos")
    estudiantes = relationship("Estudiante", back_populates="grupo", cascade="all, delete")
    mensajes = relationship("Mensaje", back_populates="grupo", cascade="all, delete")
    notas = relationship("Nota", back_populates="grupo", cascade="all, delete")
    archivos = relationship("Archivo", back_populates="grupo", cascade="all, delete")
    calificaciones = relationship("Calificacion", back_populates="grupo", cascade="all, delete")


class Estudiante(Base):
    __tablename__ = "estudiantes"

    id_estudiante = Column(String(36), primary_key=True, default=new_uuid)
    id_grupo = Column(String(36), ForeignKey("grupos.id_grupo"), nullable=False)
    codigo_estudiante = Column(String(100), nullable=False)
    genero = Column(String(20))
    tiene_piar = Column(Boolean, default=False)
    diagnostico = Column(Text)
    ajustes = Column(Text)
    fecha_agregado = Column(DateTime, default=datetime.utcnow)

    grupo = relationship("Grupo", back_populates="estudiantes")
    calificaciones = relationship("Calificacion", back_populates="estudiante", cascade="all, delete")


class Mensaje(Base):
    __tablename__ = "mensajes"

    id_mensaje = Column(String(36), primary_key=True, default=new_uuid)
    id_grupo = Column(String(36), ForeignKey("grupos.id_grupo"), nullable=False)
    remitente = Column(String(20), nullable=False)  # 'docente' o 'sistema'
    contenido = Column(Text, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)

    grupo = relationship("Grupo", back_populates="mensajes")


class Nota(Base):
    __tablename__ = "notas"

    id_nota = Column(String(36), primary_key=True, default=new_uuid)
    id_grupo = Column(String(36), ForeignKey("grupos.id_grupo"), nullable=False)
    contenido = Column(Text, nullable=False)
    fecha_creacion = Column(DateTime, default=datetime.utcnow)

    grupo = relationship("Grupo", back_populates="notas")


class Calificacion(Base):
    __tablename__ = "calificaciones"

    id_calificacion = Column(String(36), primary_key=True, default=new_uuid)
    id_estudiante = Column(String(36), ForeignKey("estudiantes.id_estudiante"), nullable=False)
    id_grupo = Column(String(36), ForeignKey("grupos.id_grupo"), nullable=False)
    periodo = Column(Integer, nullable=False, default=1)
    tipo = Column(String(50))        # taller, parcial, quiz, examen, tarea, proyecto, oral
    descripcion = Column(String(200))
    valor = Column(Float)            # 0.0 – 5.0
    porcentaje = Column(Float)       # peso de la nota (0 – 100)
    fecha = Column(DateTime, default=datetime.utcnow)

    estudiante = relationship("Estudiante", back_populates="calificaciones")
    grupo = relationship("Grupo", back_populates="calificaciones")


class Archivo(Base):
    __tablename__ = "archivos"

    id_archivo = Column(String(36), primary_key=True, default=new_uuid)
    id_grupo = Column(String(36), ForeignKey("grupos.id_grupo"), nullable=False)
    nombre_archivo = Column(String(255), nullable=False)
    ruta_archivo = Column(String(500), nullable=False)
    tamanio = Column(Integer)
    tipo_mime = Column(String(100))
    fecha_subida = Column(DateTime, default=datetime.utcnow)

    grupo = relationship("Grupo", back_populates="archivos")
