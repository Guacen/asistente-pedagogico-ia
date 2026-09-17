"""
migrate.py — Migraciones de base de datos y seed de datos iniciales.

Se llama desde main.py en el evento startup, justo después de create_tables().
- apply_migrations(): agrega columnas nuevas a tablas existentes (idempotente).
- seed_pro_user(): sube a Plan Pro al usuario de prueba.

Sprint migraciones-aisladas (post-incidente): una sola columna con un tipo
inválido en Postgres (`DATETIME` en vez de `TIMESTAMP`, sesiones_presentacion
.slide_abierto_en) tumbó el arranque COMPLETO de la app en producción — el
startup no llegaba ni a levantar el servidor HTTP, así que Railway nunca
pudo enrutar tráfico. La función a la que pertenecía esa columna
(Presentaciones Interactivas) llevaba días construida para archivarse
detrás de FEATURE_PRESENTACIONES (default False, ver config.py y
presentaciones.py) pero ese PR seguía sin mergear cuando ocurrió el
incidente — la función estaba en producción sin querer, sin que hiciera
falta: un bug en una migración de una función que nadie debería poder
tocar todavía dejó fuera de servicio TODO, incluyendo login, grupos, chat.

Importante: el flag SÓLO apaga la API (/api/presentaciones/*) y la UI —
"tablas y migraciones quedan intactas" es explícito desde que se diseñó
el archivado. `apply_migrations()` corre las migraciones de Presentaciones
SIEMPRE, esté el flag prendido o no. El aislamiento de abajo (_paso) es lo
que realmente evita que un bug como éste vuelva a tumbar el arranque —
el flag resuelve un problema distinto (que la función no sea usable en
producción todavía), no éste.

Por eso cada paso de apply_migrations() corre aislado vía _paso(): si uno
falla, se registra con detalle completo (traceback) en MIGRATION_ERRORS y
el arranque CONTINÚA con los demás — nunca vuelve a morir por una sola
migración rota. MIGRATION_ERRORS se expone en GET /health y GET
/api/version (ver main.py) para que un fallo sea visible sin entrar a los
logs de Railway.
"""

import traceback
from typing import Callable, Dict, List

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from database import Base, engine, SessionLocal
from models import Suscripcion


# ============================================================
# AISLAMIENTO DE MIGRACIONES — ver docstring del módulo
# ============================================================

# Cada entrada: {"paso": "<nombre>", "error": "<mensaje>"}. Se limpia al
# empezar cada apply_migrations() — no acumula entre llamadas repetidas.
MIGRATION_ERRORS: List[Dict[str, str]] = []


def _paso(nombre: str, fn: Callable[[], None]) -> None:
    """
    Corre una migración individual aislada. Si `fn` lanza cualquier
    excepción, se loguea con traceback completo y se registra en
    MIGRATION_ERRORS — pero NUNCA se re-lanza, así que apply_migrations()
    sigue con el siguiente paso en vez de morir.

    Nota sobre pasos dependientes entre sí (documentados inline donde
    aplica, p.ej. "es_admin" debe existir antes del backfill de
    instituciones): si un paso temprano falla, uno posterior que dependa
    de su resultado también va a fallar — eso es esperado y correcto, se
    registra igual como su propio error aislado. Lo que NO puede pasar es
    que cualquiera de los dos tumbe el proceso entero.
    """
    try:
        fn()
    except Exception as exc:
        detalle = traceback.format_exc()
        print(f"❌ Migración '{nombre}' FALLÓ — la app sigue arrancando igual. Detalle:\n{detalle}")
        MIGRATION_ERRORS.append({"paso": nombre, "error": str(exc)})


def _tiene_columna(tabla: str, columna: str) -> bool:
    return columna in [c["name"] for c in inspect(engine).get_columns(tabla)]


# ============================================================
# MIGRACIONES DE ESQUEMA
# ============================================================

def apply_migrations():
    """
    Aplica cambios al esquema que create_all() no puede hacer
    (p.ej. agregar columnas a tablas ya existentes). Cada paso corre
    aislado — ver _paso() y el docstring del módulo.
    """
    MIGRATION_ERRORS.clear()

    # ── calificaciones.id_columna ──────────────────────────────────
    def _paso_calificaciones_id_columna():
        if _tiene_columna("calificaciones", "id_columna"):
            return
        with engine.connect() as conn:
            conn.execute(text(
                "ALTER TABLE calificaciones ADD COLUMN id_columna VARCHAR(36) REFERENCES evaluacion_columnas(id_columna)"
            ))
            conn.commit()
        print("✅ Migración: columna 'id_columna' agregada a 'calificaciones'")
    _paso("calificaciones.id_columna", _paso_calificaciones_id_columna)

    # ── mensajes.modo ──────────────────────────────────────────────
    # Fase B chat multi-modo — mensajes previos quedan como 'planeacion'
    # (era el único modo hasta este sprint).
    def _paso_mensajes_modo():
        if _tiene_columna("mensajes", "modo"):
            return
        with engine.connect() as conn:
            conn.execute(text(
                "ALTER TABLE mensajes ADD COLUMN modo VARCHAR(32) NOT NULL DEFAULT 'planeacion'"
            ))
            conn.commit()
        print("✅ Migración: columna 'modo' agregada a 'mensajes' (default planeacion)")
    _paso("mensajes.modo", _paso_mensajes_modo)

    # ── mensajes.id_estudiante ────────────────────────────────────
    # Fase C PIAR: el chat en modo PIAR es por estudiante, así que
    # cada mensaje se asocia al estudiante para poder filtrar el
    # historial por (grupo, modo, estudiante). NULL para mensajes
    # legacy y para modos != piar — retro-compat total.
    def _paso_mensajes_id_estudiante():
        if _tiene_columna("mensajes", "id_estudiante"):
            return
        with engine.connect() as conn:
            conn.execute(text(
                "ALTER TABLE mensajes ADD COLUMN id_estudiante VARCHAR(36) "
                "REFERENCES estudiantes(id_estudiante)"
            ))
            conn.commit()
        print("✅ Migración: columna 'id_estudiante' agregada a 'mensajes' (nullable)")
    _paso("mensajes.id_estudiante", _paso_mensajes_id_estudiante)

    # ── rate_limit_counter (tabla nueva) ────────────────────────────
    # Se crea por metadata.create_all: SQLAlchemy detecta que la tabla no
    # existe y la crea. Es idempotente y compatible con Postgres y SQLite.
    def _paso_tabla_rate_limit_counter():
        from models import RateLimitCounter  # noqa: F401
        Base.metadata.create_all(bind=engine, tables=[RateLimitCounter.__table__])
    _paso("tabla rate_limit_counter", _paso_tabla_rate_limit_counter)

    # ── piar (tabla nueva) ──────────────────────────────────────────
    # Fase C — Generador de PIAR. Idempotente vía metadata.create_all.
    def _paso_tabla_piar():
        from models import PIAR  # noqa: F401
        Base.metadata.create_all(bind=engine, tables=[PIAR.__table__])
    _paso("tabla piar", _paso_tabla_piar)

    # ── instituciones (tabla nueva) + Docente.id_institucion / rol ──
    # Multi-institución (Issue #5).
    def _paso_tabla_instituciones():
        from models import Institucion  # noqa: F401
        Base.metadata.create_all(bind=engine, tables=[Institucion.__table__])
    _paso("tabla instituciones", _paso_tabla_instituciones)

    def _paso_docentes_id_institucion():
        if _tiene_columna("docentes", "id_institucion"):
            return
        with engine.connect() as conn:
            conn.execute(text(
                "ALTER TABLE docentes ADD COLUMN id_institucion VARCHAR(36) "
                "REFERENCES instituciones(id_institucion)"
            ))
            conn.commit()
        print("✅ Migración: columna 'id_institucion' agregada a 'docentes'")
    _paso("docentes.id_institucion", _paso_docentes_id_institucion)

    def _paso_docentes_rol():
        if _tiene_columna("docentes", "rol"):
            return
        with engine.connect() as conn:
            conn.execute(text(
                "ALTER TABLE docentes ADD COLUMN rol VARCHAR(20) NOT NULL DEFAULT 'docente'"
            ))
            conn.commit()
        print("✅ Migración: columna 'rol' agregada a 'docentes' (default 'docente')")
    _paso("docentes.rol", _paso_docentes_rol)

    # ── Sprint sesiones temáticas ──
    # IMPORTANTE: este paso va ANTES de _backfill_instituciones_unipersonales
    # porque el modelo Docente ya declara `es_admin`. Si el backfill (que
    # hace SELECT docentes.*) corre antes del ALTER TABLE, SQLAlchemy pide
    # una columna que la DB todavía no tiene y ese backfill falla — aislado
    # (ver _paso), pero falla igual: si este paso falla, revisar primero.
    def _paso_docentes_es_admin():
        if _tiene_columna("docentes", "es_admin"):
            return
        with engine.connect() as conn:
            conn.execute(text(
                "ALTER TABLE docentes ADD COLUMN es_admin BOOLEAN NOT NULL DEFAULT FALSE"
            ))
            conn.commit()
        print("✅ Migración: columna 'es_admin' agregada a 'docentes' (default FALSE)")
    _paso("docentes.es_admin", _paso_docentes_es_admin)

    # Tabla chat_sesiones — create_all idempotente
    def _paso_tabla_chat_sesiones():
        from models import ChatSesion  # noqa: F401
        Base.metadata.create_all(bind=engine, tables=[ChatSesion.__table__])
    _paso("tabla chat_sesiones", _paso_tabla_chat_sesiones)

    # Mensaje.id_sesion (FK nullable) — retro-compat: los mensajes viejos
    # quedan con NULL y el frontend los agrupa en "Historial anterior".
    def _paso_mensajes_id_sesion():
        if _tiene_columna("mensajes", "id_sesion"):
            return
        with engine.connect() as conn:
            conn.execute(text(
                "ALTER TABLE mensajes ADD COLUMN id_sesion VARCHAR(36) "
                "REFERENCES chat_sesiones(id_sesion)"
            ))
            conn.commit()
        print("✅ Migración: columna 'id_sesion' agregada a 'mensajes' (nullable)")
    _paso("mensajes.id_sesion", _paso_mensajes_id_sesion)

    # ── Sprint email-verification-consent ──
    # 5 columnas nuevas en docentes + tabla email_verifications.
    # IMPORTANTE: estos pasos van ANTES de _backfill_instituciones_unipersonales
    # porque el backfill hace SELECT docentes.* — si el ALTER TABLE corre
    # después, SQLAlchemy pide columnas que la DB aún no tiene (mismo
    # patrón que 'es_admin' arriba).
    #
    # Grandfathered: los docentes existentes al momento del deploy quedan
    # con email_verificado=TRUE — no queremos cortar sesiones activas. El
    # UPDATE de backfill corre en la MISMA transacción que el ALTER
    # (mismo `with engine.connect()`) a propósito: si el backfill fallara,
    # no queremos la columna agregada sin sus datos migrados a medias.
    def _paso_docentes_email_verificado():
        if _tiene_columna("docentes", "email_verificado"):
            return
        with engine.connect() as conn:
            conn.execute(text(
                "ALTER TABLE docentes ADD COLUMN email_verificado BOOLEAN NOT NULL DEFAULT FALSE"
            ))
            conn.execute(text("UPDATE docentes SET email_verificado = TRUE"))
            conn.commit()
        print("✅ Migración: 'email_verificado' agregada a 'docentes' + backfill grandfathered")
    _paso("docentes.email_verificado", _paso_docentes_email_verificado)

    def _paso_docentes_fecha_verificacion():
        if _tiene_columna("docentes", "fecha_verificacion"):
            return
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE docentes ADD COLUMN fecha_verificacion TIMESTAMP"))
            conn.commit()
        print("✅ Migración: 'fecha_verificacion' agregada a 'docentes'")
    _paso("docentes.fecha_verificacion", _paso_docentes_fecha_verificacion)

    def _paso_docentes_consentimiento_datos():
        if _tiene_columna("docentes", "consentimiento_datos"):
            return
        # NULL para grandfathered — el frontend muestra banner al login
        # y los NUEVOS registros lo setean en TRUE via el flujo del form.
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE docentes ADD COLUMN consentimiento_datos BOOLEAN"))
            conn.commit()
        print("✅ Migración: 'consentimiento_datos' agregada a 'docentes' (NULL para existentes)")
    _paso("docentes.consentimiento_datos", _paso_docentes_consentimiento_datos)

    def _paso_docentes_fecha_consentimiento():
        if _tiene_columna("docentes", "fecha_consentimiento"):
            return
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE docentes ADD COLUMN fecha_consentimiento TIMESTAMP"))
            conn.commit()
        print("✅ Migración: 'fecha_consentimiento' agregada a 'docentes'")
    _paso("docentes.fecha_consentimiento", _paso_docentes_fecha_consentimiento)

    def _paso_docentes_ip_consentimiento():
        if _tiene_columna("docentes", "ip_consentimiento"):
            return
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE docentes ADD COLUMN ip_consentimiento VARCHAR(45)"))
            conn.commit()
        print("✅ Migración: 'ip_consentimiento' agregada a 'docentes'")
    _paso("docentes.ip_consentimiento", _paso_docentes_ip_consentimiento)

    # Tabla email_verifications — create_all idempotente
    def _paso_tabla_email_verifications():
        from models import EmailVerification  # noqa: F401
        Base.metadata.create_all(bind=engine, tables=[EmailVerification.__table__])
    _paso("tabla email_verifications", _paso_tabla_email_verifications)

    # ── Sprint password-reset ──
    def _paso_tabla_password_reset_tokens():
        from models import PasswordResetToken  # noqa: F401
        Base.metadata.create_all(bind=engine, tables=[PasswordResetToken.__table__])
    _paso("tabla password_reset_tokens", _paso_tabla_password_reset_tokens)

    # ── Sprint observaciones-seguimiento ──
    def _paso_tabla_observaciones():
        from models import Observacion  # noqa: F401
        Base.metadata.create_all(bind=engine, tables=[Observacion.__table__])
    _paso("tabla observaciones", _paso_tabla_observaciones)

    # ── Sprint malla-curricular ──
    # 4 tablas nuevas, sin ALTER TABLE necesario — create_all idempotente.
    # Se pasan juntas para que SQLAlchemy resuelva el orden de FKs
    # (DBA / MallaCurricular deben existir antes que MallaItem/SeguimientoDBA).
    def _paso_tablas_malla_curricular():
        from models import DBA, MallaCurricular, MallaItem, SeguimientoDBA  # noqa: F401
        Base.metadata.create_all(bind=engine, tables=[
            DBA.__table__, MallaCurricular.__table__,
            MallaItem.__table__, SeguimientoDBA.__table__,
        ])
    _paso("tablas malla curricular (dbas/mallas/items/seguimiento)", _paso_tablas_malla_curricular)

    def _paso_seed_dbas():
        from seed_dbas import seed_dbas
        seed_dbas()
    _paso("seed_dbas", _paso_seed_dbas)

    # ── Sprint trial-7-dias ──
    # 2 columnas nuevas en docentes. Grandfathered: los docentes que ya
    # existían al momento del deploy quedan con plan='activo' y
    # trial_ends_at=NULL (nunca se bloquean) — mismo criterio que
    # email_verificado arriba. El ALTER TABLE con DEFAULT 'trial' backfillea
    # 'trial' en TODAS las filas existentes automáticamente (comportamiento
    # estándar de ADD COLUMN ... DEFAULT), así que el UPDATE a 'activo' es
    # obligatorio, no defensivo — sin él, cada docente pre-existente
    # quedaría con plan='trial' y trial_ends_at=NULL, que
    # verify_trial_active() trata como vencido de inmediato. Mismo motivo
    # que 'email_verificado' arriba: UPDATE en la misma transacción que el ALTER.
    def _paso_docentes_plan():
        if _tiene_columna("docentes", "plan"):
            return
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE docentes ADD COLUMN plan VARCHAR(20) NOT NULL DEFAULT 'trial'"))
            conn.execute(text("UPDATE docentes SET plan = 'activo'"))
            conn.commit()
        print("✅ Migración: 'plan' agregada a 'docentes' + backfill grandfathered a 'activo'")
    _paso("docentes.plan", _paso_docentes_plan)

    def _paso_docentes_trial_ends_at():
        if _tiene_columna("docentes", "trial_ends_at"):
            return
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE docentes ADD COLUMN trial_ends_at TIMESTAMP"))
            conn.commit()
        print("✅ Migración: 'trial_ends_at' agregada a 'docentes' (NULL para existentes)")
    _paso("docentes.trial_ends_at", _paso_docentes_trial_ends_at)

    # ── Sprint wompi-pagos ──
    def _paso_tabla_transacciones_pago():
        from models import TransaccionPago  # noqa: F401
        Base.metadata.create_all(bind=engine, tables=[TransaccionPago.__table__])
    _paso("tabla transacciones_pago", _paso_tabla_transacciones_pago)

    # ── Sprint seguridad-avanzada ──
    def _paso_tablas_token_blacklist_audit_log():
        from models import AuditLog, TokenBlacklist  # noqa: F401
        Base.metadata.create_all(bind=engine, tables=[
            TokenBlacklist.__table__, AuditLog.__table__,
        ])
    _paso("tablas token_blacklist/audit_log", _paso_tablas_token_blacklist_audit_log)

    # ── Sprint presentaciones-interactivas ──
    # 3 tablas nuevas. Se pasan juntas para que SQLAlchemy resuelva el
    # orden de FKs (Presentacion antes que SesionPresentacion antes que
    # RespuestaPresentacion).
    def _paso_tablas_presentaciones():
        from models import Presentacion, RespuestaPresentacion, SesionPresentacion  # noqa: F401
        Base.metadata.create_all(bind=engine, tables=[
            Presentacion.__table__, SesionPresentacion.__table__, RespuestaPresentacion.__table__,
        ])
    _paso("tablas presentaciones/sesiones/respuestas", _paso_tablas_presentaciones)

    # ── SPRINT 4 — generación asíncrona de presentaciones ──
    # estado/error_generacion en presentaciones: POST /generar ya no
    # bloquea el request esperando a la IA (causaba 502 de Cloudflare
    # con generaciones grandes) — crea la fila con estado='generando' y
    # la actualiza en background.
    def _paso_presentaciones_estado():
        if _tiene_columna("presentaciones", "estado"):
            return
        with engine.connect() as conn:
            conn.execute(text(
                "ALTER TABLE presentaciones ADD COLUMN estado VARCHAR(20) NOT NULL DEFAULT 'lista'"
            ))
            conn.commit()
        print("✅ Migración: columna 'estado' agregada a 'presentaciones' (default 'lista')")
    _paso("presentaciones.estado", _paso_presentaciones_estado)

    def _paso_presentaciones_error_generacion():
        if _tiene_columna("presentaciones", "error_generacion"):
            return
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE presentaciones ADD COLUMN error_generacion TEXT"))
            conn.commit()
        print("✅ Migración: columna 'error_generacion' agregada a 'presentaciones'")
    _paso("presentaciones.error_generacion", _paso_presentaciones_error_generacion)

    # ── SPRINT 6 — puntaje configurable, podio en vivo, PIAR ──
    # Config de puntaje en presentaciones (elegida en el modal de
    # creación, aplica a toda la presentación) + tiempo_limite_ms/
    # puntos_obtenidos en respuestas_presentacion (fijados al responder,
    # nunca recalculados) + tabla nueva de puntaje acumulado por sesión.
    def _paso_presentaciones_modo_puntaje():
        if _tiene_columna("presentaciones", "modo_puntaje"):
            return
        with engine.connect() as conn:
            conn.execute(text(
                "ALTER TABLE presentaciones ADD COLUMN modo_puntaje VARCHAR(20) NOT NULL DEFAULT 'competencia'"
            ))
            conn.commit()
        print("✅ Migración: columna 'modo_puntaje' agregada a 'presentaciones'")
    _paso("presentaciones.modo_puntaje", _paso_presentaciones_modo_puntaje)

    def _paso_presentaciones_tiempo_pregunta_s():
        if _tiene_columna("presentaciones", "tiempo_pregunta_s"):
            return
        with engine.connect() as conn:
            conn.execute(text(
                "ALTER TABLE presentaciones ADD COLUMN tiempo_pregunta_s INTEGER NOT NULL DEFAULT 20"
            ))
            conn.commit()
        print("✅ Migración: columna 'tiempo_pregunta_s' agregada a 'presentaciones'")
    _paso("presentaciones.tiempo_pregunta_s", _paso_presentaciones_tiempo_pregunta_s)

    def _paso_presentaciones_factor_tiempo_piar():
        if _tiene_columna("presentaciones", "factor_tiempo_piar"):
            return
        with engine.connect() as conn:
            conn.execute(text(
                "ALTER TABLE presentaciones ADD COLUMN factor_tiempo_piar FLOAT NOT NULL DEFAULT 1.5"
            ))
            conn.commit()
        print("✅ Migración: columna 'factor_tiempo_piar' agregada a 'presentaciones'")
    _paso("presentaciones.factor_tiempo_piar", _paso_presentaciones_factor_tiempo_piar)

    def _paso_respuestas_tiempo_limite_ms():
        if _tiene_columna("respuestas_presentacion", "tiempo_limite_ms"):
            return
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE respuestas_presentacion ADD COLUMN tiempo_limite_ms INTEGER"))
            conn.commit()
        print("✅ Migración: columna 'tiempo_limite_ms' agregada a 'respuestas_presentacion'")
    _paso("respuestas_presentacion.tiempo_limite_ms", _paso_respuestas_tiempo_limite_ms)

    def _paso_respuestas_puntos_obtenidos():
        if _tiene_columna("respuestas_presentacion", "puntos_obtenidos"):
            return
        with engine.connect() as conn:
            conn.execute(text(
                "ALTER TABLE respuestas_presentacion ADD COLUMN puntos_obtenidos INTEGER NOT NULL DEFAULT 0"
            ))
            conn.commit()
        print("✅ Migración: columna 'puntos_obtenidos' agregada a 'respuestas_presentacion'")
    _paso("respuestas_presentacion.puntos_obtenidos", _paso_respuestas_puntos_obtenidos)

    def _paso_tabla_puntaje_estudiante():
        from models import PuntajeEstudiante  # noqa: F401
        Base.metadata.create_all(bind=engine, tables=[PuntajeEstudiante.__table__])
    _paso("tabla puntaje_estudiante", _paso_tabla_puntaje_estudiante)

    # ── SPRINT 7 — multi-tema por secciones ──
    # `secciones` es METADATA nueva (qué rango de `diapositivas`
    # pertenece a cada tema) — `diapositivas` en sí NUNCA se reescribe
    # acá: correrle los índices rompería slide_index ya guardado en
    # respuestas/sesiones existentes. Presentaciones de antes de este
    # sprint quedan con una sola sección sintética que cubre todo su
    # array tal cual está, sin diapositiva separadora (ese concepto es
    # nuevo, no se inventa retroactivamente).
    def _paso_presentaciones_secciones():
        if _tiene_columna("presentaciones", "secciones"):
            return
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE presentaciones ADD COLUMN secciones JSON"))
            conn.commit()
        print("✅ Migración: columna 'secciones' agregada a 'presentaciones'")
        _backfill_secciones_presentaciones_existentes()
    _paso("presentaciones.secciones (+ backfill)", _paso_presentaciones_secciones)

    # ── SPRINT 8, Parte A — reconexión: tiempo restante server-truthful ──
    def _paso_sesiones_slide_abierto_en():
        if _tiene_columna("sesiones_presentacion", "slide_abierto_en"):
            return
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE sesiones_presentacion ADD COLUMN slide_abierto_en TIMESTAMP"))
            conn.commit()
        print("✅ Migración: columna 'slide_abierto_en' agregada a 'sesiones_presentacion'")
    _paso("sesiones_presentacion.slide_abierto_en", _paso_sesiones_slide_abierto_en)

    # Backfill uni-personal: cada docente sin id_institucion recibe una
    # Institucion nueva a su nombre. Idempotente — si ya tiene, no toca.
    _paso("backfill instituciones unipersonales", _backfill_instituciones_unipersonales)

    # Refrescar inspector para verificar que quedó creada (log claro) —
    # sólo lectura, pero igual aislado: un problema de conectividad acá
    # no debe tumbar el resto del startup tampoco.
    def _paso_verificacion_final():
        inspector = inspect(engine)
        tablas_nuevas = (
            "rate_limit_counter", "piar", "instituciones", "chat_sesiones",
            "email_verifications", "password_reset_tokens", "observaciones",
            "dbas", "mallas_curriculares", "token_blacklist", "audit_log",
            "presentaciones",
        )
        for tabla in tablas_nuevas:
            if tabla in inspector.get_table_names():
                print(f"✅ Migración: tabla '{tabla}' verificada/creada")
    _paso("verificación final de tablas", _paso_verificacion_final)

    if MIGRATION_ERRORS:
        print(
            f"⚠️  Migraciones aplicadas CON {len(MIGRATION_ERRORS)} error(es) — "
            f"ver detalle arriba. La app sigue arrancando; consulta GET /health "
            f"o GET /api/version para ver el resumen sin entrar a los logs."
        )
    else:
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
