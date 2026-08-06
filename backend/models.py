import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean, Column, Date, DateTime, Float, ForeignKey,
    Integer, JSON, String, Text
)
from sqlalchemy.orm import relationship

from database import Base


def new_uuid() -> str:
    return str(uuid.uuid4())


class Institucion(Base):
    """
    Institución educativa que agrupa docentes con roles.
    Cada docente pertenece a exactamente una institución (post-migración
    todos los docentes tienen una uni-personal como default retro-compat).

    `plan` controla qué features institucionales están activas:
    - 'free' / 'pro' → institución uni-personal o pequeña, sin roles admin.
    - 'institucional' → habilita rol coordinador y rector.

    Activación manual del plan: el owner cambia institucion.plan en DB
    directamente. No hay flujo de pago en este sprint.
    """
    __tablename__ = "instituciones"

    id_institucion = Column(String(36), primary_key=True, default=new_uuid)
    nombre = Column(String(200), nullable=False)
    nit = Column(String(50))
    ciudad = Column(String(100))
    departamento = Column(String(100))
    plan = Column(String(20), nullable=False, default="free")
    creado_en = Column(DateTime, default=datetime.utcnow)

    docentes = relationship("Docente", back_populates="institucion_obj")


class Docente(Base):
    __tablename__ = "docentes"

    id_docente = Column(String(36), primary_key=True, default=new_uuid)
    nombre_completo = Column(String(200), nullable=False)
    email = Column(String(200), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    # Campo legacy — nombre de institución como texto libre. Se mantiene
    # por retro-compat con datos existentes; el nuevo modelo usa id_institucion.
    institucion = Column(String(200))
    ciudad = Column(String(100))
    departamento = Column(String(100))
    fecha_registro = Column(DateTime, default=datetime.utcnow)

    # ── Multi-institución (Issue #5) ──
    # FK a la nueva tabla instituciones. Nullable en el esquema para
    # retro-compat de esquema; el backfill de migración garantiza que
    # todo docente en producción tenga una institución uni-personal.
    id_institucion = Column(
        String(36),
        ForeignKey("instituciones.id_institucion"),
        nullable=True,
        index=True,
    )
    # Rol dentro de la institución:
    # - 'docente'      → default; comportamiento idéntico al pre-sprint.
    # - 'coordinador'  → puede leer todo lo de su institución (grupos,
    #                    estudiantes, PIARs), no crea grupos ni edita notas.
    # - 'rector'       → todo lo del coordinador + puede cambiar roles
    #                    de otros docentes de su institución.
    rol = Column(String(20), nullable=False, default="docente")

    # ── Admin flag (sesiones sprint) ──
    # Cuando es_admin=True, el rate limit diario por modo no bloquea al
    # docente. El contador sigue incrementando (métricas) pero
    # _consumir_rate_limit siempre autoriza. Se activa manualmente por SQL:
    #   UPDATE docentes SET es_admin = TRUE WHERE email = '<email>';
    es_admin = Column(Boolean, nullable=False, default=False)

    # ── Verificación de email + Consentimiento Ley 1581 ──
    # Sprint email-verification-consent.
    #
    # email_verificado: TRUE tras clicar el link enviado al registrarse.
    # Los docentes existentes al momento del deploy fueron grandfathered
    # via migrate.py (UPDATE docentes SET email_verificado = TRUE WHERE ...).
    # Nuevos registros arrancan en False y no pueden usar /api/auth/me
    # hasta verificar (401 con code="email_no_verificado").
    #
    # consentimiento_datos: TRUE si el docente aceptó la política Ley 1581.
    # NULL para grandfathered — el frontend muestra banner al login para
    # que acepten. False sólo aparece si rechazan explícitamente (no hay
    # UI para eso hoy, queda reservado).
    #
    # ip_consentimiento: guardada para auditoría legal — la Ley 1581 exige
    # poder demostrar que el consentimiento fue otorgado.
    email_verificado = Column(Boolean, nullable=False, default=False)
    fecha_verificacion = Column(DateTime, nullable=True)
    consentimiento_datos = Column(Boolean, nullable=True, default=None)
    fecha_consentimiento = Column(DateTime, nullable=True)
    ip_consentimiento = Column(String(45), nullable=True)  # IPv6 max = 45 chars

    # ── Prueba gratuita 7 días — sprint trial-7-dias ──
    # `plan` acá es un eje DISTINTO de Suscripcion.plan ('free'/'pro', el
    # tier de facturación Stripe) e Institucion.plan ('free', billing a
    # nivel institución). Este `plan` es el estado de ACCESO self-service:
    #   'trial'    → dentro de la ventana de 7 días desde el registro.
    #   'activo'   → nunca se bloquea (docentes grandfathered al deploy de
    #                este sprint, o cualquier cuenta que decidamos eximir
    #                manualmente). trial_ends_at queda NULL para estos.
    #   'expirado' → la ventana de 7 días venció; verify_trial_active()
    #                devuelve 402 en los endpoints de producto.
    # trial_ends_at es naive UTC (no tz-aware) a propósito — TODAS las
    # demás columnas de fecha en este modelo (fecha_registro, etc.) son
    # naive UTC comparadas con datetime.utcnow(); mezclar aware/naive acá
    # sólo introduce un TypeError latente al comparar.
    trial_ends_at = Column(DateTime, nullable=True)
    plan = Column(String(20), nullable=False, default="trial")

    # Relaciones
    grupos = relationship("Grupo", back_populates="docente", cascade="all, delete")
    suscripcion = relationship("Suscripcion", back_populates="docente", uselist=False, cascade="all, delete")
    uso_mensual = relationship("UsoMensual", back_populates="docente", cascade="all, delete")
    # Relationship al objeto Institucion. Se llama `institucion_obj` para
    # NO colisionar con la columna legacy `institucion` (string libre) que
    # documento.py y piar.py leen como texto para el encabezado DOCX.
    institucion_obj = relationship("Institucion", back_populates="docentes")


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


class RateLimitCounter(Base):
    """
    Contador diario de uso del asistente IA por (docente, fecha, modo).
    Se incrementa al INICIAR una generación (no al finalizar), así el
    usuario no puede evadir el límite cancelando la respuesta a mitad.
    """
    __tablename__ = "rate_limit_counter"
    __table_args__ = (
        # Un solo contador por combinación diaria+modo — evita duplicados
        # y permite ON CONFLICT / SELECT FOR UPDATE en el futuro.
        __import__("sqlalchemy").UniqueConstraint(
            "id_docente", "fecha", "modo",
            name="uq_ratelimit_docente_fecha_modo",
        ),
    )

    id_counter = Column(String(36), primary_key=True, default=new_uuid)
    id_docente = Column(
        String(36),
        ForeignKey("docentes.id_docente"),
        nullable=False,
        index=True,
    )
    fecha = Column(String(10), nullable=False, index=True)  # 'YYYY-MM-DD'
    modo = Column(String(32), nullable=False, index=True)
    count = Column(Integer, default=0, nullable=False)


class EmailVerification(Base):
    """
    Tokens de verificación de email. Un docente puede tener N filas
    (por reintentos de reenviar-verificación) — el `verified_at` del
    docente en `docentes.fecha_verificacion` es la fuente de verdad;
    esta tabla es sólo el registro de tokens emitidos.

    El token expira a las 24h; después de esa ventana se ignora y hay
    que pedir reenvío. Se puede purgar por cron los tokens con
    `expires_at < now() - 30 days` para no acumular basura.
    """
    __tablename__ = "email_verifications"

    id_verification = Column(String(36), primary_key=True, default=new_uuid)
    id_docente = Column(
        String(36),
        ForeignKey("docentes.id_docente"),
        nullable=False,
        index=True,
    )
    token = Column(String(64), unique=True, nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False)
    verified_at = Column(DateTime, nullable=True)   # None hasta que se use
    creado_en = Column(DateTime, default=datetime.utcnow, nullable=False)


class PasswordResetToken(Base):
    """
    Tokens de recuperación de contraseña. Mismo patrón que
    `EmailVerification`: un docente puede tener N filas (reintentos de
    "olvidé mi contraseña"); cada token expira a la hora y es de un solo
    uso (`used_at`).

    TTL más corto que el de verificación de email (1h vs 24h) porque un
    link de reset de contraseña es más sensible si queda vivo mucho
    tiempo en una bandeja de entrada comprometida.
    """
    __tablename__ = "password_reset_tokens"

    id_reset = Column(String(36), primary_key=True, default=new_uuid)
    id_docente = Column(
        String(36),
        ForeignKey("docentes.id_docente"),
        nullable=False,
        index=True,
    )
    token = Column(String(64), unique=True, nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime, nullable=True)   # None hasta que se use
    creado_en = Column(DateTime, default=datetime.utcnow, nullable=False)


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
    columnas = relationship("EvaluacionColumna", back_populates="grupo", cascade="all, delete")
    mallas = relationship("MallaCurricular", back_populates="grupo", cascade="all, delete")


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


class ChatSesion(Base):
    """
    Sesión temática dentro de un modo de chat. Reemplaza al "hilo infinito
    por modo" con conversaciones separadas que tienen título propio y no
    contaminan el contexto entre sí.

    Ámbito de una sesión = (id_grupo, modo) + (id_estudiante opcional para
    modo PIAR). El contexto que se envía al LLM en cada mensaje son sólo
    los mensajes de ESTA sesión, no todo el historial del modo.
    """
    __tablename__ = "chat_sesiones"

    id_sesion = Column(String(36), primary_key=True, default=new_uuid)
    id_grupo = Column(
        String(36), ForeignKey("grupos.id_grupo"), nullable=False, index=True,
    )
    id_docente = Column(
        String(36), ForeignKey("docentes.id_docente"), nullable=False, index=True,
    )
    # Mismos valores que Mensaje.modo (planeacion/socioemocional/calificacion/piar).
    modo = Column(String(32), nullable=False, index=True)
    # Estudiante — obligatorio si modo=piar, NULL en otros modos.
    id_estudiante = Column(
        String(36), ForeignKey("estudiantes.id_estudiante"), nullable=True, index=True,
    )
    # Título provisional "Sesión DD/MM/YYYY HH:MM" al crear; se renombra
    # automáticamente después del primer intercambio con el LLM (≤6 palabras).
    titulo = Column(String(80), nullable=False, default="Sesión")
    creado_en = Column(DateTime, default=datetime.utcnow, nullable=False)
    ultimo_mensaje_en = Column(DateTime, default=datetime.utcnow, nullable=False)
    archivada = Column(Boolean, nullable=False, default=False, index=True)


class Mensaje(Base):
    __tablename__ = "mensajes"

    id_mensaje = Column(String(36), primary_key=True, default=new_uuid)
    id_grupo = Column(String(36), ForeignKey("grupos.id_grupo"), nullable=False)
    remitente = Column(String(20), nullable=False)  # 'docente' o 'sistema'
    contenido = Column(Text, nullable=False)
    # Modo del asistente en el que se emitió el mensaje. Valores en
    # prompts.MODOS_ACTIVOS ∪ {'piar'}. Default 'planeacion' preserva la
    # semántica de los mensajes previos al sprint de modos.
    modo = Column(String(32), nullable=False, default="planeacion", index=True)
    # Estudiante al que se refiere el mensaje. NULL para modos != piar.
    # En modo PIAR es obligatorio para poder filtrar el historial por
    # (grupo, modo, estudiante) — cada PIAR es su propia conversación.
    id_estudiante = Column(
        String(36),
        ForeignKey("estudiantes.id_estudiante"),
        nullable=True,
        index=True,
    )
    # Sesión temática (sprint sesiones). Nullable para retro-compat con
    # mensajes anteriores a la introducción de ChatSesion — el frontend
    # los muestra en un panel separado "Historial anterior".
    id_sesion = Column(
        String(36),
        ForeignKey("chat_sesiones.id_sesion"),
        nullable=True,
        index=True,
    )
    timestamp = Column(DateTime, default=datetime.utcnow)

    grupo = relationship("Grupo", back_populates="mensajes")


class Nota(Base):
    __tablename__ = "notas"

    id_nota = Column(String(36), primary_key=True, default=new_uuid)
    id_grupo = Column(String(36), ForeignKey("grupos.id_grupo"), nullable=False)
    contenido = Column(Text, nullable=False)
    fecha_creacion = Column(DateTime, default=datetime.utcnow)

    grupo = relationship("Grupo", back_populates="notas")


class EvaluacionColumna(Base):
    """Columna del libro de notas (representa una evaluación/actividad)."""
    __tablename__ = "evaluacion_columnas"

    id_columna = Column(String(36), primary_key=True, default=new_uuid)
    id_grupo = Column(String(36), ForeignKey("grupos.id_grupo"), nullable=False)
    periodo = Column(Integer, nullable=False, default=1)
    nombre = Column(String(200), nullable=False)
    tipo = Column(String(50), default="taller")   # taller, quiz, parcial, examen, tarea, proyecto, oral
    porcentaje = Column(Float)                    # peso de la columna (0–100)
    orden = Column(Integer, default=0)
    fecha_creacion = Column(DateTime, default=datetime.utcnow)

    grupo = relationship("Grupo", back_populates="columnas")
    calificaciones = relationship("Calificacion", back_populates="columna", cascade="all, delete")


class Calificacion(Base):
    __tablename__ = "calificaciones"

    id_calificacion = Column(String(36), primary_key=True, default=new_uuid)
    id_estudiante = Column(String(36), ForeignKey("estudiantes.id_estudiante"), nullable=False)
    id_grupo = Column(String(36), ForeignKey("grupos.id_grupo"), nullable=False)
    id_columna = Column(String(36), ForeignKey("evaluacion_columnas.id_columna"), nullable=True)
    periodo = Column(Integer, nullable=False, default=1)
    tipo = Column(String(50))        # taller, parcial, quiz, examen, tarea, proyecto, oral
    descripcion = Column(String(200))
    valor = Column(Float)            # 0.0 – 5.0
    porcentaje = Column(Float)       # peso de la nota (0 – 100)
    fecha = Column(DateTime, default=datetime.utcnow)

    estudiante = relationship("Estudiante", back_populates="calificaciones")
    grupo = relationship("Grupo", back_populates="calificaciones")
    columna = relationship("EvaluacionColumna", back_populates="calificaciones")


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


class PIAR(Base):
    """
    Plan Individual de Ajustes Razonables (Decreto 1421 de 2017).

    Un registro por (estudiante, grupo, periodo, año, version). Versionado
    paralelo: nuevas versiones NO borran las anteriores — el docente puede
    generar v2, v3... para el mismo periodo comparando iteraciones.

    Estados:
    - 'borrador' → editable, se puede aprobar
    - 'aprobado' → inmutable, no se puede editar ni desaprobar; una nueva
      versión (v+1) sí se puede crear siempre.

    Denormalización intencional (id_grupo, id_docente): derivables desde
    id_estudiante vía JOIN, pero se guardan para queries frecuentes sin
    JOINs. Confirmado con el owner del proyecto en el sprint spec.

    Sin campo docx_bytes: el DOCX se regenera on-demand desde `contenido`.
    Permite cambiar el template sin migrar datos.
    """
    __tablename__ = "piar"
    __table_args__ = (
        __import__("sqlalchemy").UniqueConstraint(
            "id_estudiante", "id_grupo", "periodo", "anio", "version",
            name="uq_piar_est_grupo_periodo_version",
        ),
    )

    id_piar = Column(String(36), primary_key=True, default=new_uuid)
    id_estudiante = Column(
        String(36),
        ForeignKey("estudiantes.id_estudiante"),
        nullable=False,
        index=True,
    )
    id_grupo = Column(
        String(36),
        ForeignKey("grupos.id_grupo"),
        nullable=False,
        index=True,
    )
    id_docente = Column(
        String(36),
        ForeignKey("docentes.id_docente"),
        nullable=False,
        index=True,
    )
    periodo = Column(Integer, nullable=False)
    anio = Column(Integer, nullable=False)
    version = Column(Integer, nullable=False, default=1)
    # JSON estructurado con las 6 secciones del Decreto 1421.
    # Schema (flat markdown por sección, decisión owner-approved):
    # {
    #   "caracterizacion": "markdown",
    #   "barreras": "markdown",
    #   "ajustes_razonables": "markdown",
    #   "apoyos": "markdown",
    #   "metas": "markdown",
    #   "seguimiento": "markdown"
    # }
    # Secciones no cubiertas por la conversación quedan como
    # "[PENDIENTE — sin información]" — Claude lo marca al sintetizar.
    contenido = Column(JSON, nullable=False, default=dict)
    estado = Column(String(20), nullable=False, default="borrador", index=True)
    creado_en = Column(DateTime, default=datetime.utcnow, nullable=False)
    aprobado_en = Column(DateTime, nullable=True)


class Observacion(Base):
    """
    Observación del Observador del Alumno + seguimiento (Ley 1620 de 2013,
    Decreto 1965 de 2013, Ley 1098 de 2006).

    El docente narra una situación en texto libre (`situacion_descrita`);
    la IA redacta la versión profesional (`observacion_generada`), la
    clasifica según la Ruta de Atención Integral de la Ley 1620
    (`nivel_escalacion`) y sugiere pasos concretos (`acciones_recomendadas`).
    A diferencia del PIAR, es un registro de un solo turno — no requiere
    conversación previa en el chat.

    `id_estudiante` es nullable a propósito: una observación puede ser
    grupal (ej. "el grupo completo tuvo un conflicto en el recreo") sin
    apuntar a un estudiante específico.
    """
    __tablename__ = "observaciones"

    id_observacion = Column(String(36), primary_key=True, default=new_uuid)
    id_estudiante = Column(
        String(36),
        ForeignKey("estudiantes.id_estudiante"),
        nullable=True,
        index=True,
    )
    id_docente = Column(
        String(36),
        ForeignKey("docentes.id_docente"),
        nullable=False,
        index=True,
    )
    id_grupo = Column(
        String(36),
        ForeignKey("grupos.id_grupo"),
        nullable=False,
        index=True,
    )
    # academica / convivencia / familiar / salud / asistencia / piar / logro
    tipo = Column(String(20), nullable=False)
    situacion_descrita = Column(Text, nullable=False)
    observacion_generada = Column(Text, nullable=True)
    # docente / coordinador / orientador / externo / icbf — Ruta de
    # Atención Integral, Ley 1620. "icbf" implica Tipo III (Art. 44 Ley 1098).
    nivel_escalacion = Column(String(20), nullable=False, default="docente")
    acciones_recomendadas = Column(JSON, nullable=True, default=list)
    requiere_seguimiento = Column(Boolean, nullable=False, default=True)
    fecha_seguimiento = Column(Date, nullable=True)
    estado = Column(String(20), nullable=False, default="abierta", index=True)
    creado_en = Column(DateTime, default=datetime.utcnow, nullable=False)


class DBA(Base):
    """
    Derecho Básico de Aprendizaje (MEN Colombia) — sprint malla-curricular.
    Catálogo de referencia, sembrado una vez desde backend/data/dba_seed_data.json
    (252 DBAs: Lenguaje, Ciencias Naturales, Ciencias Sociales, Inglés, Transición
    — grados 1-11 según la asignatura, ver seed_dbas.py).

    Los DBA son metas ANUALES del MEN sin orden prescrito por período — este
    catálogo no impone distribución alguna; eso lo decide MallaCurricular.
    """
    __tablename__ = "dbas"
    __table_args__ = (
        __import__("sqlalchemy").UniqueConstraint(
            "asignatura", "grado", "numero", name="uq_dba_asignatura_grado_numero",
        ),
    )

    id_dba = Column(String(36), primary_key=True, default=new_uuid)
    asignatura = Column(String(50), nullable=False, index=True)
    grado = Column(String(20), nullable=False, index=True)  # "1".."11" o "Transición"
    numero = Column(Integer, nullable=False)
    enunciado = Column(Text, nullable=False)
    evidencias = Column(JSON, nullable=False, default=list)


class MallaCurricular(Base):
    """
    Distribución de los DBA de una (grupo, asignatura) entre los períodos
    académicos del año. `tipo` distingue si la generó la IA ("generada") o
    si el docente la armó a mano ("personalizada" — Ruta B, sprint futuro,
    no implementada todavía).
    """
    __tablename__ = "mallas_curriculares"
    __table_args__ = (
        __import__("sqlalchemy").UniqueConstraint(
            "id_grupo", "asignatura", name="uq_malla_grupo_asignatura",
        ),
    )

    id_malla = Column(String(36), primary_key=True, default=new_uuid)
    id_grupo = Column(
        String(36), ForeignKey("grupos.id_grupo"), nullable=False, index=True,
    )
    asignatura = Column(String(50), nullable=False)
    grado = Column(String(20), nullable=False)
    periodos = Column(Integer, nullable=False, default=4)
    tipo = Column(String(20), nullable=False, default="generada")
    creado_en = Column(DateTime, default=datetime.utcnow, nullable=False)
    actualizado_en = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False,
    )

    grupo = relationship("Grupo", back_populates="mallas")
    items = relationship(
        "MallaItem", back_populates="malla", cascade="all, delete-orphan",
    )


class MallaItem(Base):
    """Un DBA asignado a un período específico dentro de una MallaCurricular."""
    __tablename__ = "malla_items"

    id_item = Column(String(36), primary_key=True, default=new_uuid)
    id_malla = Column(
        String(36), ForeignKey("mallas_curriculares.id_malla"),
        nullable=False, index=True,
    )
    id_dba = Column(String(36), ForeignKey("dbas.id_dba"), nullable=False, index=True)
    periodo = Column(Integer, nullable=False)

    malla = relationship("MallaCurricular", back_populates="items")
    dba = relationship("DBA")


class SeguimientoDBA(Base):
    """
    Registro de si un DBA quedó cubierto en un período dado, para un grupo.
    Independiente de MallaItem a propósito: un docente puede marcar un DBA
    como cubierto aunque no esté en la malla generada (ajuste manual).
    """
    __tablename__ = "seguimiento_dbas"
    __table_args__ = (
        __import__("sqlalchemy").UniqueConstraint(
            "id_grupo", "id_dba", "periodo", name="uq_seguimiento_grupo_dba_periodo",
        ),
    )

    id_seguimiento = Column(String(36), primary_key=True, default=new_uuid)
    id_grupo = Column(
        String(36), ForeignKey("grupos.id_grupo"), nullable=False, index=True,
    )
    id_dba = Column(String(36), ForeignKey("dbas.id_dba"), nullable=False, index=True)
    periodo = Column(Integer, nullable=False)
    cubierto = Column(Boolean, nullable=False, default=False)
    fecha_cubierto = Column(DateTime, nullable=True)
    plan_clase_referencia = Column(Text, nullable=True)

    grupo = relationship("Grupo")
    dba = relationship("DBA")
