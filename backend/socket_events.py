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

import asyncio
from datetime import datetime

import socketio

from auth import verify_token_for_socket
from database import SessionLocal
from ia import generar_respuesta
from models import (
    Calificacion,
    Docente,
    Estudiante,
    EvaluacionColumna,
    Grupo,
    Mensaje,
    RateLimitCounter,
    Suscripcion,
    UsoMensual,
)
from prompts import (
    LIMITES_DIARIOS,
    MODO_CALIFICACION,
    MODO_DEFAULT,
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
    }.get(modo, modo)


def _consumir_rate_limit(db, docente_id: str, modo: str) -> tuple[bool, int, int]:
    """
    Intenta consumir 1 unidad de la cuota diaria para (docente, hoy, modo).

    Retorna: (ok, count_actual, limite_diario)
    - ok=True si tras incrementar sigue dentro del límite → autoriza generación
    - ok=False si YA estaba en el límite antes de incrementar → bloquea

    Se cuenta AL INICIAR la generación (no al finalizar): así el usuario
    no puede evadir el límite cancelando el streaming a mitad de camino.

    Implementación: buscar o crear el contador del día+modo, incrementar,
    commit. El UniqueConstraint lo protege ante race conditions en la
    creación (dos requests simultáneas del mismo docente); en ese caso
    la segunda re-lee y suma sobre el contador que ya existía.
    """
    limite = LIMITES_DIARIOS.get(modo, 0)
    if limite <= 0:
        # Modo desconocido o sin límite definido — bloqueamos por default
        return False, 0, 0

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
                # No debería pasar — falla dura
                return False, 0, limite
            if contador.count >= limite:
                return False, contador.count, limite
            contador.count += 1
            db.commit()
        return contador.count <= limite, contador.count, limite

    # Contador existente
    if contador.count >= limite:
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

        # 2. Verificar límite del plan (mensual)
        docente = db.query(Docente).filter(Docente.id_docente == docente_id).first()
        if not _verificar_limite_plan(docente, db):
            await sio.emit("ia_error", {
                "message": "Alcanzaste el límite de 10 mensajes/mes del plan Free. "
                           "Actualiza a Pro para mensajes ilimitados."
            }, to=sid)
            return

        # 2b. Verificar rate limit diario POR MODO — se consume al iniciar
        # para que cancelar la respuesta no evada el límite.
        ok, usado, limite = _consumir_rate_limit(db, docente_id, modo)
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

        # 3. Guardar mensaje del docente (con el modo activo)
        msg_docente = Mensaje(
            id_grupo=grupo_id,
            remitente="docente",
            contenido=mensaje_texto,
            modo=modo,
        )
        db.add(msg_docente)
        db.commit()
        db.refresh(msg_docente)

        # 4. Emitir mensaje del docente a la sala
        await sio.emit("new_message", {
            "id_mensaje": msg_docente.id_mensaje,
            "id_grupo": grupo_id,
            "remitente": "docente",
            "contenido": mensaje_texto,
            "modo": modo,
            "timestamp": msg_docente.timestamp.isoformat(),
        }, room=grupo_id)

        # 5. Señal de que la IA está generando (con el modo activo)
        await sio.emit("ia_generando", {"modo": modo}, room=grupo_id)

        # 6. Obtener historial y estudiantes para contexto.
        # Filtramos por modo activo para que la conversación no cruce
        # contextos (ej. socioemocional no ve historial de planeacion).
        # El mensaje recién guardado ya tiene el modo correcto, así que
        # entra en su propia conversación.
        historial = (
            db.query(Mensaje)
            .filter(
                Mensaje.id_grupo == grupo_id,
                Mensaje.modo == modo,
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

        if modo in (MODO_SOCIOEMOCIONAL, MODO_CALIFICACION):
            # Notas registradas por estudiante — sirve para detectar bajos
            # rendimientos en socioemocional y para tener contexto real en
            # calificacion.
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
        )

        # 8. Guardar respuesta completa de la IA (mismo modo del mensaje)
        msg_ia = Mensaje(
            id_grupo=grupo_id,
            remitente="sistema",
            contenido=respuesta_completa,
            modo=modo,
        )
        db.add(msg_ia)
        db.commit()
        db.refresh(msg_ia)

        # 9. Emitir evento de completado (incluye el modo)
        await sio.emit("ia_complete", {
            "id_mensaje": msg_ia.id_mensaje,
            "id_grupo": grupo_id,
            "remitente": "sistema",
            "contenido": respuesta_completa,
            "modo": modo,
            "timestamp": msg_ia.timestamp.isoformat(),
        }, room=grupo_id)

        # 10. Incrementar uso mensual
        _incrementar_uso(docente_id, db)

    except Exception as e:
        print(f"❌ Error en send_message: {e}")
        await sio.emit("ia_error", {"message": "Error generando respuesta. Intenta nuevamente."}, to=sid)

    finally:
        db.close()
