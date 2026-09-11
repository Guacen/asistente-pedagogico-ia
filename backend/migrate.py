"""
migrate.py — Migraciones de base de datos y seed de datos iniciales.

Se llama desde main.py en el evento startup, justo después de create_tables().
- apply_migrations(): agrega columnas nuevas a tablas existentes (idempotente).
- seed_pro_user(): sube a Plan Pro al usuario de prueba.
"""

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from database import Base, engine, SessionLocal
from models import Suscripcion


# ============================================================
# MIGRACIONES DE ESQUEMA
# ============================================================

def apply_migrations():
    """
    Aplica cambios al esquema que create_all() no puede hacer
    (p.ej. agregar columnas a tablas ya existentes).
    """
    inspector = inspect(engine)
    with engine.connect() as conn:

        # ── calificaciones.id_columna ──────────────────────────────────
        cols_cal = [c["name"] for c in inspector.get_columns("calificaciones")]
        if "id_columna" not in cols_cal:
            conn.execute(text(
                "ALTER TABLE calificaciones ADD COLUMN id_columna VARCHAR(36) REFERENCES evaluacion_columnas(id_columna)"
            ))
            conn.commit()
            print("✅ Migración: columna 'id_columna' agregada a 'calificaciones'")

        # ── mensajes.modo ──────────────────────────────────────────────
        # Fase B chat multi-modo — mensajes previos quedan como 'planeacion'
        # (era el único modo hasta este sprint).
        cols_msg = [c["name"] for c in inspector.get_columns("mensajes")]
        if "modo" not in cols_msg:
            conn.execute(text(
                "ALTER TABLE mensajes ADD COLUMN modo VARCHAR(32) NOT NULL DEFAULT 'planeacion'"
            ))
            conn.commit()
            print("✅ Migración: columna 'modo' agregada a 'mensajes' (default planeacion)")

        # ── mensajes.id_estudiante ────────────────────────────────────
        # Fase C PIAR: el chat en modo PIAR es por estudiante, así que
        # cada mensaje se asocia al estudiante para poder filtrar el
        # historial por (grupo, modo, estudiante). NULL para mensajes
        # legacy y para modos != piar — retro-compat total.
        if "id_estudiante" not in cols_msg:
            conn.execute(text(
                "ALTER TABLE mensajes ADD COLUMN id_estudiante VARCHAR(36) "
                "REFERENCES estudiantes(id_estudiante)"
            ))
            conn.commit()
            print("✅ Migración: columna 'id_estudiante' agregada a 'mensajes' (nullable)")

    # ── rate_limit_counter (tabla nueva) ────────────────────────────
    # Se crea por metadata.create_all: SQLAlchemy detecta que la tabla no
    # existe y la crea. Es idempotente y compatible con Postgres y SQLite.
    # RateLimitCounter viene del import lazy para evitar ciclo circular.
    from models import RateLimitCounter  # noqa: F401
    Base.metadata.create_all(bind=engine, tables=[RateLimitCounter.__table__])

    # ── piar (tabla nueva) ──────────────────────────────────────────
    # Fase C — Generador de PIAR. Idempotente vía metadata.create_all.
    from models import PIAR  # noqa: F401
    Base.metadata.create_all(bind=engine, tables=[PIAR.__table__])

    # ── instituciones (tabla nueva) + Docente.id_institucion + Docente.rol
    # Multi-institución (Issue #5).
    from models import Docente, Institucion  # noqa: F401
    Base.metadata.create_all(bind=engine, tables=[Institucion.__table__])

    # ALTER TABLE docentes ADD COLUMN id_institucion / rol (idempotente).
    cols_doc = [c["name"] for c in inspect(engine).get_columns("docentes")]
    with engine.connect() as conn:
        if "id_institucion" not in cols_doc:
            conn.execute(text(
                "ALTER TABLE docentes ADD COLUMN id_institucion VARCHAR(36) "
                "REFERENCES instituciones(id_institucion)"
            ))
            conn.commit()
            print("✅ Migración: columna 'id_institucion' agregada a 'docentes'")
        if "rol" not in cols_doc:
            conn.execute(text(
                "ALTER TABLE docentes ADD COLUMN rol VARCHAR(20) NOT NULL DEFAULT 'docente'"
            ))
            conn.commit()
            print("✅ Migración: columna 'rol' agregada a 'docentes' (default 'docente')")

    # ── Sprint sesiones temáticas ──
    # IMPORTANTE: este bloque va ANTES de _backfill_instituciones_unipersonales
    # porque el modelo Docente ya declara `es_admin`. Si el backfill (que
    # hace SELECT docentes.*) corre antes del ALTER TABLE, SQLAlchemy pide
    # una columna que la DB todavía no tiene y todo el startup crashea.
    cols_doc_v2 = [c["name"] for c in inspect(engine).get_columns("docentes")]
    with engine.connect() as conn:
        if "es_admin" not in cols_doc_v2:
            conn.execute(text(
                "ALTER TABLE docentes ADD COLUMN es_admin BOOLEAN NOT NULL DEFAULT FALSE"
            ))
            conn.commit()
            print("✅ Migración: columna 'es_admin' agregada a 'docentes' (default FALSE)")

    # Tabla chat_sesiones — create_all idempotente
    from models import ChatSesion  # noqa: F401
    Base.metadata.create_all(bind=engine, tables=[ChatSesion.__table__])

    # Mensaje.id_sesion (FK nullable) — retro-compat: los mensajes viejos
    # quedan con NULL y el frontend los agrupa en "Historial anterior".
    cols_msg = [c["name"] for c in inspect(engine).get_columns("mensajes")]
    with engine.connect() as conn:
        if "id_sesion" not in cols_msg:
            conn.execute(text(
                "ALTER TABLE mensajes ADD COLUMN id_sesion VARCHAR(36) "
                "REFERENCES chat_sesiones(id_sesion)"
            ))
            conn.commit()
            print("✅ Migración: columna 'id_sesion' agregada a 'mensajes' (nullable)")

    # ── Sprint email-verification-consent ──
    # 5 columnas nuevas en docentes + tabla email_verifications.
    # IMPORTANTE: este bloque va ANTES de _backfill_instituciones_unipersonales
    # porque el backfill hace SELECT docentes.* — si el ALTER TABLE corre
    # después, SQLAlchemy pide columnas que la DB aún no tiene y crashea
    # (mismo patrón que ya se documentó para 'es_admin').
    #
    # Grandfathered: los docentes existentes al momento del deploy quedan
    # con email_verificado=TRUE — no queremos cortar sesiones activas.
    cols_doc_v3 = [c["name"] for c in inspect(engine).get_columns("docentes")]
    with engine.connect() as conn:
        if "email_verificado" not in cols_doc_v3:
            conn.execute(text(
                "ALTER TABLE docentes ADD COLUMN email_verificado BOOLEAN NOT NULL DEFAULT FALSE"
            ))
            conn.execute(text("UPDATE docentes SET email_verificado = TRUE"))
            conn.commit()
            print("✅ Migración: 'email_verificado' agregada a 'docentes' + backfill grandfathered")
        if "fecha_verificacion" not in cols_doc_v3:
            conn.execute(text(
                "ALTER TABLE docentes ADD COLUMN fecha_verificacion TIMESTAMP"
            ))
            conn.commit()
            print("✅ Migración: 'fecha_verificacion' agregada a 'docentes'")
        if "consentimiento_datos" not in cols_doc_v3:
            # NULL para grandfathered — el frontend muestra banner al login
            # y los NUEVOS registros lo setean en TRUE via el flujo del form.
            conn.execute(text(
                "ALTER TABLE docentes ADD COLUMN consentimiento_datos BOOLEAN"
            ))
            conn.commit()
            print("✅ Migración: 'consentimiento_datos' agregada a 'docentes' (NULL para existentes)")
        if "fecha_consentimiento" not in cols_doc_v3:
            conn.execute(text(
                "ALTER TABLE docentes ADD COLUMN fecha_consentimiento TIMESTAMP"
            ))
            conn.commit()
            print("✅ Migración: 'fecha_consentimiento' agregada a 'docentes'")
        if "ip_consentimiento" not in cols_doc_v3:
            conn.execute(text(
                "ALTER TABLE docentes ADD COLUMN ip_consentimiento VARCHAR(45)"
            ))
            conn.commit()
            print("✅ Migración: 'ip_consentimiento' agregada a 'docentes'")

    # Tabla email_verifications — create_all idempotente
    from models import EmailVerification  # noqa: F401
    Base.metadata.create_all(bind=engine, tables=[EmailVerification.__table__])

    # ── Sprint password-reset ──
    # Tabla nueva, sin ALTER TABLE necesario — create_all idempotente.
    from models import PasswordResetToken  # noqa: F401
    Base.metadata.create_all(bind=engine, tables=[PasswordResetToken.__table__])

    # ── Sprint observaciones-seguimiento ──
    # Tabla nueva, sin ALTER TABLE necesario — create_all idempotente.
    from models import Observacion  # noqa: F401
    Base.metadata.create_all(bind=engine, tables=[Observacion.__table__])

    # ── Sprint malla-curricular ──
    # 4 tablas nuevas, sin ALTER TABLE necesario — create_all idempotente.
    # Se pasan juntas para que SQLAlchemy resuelva el orden de FKs
    # (DBA / MallaCurricular deben existir antes que MallaItem/SeguimientoDBA).
    from models import DBA, MallaCurricular, MallaItem, SeguimientoDBA  # noqa: F401
    Base.metadata.create_all(bind=engine, tables=[
        DBA.__table__, MallaCurricular.__table__,
        MallaItem.__table__, SeguimientoDBA.__table__,
    ])
    from seed_dbas import seed_dbas
    seed_dbas()

    # ── Sprint trial-7-dias ──
    # 2 columnas nuevas en docentes. Grandfathered: los docentes que ya
    # existían al momento del deploy quedan con plan='activo' y
    # trial_ends_at=NULL (nunca se bloquean) — mismo criterio que
    # email_verificado arriba. El ALTER TABLE con DEFAULT 'trial' backfillea
    # 'trial' en TODAS las filas existentes automáticamente (comportamiento
    # estándar de ADD COLUMN ... DEFAULT), así que el UPDATE a 'activo'
    # de abajo es obligatorio, no defensivo — sin él, cada docente
    # pre-existente quedaría con plan='trial' y trial_ends_at=NULL, que
    # verify_trial_active() trata como vencido de inmediato.
    cols_doc_v4 = [c["name"] for c in inspect(engine).get_columns("docentes")]
    with engine.connect() as conn:
        if "plan" not in cols_doc_v4:
            conn.execute(text(
                "ALTER TABLE docentes ADD COLUMN plan VARCHAR(20) NOT NULL DEFAULT 'trial'"
            ))
            conn.execute(text("UPDATE docentes SET plan = 'activo'"))
            conn.commit()
            print("✅ Migración: 'plan' agregada a 'docentes' + backfill grandfathered a 'activo'")
        if "trial_ends_at" not in cols_doc_v4:
            conn.execute(text(
                "ALTER TABLE docentes ADD COLUMN trial_ends_at TIMESTAMP"
            ))
            conn.commit()
            print("✅ Migración: 'trial_ends_at' agregada a 'docentes' (NULL para existentes)")

    # ── Sprint wompi-pagos ──
    # Tabla nueva, sin ALTER TABLE necesario — create_all idempotente.
    from models import TransaccionPago  # noqa: F401
    Base.metadata.create_all(bind=engine, tables=[TransaccionPago.__table__])

    # ── Sprint seguridad-avanzada ──
    # 2 tablas nuevas, sin ALTER TABLE necesario — create_all idempotente.
    from models import AuditLog, TokenBlacklist  # noqa: F401
    Base.metadata.create_all(bind=engine, tables=[
        TokenBlacklist.__table__, AuditLog.__table__,
    ])

    # ── Sprint presentaciones-interactivas ──
    # 3 tablas nuevas, sin ALTER TABLE necesario — create_all idempotente.
    # Se pasan juntas para que SQLAlchemy resuelva el orden de FKs
    # (Presentacion antes que SesionPresentacion antes que
    # RespuestaPresentacion).
    from models import Presentacion, RespuestaPresentacion, SesionPresentacion  # noqa: F401
    Base.metadata.create_all(bind=engine, tables=[
        Presentacion.__table__, SesionPresentacion.__table__, RespuestaPresentacion.__table__,
    ])

    # ── SPRINT 4 — generación asíncrona de presentaciones ──
    # estado/error_generacion en presentaciones: POST /generar ya no
    # bloquea el request esperando a la IA (causaba 502 de Cloudflare
    # con generaciones grandes) — crea la fila con estado='generando' y
    # la actualiza en background.
    cols_pres = [c["name"] for c in inspect(engine).get_columns("presentaciones")]
    with engine.connect() as conn:
        if "estado" not in cols_pres:
            conn.execute(text(
                "ALTER TABLE presentaciones ADD COLUMN estado VARCHAR(20) NOT NULL DEFAULT 'lista'"
            ))
            conn.commit()
            print("✅ Migración: columna 'estado' agregada a 'presentaciones' (default 'lista')")
        if "error_generacion" not in cols_pres:
            conn.execute(text(
                "ALTER TABLE presentaciones ADD COLUMN error_generacion TEXT"
            ))
            conn.commit()
            print("✅ Migración: columna 'error_generacion' agregada a 'presentaciones'")

    # ── SPRINT 6 — puntaje configurable, podio en vivo, PIAR ──
    # Config de puntaje en presentaciones (elegida en el modal de
    # creación, aplica a toda la presentación) + tiempo_limite_ms/
    # puntos_obtenidos en respuestas_presentacion (fijados al responder,
    # nunca recalculados) + tabla nueva de puntaje acumulado por sesión.
    cols_pres = [c["name"] for c in inspect(engine).get_columns("presentaciones")]
    with engine.connect() as conn:
        if "modo_puntaje" not in cols_pres:
            conn.execute(text(
                "ALTER TABLE presentaciones ADD COLUMN modo_puntaje VARCHAR(20) NOT NULL DEFAULT 'competencia'"
            ))
            conn.commit()
            print("✅ Migración: columna 'modo_puntaje' agregada a 'presentaciones'")
        if "tiempo_pregunta_s" not in cols_pres:
            conn.execute(text(
                "ALTER TABLE presentaciones ADD COLUMN tiempo_pregunta_s INTEGER NOT NULL DEFAULT 20"
            ))
            conn.commit()
            print("✅ Migración: columna 'tiempo_pregunta_s' agregada a 'presentaciones'")
        if "factor_tiempo_piar" not in cols_pres:
            conn.execute(text(
                "ALTER TABLE presentaciones ADD COLUMN factor_tiempo_piar FLOAT NOT NULL DEFAULT 1.5"
            ))
            conn.commit()
            print("✅ Migración: columna 'factor_tiempo_piar' agregada a 'presentaciones'")

    cols_resp = [c["name"] for c in inspect(engine).get_columns("respuestas_presentacion")]
    with engine.connect() as conn:
        if "tiempo_limite_ms" not in cols_resp:
            conn.execute(text(
                "ALTER TABLE respuestas_presentacion ADD COLUMN tiempo_limite_ms INTEGER"
            ))
            conn.commit()
            print("✅ Migración: columna 'tiempo_limite_ms' agregada a 'respuestas_presentacion'")
        if "puntos_obtenidos" not in cols_resp:
            conn.execute(text(
                "ALTER TABLE respuestas_presentacion ADD COLUMN puntos_obtenidos INTEGER NOT NULL DEFAULT 0"
            ))
            conn.commit()
            print("✅ Migración: columna 'puntos_obtenidos' agregada a 'respuestas_presentacion'")

    from models import PuntajeEstudiante  # noqa: F401
    Base.metadata.create_all(bind=engine, tables=[PuntajeEstudiante.__table__])

    # ── SPRINT 7 — multi-tema por secciones ──
    # `secciones` es METADATA nueva (qué rango de `diapositivas`
    # pertenece a cada tema) — `diapositivas` en sí NUNCA se reescribe
    # acá: correrle los índices rompería slide_index ya guardado en
    # respuestas/sesiones existentes. Presentaciones de antes de este
    # sprint quedan con una sola sección sintética que cubre todo su
    # array tal cual está, sin diapositiva separadora (ese concepto es
    # nuevo, no se inventa retroactivamente).
    cols_pres = [c["name"] for c in inspect(engine).get_columns("presentaciones")]
    if "secciones" not in cols_pres:
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE presentaciones ADD COLUMN secciones JSON"))
            conn.commit()
        print("✅ Migración: columna 'secciones' agregada a 'presentaciones'")
        _backfill_secciones_presentaciones_existentes()

    # Backfill uni-personal: cada docente sin id_institucion recibe una
    # Institucion nueva a su nombre. Idempotente — si ya tiene, no toca.
    _backfill_instituciones_unipersonales()

    # Refrescar inspector para verificar que quedó creada (log claro)
    inspector = inspect(engine)
    if "rate_limit_counter" in inspector.get_table_names():
        print("✅ Migración: tabla 'rate_limit_counter' verificada/creada")
    if "piar" in inspector.get_table_names():
        print("✅ Migración: tabla 'piar' verificada/creada")
    if "instituciones" in inspector.get_table_names():
        print("✅ Migración: tabla 'instituciones' verificada/creada")
    if "chat_sesiones" in inspector.get_table_names():
        print("✅ Migración: tabla 'chat_sesiones' verificada/creada")
    if "email_verifications" in inspector.get_table_names():
        print("✅ Migración: tabla 'email_verifications' verificada/creada")
    if "password_reset_tokens" in inspector.get_table_names():
        print("✅ Migración: tabla 'password_reset_tokens' verificada/creada")
    if "observaciones" in inspector.get_table_names():
        print("✅ Migración: tabla 'observaciones' verificada/creada")
    if "dbas" in inspector.get_table_names():
        print("✅ Migración: tabla 'dbas' verificada/creada")
    if "mallas_curriculares" in inspector.get_table_names():
        print("✅ Migración: tabla 'mallas_curriculares' verificada/creada")
    if "token_blacklist" in inspector.get_table_names():
        print("✅ Migración: tabla 'token_blacklist' verificada/creada")
    if "audit_log" in inspector.get_table_names():
        print("✅ Migración: tabla 'audit_log' verificada/creada")
    if "presentaciones" in inspector.get_table_names():
        print("✅ Migración: tabla 'presentaciones' verificada/creada")

    print("✅ Migraciones aplicadas")


def _backfill_secciones_presentaciones_existentes():
    """
    SPRINT 7 — a cada Presentacion con secciones NULL (recién agregada
    la columna) se le sintetiza una sola sección que cubre todo su
    `diapositivas` actual, derivando los conteos de contenido/preguntas
    de lo que YA está guardado ahí (no hace falta preguntarle nada al
    docente ni a la IA). Idempotente vía el filtro IS NULL: una
    presentación nueva creada después de este ALTER ya nace con
    `secciones` poblado por el ORM (default=list en el modelo, o
    poblado explícitamente por el endpoint /generar), así que nunca
    vuelve a entrar acá.
    """
    from models import Presentacion
    from presentaciones import TIPOS_PREGUNTA_SOPORTADOS

    db = SessionLocal()
    try:
        pendientes = db.query(Presentacion).filter(Presentacion.secciones.is_(None)).all()
        if not pendientes:
            print("ℹ️  Backfill secciones: ninguna presentación pendiente")
            return
        for p in pendientes:
            diapositivas = p.diapositivas or []
            n_contenido = sum(1 for d in diapositivas if isinstance(d, dict) and d.get("tipo") == "contenido")
            n_preguntas = sum(
                1 for d in diapositivas if isinstance(d, dict) and d.get("tipo") in TIPOS_PREGUNTA_SOPORTADOS
            )
            p.secciones = [{
                "tema": p.tema,
                "n_slides_contenido": n_contenido,
                "n_preguntas": n_preguntas,
                "inicio": 0,
                "fin": max(len(diapositivas) - 1, 0),
                "estado": p.estado,
                "error_generacion": p.error_generacion,
            }]
        db.commit()
        print(f"✅ Backfill: {len(pendientes)} presentación(es) migrada(s) a una sección única")
    finally:
        db.close()


def _backfill_instituciones_unipersonales():
    """
    Cada docente sin id_institucion recibe una Institucion propia con
    nombre = 'Institución de <nombre docente>'. Rol se preserva; los
    docentes existentes quedan con rol='docente' (default de la columna).

    Idempotente: docentes que ya tienen id_institucion se saltean.
    Race-safe hasta el nivel de "muchos workers arrancando al mismo
    tiempo": el chequeo per-docente es individual y el commit por lote.
    """
    from models import Docente, Institucion
    db = SessionLocal()
    try:
        pendientes = db.query(Docente).filter(Docente.id_institucion.is_(None)).all()
        if not pendientes:
            print("ℹ️  Backfill instituciones: ningún docente pendiente")
            return
        for d in pendientes:
            inst = Institucion(
                nombre=f"Institución de {d.nombre_completo}",
                plan="free",
            )
            db.add(inst)
            db.flush()  # necesito el id antes del assign
            d.id_institucion = inst.id_institucion
        db.commit()
        print(f"✅ Backfill: {len(pendientes)} institución(es) uni-personal(es) creada(s)")
    finally:
        db.close()


# ============================================================
# SEED: USUARIO DE PRUEBA CON PLAN PRO
# ============================================================

def seed_pro_user():
    """
    Asegura que prueba1@prueba.com tenga suscripción Pro activa.
    Idempotente: solo hace cambios si el plan no es 'pro' todavía.
    """
    db: Session = SessionLocal()
    try:
        from models import Docente
        docente = db.query(Docente).filter(Docente.email == "prueba1@prueba.com").first()
        if not docente:
            print("ℹ️  Usuario prueba1@prueba.com no encontrado — se creará al registrarse")
            return

        sus = db.query(Suscripcion).filter(Suscripcion.id_docente == docente.id_docente).first()
        if sus is None:
            sus = Suscripcion(id_docente=docente.id_docente, plan="pro", estado="activa")
            db.add(sus)
            db.commit()
            print("✅ Seed: suscripción Pro creada para prueba1@prueba.com")
        elif sus.plan != "pro":
            sus.plan = "pro"
            sus.estado = "activa"
            db.commit()
            print("✅ Seed: prueba1@prueba.com actualizado a Plan Pro")
        else:
            print("ℹ️  prueba1@prueba.com ya tiene Plan Pro")
    finally:
        db.close()
