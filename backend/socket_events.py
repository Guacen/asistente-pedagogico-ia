"""
Eventos de Socket.io para el chat en tiempo real.

Flujo cuando el docente envía un mensaje:
  1. Frontend emite 'send_message'
  2. Backend guarda mensaje del docente en DB
  3. Backend emite 'new_message' a la sala
  4. Backend emite 'ia_generando'
  5. Backend llama a Claude con streaming
  6. Por cada chunk → emite 'ia_chunk'
  7. Al terminar → guarda respuesta IA en DB → emite 'ia_complete'
  8. Si hay error → emite 'ia_error'
"""

from __future__ import annotations

import asyncio
from datetime import datetime

import socketio

from auth import verify_token_for_socket
from database import SessionLocal
from ia import generar_respuesta
from models import (
    Calificacion,
    ChatSesion,
    Docente,
    Estudiante,
    EvaluacionColumna,
    Grupo,
    Mensaje,
    PIAR,
    RateLimitCounter,
    Suscripcion,
    UsoMensual,
)
from prompts import (
    LIMITES_DIARIOS,
    MODO_CALIFICACION,
    MODO_DEFAULT,
    MODO_OBSERVACIONES,
    MODO_PIAR,
    MODO_SOCIOEMOCIONAL,
    MODOS_ACTIVOS,
    normalizar_modo,
)

# ============================================================
# INSTANCIA DE SOCKET.IO
# ============================================================

sio = socketio.AsyncServer(
    async_mode="asgi",
    cors_allowed_origins="*",    # En producción: cambia a tu dominio
    logger=False,
    engineio_logger=False,
)

# Mapa sid → docente_id (para saber quién está conectado)
_sesiones: dict = {}


# ============================================================
# HELPERS
# ============================================================

def _hoy_iso() -> str:
    """Fecha local ISO (YYYY-MM-DD) usada como clave del rate limit diario."""
    return datetime.utcnow().strftime("%Y-%m-%d")


def _label_modo(modo: str) -> str:
    """Etiqueta legible del modo para mensajes al usuario."""
    return {
        "planeacion": "planeación",
        "socioemocional": "socioemocional",
        "calificacion": "calificación",
        "piar": "PIAR",
        "observaciones": "observaciones",
    }.get(modo, modo)


def _consumir_rate_limit(db, docente_id: str, modo: str, *, es_admin: bool = False) -> tuple[bool, int, int]:
    """
    Intenta consumir 1 unidad de la cuota diaria para (docente, hoy, modo).

    Retorna: (ok, count_actual, limite_diario)
    - ok=True si tras incrementar sigue dentro del límite → autoriza generación
    - ok=False si YA estaba en el límite antes de incrementar → bloquea

    Se cuenta AL INICIAR la generación (no al finalizar): así el usuario
    no puede evadir el límite cancelando el streaming a mitad de camino.

    `es_admin=True` bypasea el bloqueo: el contador sigue incrementando
    para tener métricas del uso, pero siempre autoriza. Se activa por SQL:
      UPDATE docentes SET es_admin = TRUE WHERE email = '<email>';

    Implementación: buscar o crear el contador del día+modo, incrementar,
    commit. El UniqueConstraint lo protege ante race conditions en la
    creación (dos requests simultáneas del mismo docente); en ese caso
    la segunda re-lee y suma sobre el contador que ya existía.
    """
    limite = LIMITES_DIARIOS.get(modo, 0)
    if limite <= 0:
        # Modo desconocido o sin límite definido — bloqueamos por default
        # (salvo admin: para admin siempre autorizamos, incluso sin límite
        # configurado, para no romper el flow por config faltante).
        return (es_admin, 0, 0)

    fecha = _hoy_iso()
    contador = (
        db.query(RateLimitCounter)
        .filter(
            RateLimitCounter.id_docente == docente_id,
            RateLimitCounter.fecha == fecha,
            RateLimitCounter.modo == modo,
        )
        .first()
    )

    if contador is None:
        # Primera consulta del día para este modo → crear con count=1
        contador = RateLimitCounter(
            id_docente=docente_id,
            fecha=fecha,
            modo=modo,
            count=1,
        )
        db.add(contador)
        try:
            db.commit()
        except Exception:
            # Race: alguien más lo creó al mismo tiempo. Rollback y re-leer.
            db.rollback()
            contador = (
                db.query(RateLimitCounter)
                .filter(
                    RateLimitCounter.id_docente == docente_id,
                    RateLimitCounter.fecha == fecha,
                    RateLimitCounter.modo == modo,
                )
                .first()
            )
            if contador is None:
                # No debería pasar — falla dura salvo admin
                return es_admin, 0, limite
            if contador.count >= limite and not es_admin:
                return False, contador.count, limite
            contador.count += 1
            db.commit()
        # Admin siempre autoriza aunque supere el límite
        return (contador.count <= limite or es_admin), contador.count, limite

    # Contador existente
    if contador.count >= limite and not es_admin:
        return False, contador.count, limite

    contador.count += 1
    db.commit()
    return True, contador.count, limite


def _verificar_limite_plan(docente: Docente, db) -> bool:
    """Retorna True si el docente puede enviar más mensajes IA este mes."""
    plan = docente.suscripcion.plan if docente.suscripcion else "free"
    if plan == "pro":
        return True

    # Plan free: máximo 10 mensajes/mes
    ahora = datetime.utcnow()
    uso = db.query(UsoMensual).filter(
        UsoMensual.id_docente == docente.id_docente,
        UsoMensual.mes == ahora.month,
        UsoMensual.anio == ahora.year,
    ).first()

    usados = uso.mensajes_ia_usados if uso else 0
    return usados < 10


def _incrementar_uso(docente_id: str, db) -> None:
    """Incrementa el contador de mensajes IA del mes actual."""
    ahora = datetime.utcnow()
    uso = db.query(UsoMensual).filter(
        UsoMensual.id_docente == docente_id,
        UsoMensual.mes == ahora.month,
        UsoMensual.anio == ahora.year,
    ).first()

    if uso:
        uso.mensajes_ia_usados += 1
    else:
        uso = UsoMensual(
            id_docente=docente_id,
            mes=ahora.month,
            anio=ahora.year,
            mensajes_ia_usados=1,
        )
        db.add(uso)
    db.commit()


# ============================================================
# EVENTOS DE SOCKET.IO
# ============================================================

@sio.event
async def connect(sid, environ, auth):
    """Valida el JWT al conectar."""
    token = (auth or {}).get("token")
    if not token:
        raise ConnectionRefusedError("Token requerido")

    db = SessionLocal()
    try:
        docente = verify_token_for_socket(token, db)
        if not docente:
            raise ConnectionRefusedError("Token inválido")
        _sesiones[sid] = docente.id_docente
        print(f"🟢 Conectado: {docente.email} (sid={sid})")
    finally:
        db.close()


@sio.event
async def disconnect(sid):
    _sesiones.pop(sid, None)
    print(f"🔴 Desconectado: sid={sid}")


@sio.event
async def join_group(sid, data):
    """El docente se une a la sala de su grupo."""
    grupo_id = data.get("grupo_id")
    if not grupo_id:
        return

    docente_id = _sesiones.get(sid)
    db = SessionLocal()
    try:
        grupo = db.query(Grupo).filter(
            Grupo.id_grupo == grupo_id,
            Grupo.id_docente == docente_id,
        ).first()

        if grupo:
            await sio.enter_room(sid, grupo_id)
            print(f"📚 {docente_id} entró al grupo {grupo.nombre_grupo}")
        else:
            await sio.emit("ia_error", {"message": "Grupo no encontrado"}, to=sid)
    finally:
        db.close()


@sio.event
async def leave_group(sid, data):
    grupo_id = data.get("grupo_id")
    if grupo_id:
        await sio.leave_room(sid, grupo_id)


def _titulo_provisional_sesion() -> str:
    return "Sesión " + datetime.utcnow().strftime("%d/%m/%Y %H:%M")


def _resolver_sesion(
    db, grupo_id: str, docente_id: str, modo: str, id_estudiante: str | None,
    id_sesion_pedido: str | None,
) -> tuple["ChatSesion", bool]:
    """
    Devuelve (sesion, creada_ahora). Estrategia:
    - Si el cliente pasó id_sesion, se valida que pertenezca al docente
      y al ámbito (grupo, modo, estudiante) — si sí, se usa; si no,
      404 mediante RuntimeError que el handler convierte a ia_error.
    - Sin id_sesion: se toma la sesión más reciente NO archivada del
      mismo ámbito. Si no hay, se crea una nueva con título provisional.
    """
    if id_sesion_pedido:
        ses = db.query(ChatSesion).filter(
            ChatSesion.id_sesion == id_sesion_pedido,
            ChatSesion.id_docente == docente_id,
            ChatSesion.id_grupo == grupo_id,
            ChatSesion.modo == modo,
        ).first()
        if not ses:
            raise RuntimeError("Sesión no encontrada o no pertenece a este ámbito.")
        # PIAR: la sesión debe apuntar al mismo estudiante que el turno
        if modo == MODO_PIAR and ses.id_estudiante != id_estudiante:
            raise RuntimeError("La sesión pertenece a otro estudiante PIAR.")
        return ses, False

    # Sin id_sesion → buscar la más reciente no archivada del ámbito
    q = db.query(ChatSesion).filter(
        ChatSesion.id_grupo == grupo_id,
        ChatSesion.id_docente == docente_id,
        ChatSesion.modo == modo,
        ChatSesion.archivada.is_(False),
    )
    if modo == MODO_PIAR:
        q = q.filter(ChatSesion.id_estudiante == id_estudiante)
    else:
        q = q.filter(ChatSesion.id_estudiante.is_(None))
    ses = q.order_by(ChatSesion.ultimo_mensaje_en.desc()).first()
    if ses:
        return ses, False

    # No existe ninguna → crear
    ahora = datetime.utcnow()
    ses = ChatSesion(
        id_grupo=grupo_id,
        id_docente=docente_id,
        modo=modo,
        titulo=_titulo_provisional_sesion(),
        id_estudiante=id_estudiante if modo == MODO_PIAR else None,
        creado_en=ahora,
        ultimo_mensaje_en=ahora,
        archivada=False,
    )
    db.add(ses)
    db.commit()
    db.refresh(ses)
    return ses, True


async def _titular_sesion_con_ia(
    db, sesion: "ChatSesion", primer_mensaje_docente: str,
) -> str | None:
    """
    Llama al LLM con un prompt corto pidiendo un título de ≤6 palabras.
    Actualiza sesion.titulo si la respuesta es plausible. Devuelve el
    título nuevo si se cambió, None si algo salió mal. Nunca lanza —
    si el LLM falla, la sesión se queda con el título provisional.
    """
    try:
        import llm  # import local para poder mockear en tests
        prompt = (
            "Devolvé SOLO un título breve (máx 6 palabras, sin comillas, "
            "sin punto final, sin emojis, en español, tono profesional) "
            f"para esta conversación pedagógica que empieza con: «{primer_mensaje_docente}»"
        )
        titulo = await llm.respuesta_completa(
            system_prompt=(
                "Sos un asistente que genera títulos concisos para conversaciones."
            ),
            messages=[{"role": "user", "content": prompt}],
            max_tokens=40,
        )
        titulo_limpio = (titulo or "").strip().strip('"').strip("'")[:80]
        if not titulo_limpio:
            return None
        sesion.titulo = titulo_limpio
        db.commit()
        return titulo_limpio
    except Exception as exc:
        print(f"⚠️  Auto-título falló, se mantiene provisional: {exc}")
        return None


@sio.event
async def send_message(sid, data):
    """
    Recibe mensaje del docente, lo guarda, llama a Claude con streaming
    y emite los chunks en tiempo real.
    """
    grupo_id = data.get("grupo_id")
    mensaje_texto = (data.get("mensaje") or "").strip()
    # Normaliza el modo: si el frontend no lo envía o envía basura → planeacion.
    # Cualquier modo no aceptado explícitamente cae al DEFAULT en vez de fallar,
    # así el pipeline queda a prueba de clientes desactualizados.
    modo_recibido = (data.get("modo") or "").strip().lower()
    modo = normalizar_modo(modo_recibido)
    # id_estudiante — obligatorio si modo=piar, opcional en otros modos.
    estudiante_id = (data.get("id_estudiante") or "").strip() or None
    # id_sesion — opcional; retro-compat: sin él usamos la más reciente o
    # creamos una nueva. Frontend nuevo lo envía siempre.
    id_sesion_pedido = (data.get("id_sesion") or "").strip() or None

    if not grupo_id or not mensaje_texto:
        return

    docente_id = _sesiones.get(sid)
    db = SessionLocal()

    try:
        # 1. Verificar que el grupo pertenece al docente
        grupo = db.query(Grupo).filter(
            Grupo.id_grupo == grupo_id,
            Grupo.id_docente == docente_id,
        ).first()
        if not grupo:
            await sio.emit("ia_error", {"message": "Grupo no encontrado"}, to=sid)
            return

        # 1b. Validar id_estudiante para modo PIAR (obligatorio).
        # Se verifica ANTES del rate limit para no gastar cuota por un
        # request mal formado del frontend.
        estudiante_piar_obj = None
        if modo == MODO_PIAR:
            if not estudiante_id:
                await sio.emit("ia_error", {
                    "message": "Selecciona un estudiante con PIAR antes de continuar.",
                    "code": "piar_sin_estudiante",
                }, to=sid)
                return
            estudiante_piar_obj = (
                db.query(Estudiante)
                .filter(
                    Estudiante.id_estudiante == estudiante_id,
                    Estudiante.id_grupo == grupo_id,
                )
                .first()
            )
            if estudiante_piar_obj is None:
                await sio.emit("ia_error", {
                    "message": "El estudiante no pertenece a este grupo.",
                    "code": "piar_estudiante_ajeno",
                }, to=sid)
                return
            if not estudiante_piar_obj.tiene_piar:
                await sio.emit("ia_error", {
                    "message": (
                        "El estudiante seleccionado no tiene PIAR activo. "
                        "Actívalo primero en la ficha del estudiante."
                    ),
                    "code": "piar_no_activo",
                }, to=sid)
                return

        # 2. Verificar límite del plan (mensual) — observaciones queda
        # exento: son urgentes (Ley 1620/1098) y no deben quedar detrás
        # de un paywall, ni siquiera el tope mensual del plan free.
        docente = db.query(Docente).filter(Docente.id_docente == docente_id).first()
        if modo != MODO_OBSERVACIONES and not _verificar_limite_plan(docente, db):
            await sio.emit("ia_error", {
                "message": "Alcanzaste el límite de 10 mensajes/mes del plan Free. "
                           "Actualiza a Pro para mensajes ilimitados."
            }, to=sid)
            return

        # 2b. Verificar rate limit diario POR MODO — se consume al iniciar
        # para que cancelar la respuesta no evada el límite. Docentes con
        # es_admin=True bypasean el bloqueo (el contador sigue subiendo).
        ok, usado, limite = _consumir_rate_limit(
            db, docente_id, modo, es_admin=bool(getattr(docente, "es_admin", False)),
        )
        if not ok:
            await sio.emit("ia_error", {
                "message": (
                    f"Alcanzaste el límite diario para {_label_modo(modo)} "
                    f"({limite}/día). Vuelve mañana."
                ),
                "code": "rate_limit_diario",
                "modo": modo,
                "usado": usado,
                "limite": limite,
            }, to=sid)
            return

        # id_estudiante para persistir en Mensaje — sólo en modo PIAR
        est_id_a_guardar = estudiante_id if modo == MODO_PIAR else None

        # 2c. Resolver / crear la sesión temática de este turno.
        try:
            sesion, sesion_recien_creada = _resolver_sesion(
                db, grupo_id, docente_id, modo, est_id_a_guardar, id_sesion_pedido,
            )
        except RuntimeError as exc:
            await sio.emit("ia_error", {
                "message": str(exc),
                "code": "sesion_invalida",
            }, to=sid)
            return

        # 3. Guardar mensaje del docente (con el modo activo + id_sesion)
        msg_docente = Mensaje(
            id_grupo=grupo_id,
            remitente="docente",
            contenido=mensaje_texto,
            modo=modo,
            id_estudiante=est_id_a_guardar,
            id_sesion=sesion.id_sesion,
        )
        db.add(msg_docente)
        # Actualizar timestamp de la sesión (para ordenar la lista lateral)
        sesion.ultimo_mensaje_en = msg_docente.timestamp or datetime.utcnow()
        db.commit()
        db.refresh(msg_docente)
        db.refresh(sesion)

        # 4. Emitir mensaje del docente a la sala
        await sio.emit("new_message", {
            "id_mensaje": msg_docente.id_mensaje,
            "id_grupo": grupo_id,
            "remitente": "docente",
            "contenido": mensaje_texto,
            "modo": modo,
            "id_estudiante": est_id_a_guardar,
            "id_sesion": sesion.id_sesion,
            "timestamp": msg_docente.timestamp.isoformat(),
        }, room=grupo_id)

        # 5. Señal de que la IA está generando (con el modo activo)
        await sio.emit("ia_generando", {
            "modo": modo,
            "id_estudiante": est_id_a_guardar,
            "id_sesion": sesion.id_sesion,
        }, room=grupo_id)

        # 6. Obtener historial y estudiantes para contexto.
        # SPRINT SESIONES: el historial se filtra por id_sesion — cada
        # sesión es su propia conversación. Los mensajes de OTRAS sesiones
        # del mismo modo/estudiante NO contaminan el contexto. Los mensajes
        # legacy sin id_sesion tampoco entran (quedaron NULL en migración).
        historial = (
            db.query(Mensaje)
            .filter(
                Mensaje.id_grupo == grupo_id,
                Mensaje.id_sesion == sesion.id_sesion,
            )
            .order_by(Mensaje.timestamp.asc())
            .all()
        )
        estudiantes = (
            db.query(Estudiante)
            .filter(Estudiante.id_grupo == grupo_id)
            .all()
        )

        # 6b. Contexto adicional según modo
        columnas_periodo = None
        notas_por_estudiante = None

        if modo == MODO_CALIFICACION:
            # Columnas del libro para el periodo actual del grupo
            columnas_periodo = (
                db.query(EvaluacionColumna)
                .filter(
                    EvaluacionColumna.id_grupo == grupo_id,
                    EvaluacionColumna.periodo == (grupo.periodo_actual or 1),
                )
                .order_by(EvaluacionColumna.orden, EvaluacionColumna.nombre)
                .all()
            )

        if modo in (MODO_SOCIOEMOCIONAL, MODO_CALIFICACION, MODO_PIAR, MODO_OBSERVACIONES):
            # Notas registradas por estudiante — sirve para detectar bajos
            # rendimientos en socioemocional, para tener contexto real en
            # calificacion, para contextualizar rendimiento en PIAR, y para
            # dar contexto de desempeño al redactar observaciones tipo
            # "academica".
            cals = (
                db.query(Calificacion)
                .filter(Calificacion.id_grupo == grupo_id)
                .all()
            )
            notas_por_estudiante = {}
            for c in cals:
                if c.valor is None:
                    continue
                notas_por_estudiante.setdefault(c.id_estudiante, []).append(c.valor)

        # 6c. Versiones previas de PIAR del estudiante (para dar contexto
        # al asistente sobre iteraciones anteriores del mismo plan).
        piar_versiones_previas = None
        if modo == MODO_PIAR and estudiante_id:
            versiones = (
                db.query(PIAR)
                .filter(PIAR.id_estudiante == estudiante_id)
                .order_by(PIAR.anio.desc(), PIAR.periodo.desc(), PIAR.version.desc())
                .limit(5)
                .all()
            )
            piar_versiones_previas = [
                {
                    "version": p.version,
                    "periodo": p.periodo,
                    "anio": p.anio,
                    "estado": p.estado,
                }
                for p in versiones
            ]

        # 7. Generar respuesta con streaming (system prompt según modo)
        respuesta_completa = ""

        async def on_chunk(chunk: str):
            nonlocal respuesta_completa
            respuesta_completa += chunk
            await sio.emit("ia_chunk", chunk, room=grupo_id)

        await generar_respuesta(
            mensaje_docente=mensaje_texto,
            historial=historial,
            grupo=grupo,
            estudiantes=estudiantes,
            on_chunk=on_chunk,
            modo=modo,
            columnas_periodo_actual=columnas_periodo,
            notas_por_estudiante=notas_por_estudiante,
            estudiante_piar=estudiante_piar_obj,
            piar_versiones_previas=piar_versiones_previas,
        )

        # 8. Guardar respuesta completa de la IA (mismo modo + id_estudiante + id_sesion)
        msg_ia = Mensaje(
            id_grupo=grupo_id,
            remitente="sistema",
            contenido=respuesta_completa,
            modo=modo,
            id_estudiante=est_id_a_guardar,
            id_sesion=sesion.id_sesion,
        )
        db.add(msg_ia)
        sesion.ultimo_mensaje_en = msg_ia.timestamp or datetime.utcnow()
        db.commit()
        db.refresh(msg_ia)
        db.refresh(sesion)

        # 8b. SPRINT SESIONES: si esta era la primera vuelta de una sesión
        # recién creada con título provisional ("Sesión DD/MM/YYYY HH:MM"),
        # pedile al LLM un título ≤6 palabras basado en el primer mensaje.
        # Si falla, la sesión queda con el título provisional. Nunca crashea.
        titulo_nuevo = None
        if sesion_recien_creada and sesion.titulo.startswith("Sesión "):
            titulo_nuevo = await _titular_sesion_con_ia(db, sesion, mensaje_texto)

        # 9. Emitir evento de completado (incluye modo + id_sesion + titulo)
        await sio.emit("ia_complete", {
            "id_mensaje": msg_ia.id_mensaje,
            "id_grupo": grupo_id,
            "remitente": "sistema",
            "contenido": respuesta_completa,
            "modo": modo,
            "id_estudiante": est_id_a_guardar,
            "id_sesion": sesion.id_sesion,
            "titulo_sesion": titulo_nuevo or sesion.titulo,
            "sesion_recien_creada": sesion_recien_creada,
            "timestamp": msg_ia.timestamp.isoformat(),
        }, room=grupo_id)

        # 10. Incrementar uso mensual
        _incrementar_uso(docente_id, db)

    except Exception as e:
        print(f"❌ Error en send_message: {e}")
        await sio.emit("ia_error", {"message": "Error generando respuesta. Intenta nuevamente."}, to=sid)

    finally:
        db.close()
