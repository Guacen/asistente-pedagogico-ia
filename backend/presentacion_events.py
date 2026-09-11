"""
presentacion_events.py — eventos Socket.io de Presentaciones Interactivas
(sprint presentaciones-interactivas). Registra handlers sobre el mismo
`sio` que usa el chat (socket_events.py); se importa desde main.py sólo
por su efecto lateral de registro (`import presentacion_events`).

Sala Socket.io: "presentacion_{id_sesion}" — el docente y todos los
estudiantes conectados comparten la misma sala; el server difunde con
sio.emit(..., room=sala).

Los estudiantes se conectan SIN JWT (ver socket_events.connect) y sólo
quedan habilitados en una sala tras un presentacion:unirse válido — no
tienen acceso a ningún otro evento del chat.

Toda la lógica de negocio (validar si un slide sigue abierto, calcular
conteos/ranking, cambiar estado) vive en funciones puras de
presentaciones.py, testeadas directo contra la DB sin necesitar una
conexión de socket real. Los handlers acá son deliberadamente delgados:
leen el evento, llaman al helper, emiten el resultado.
"""
from __future__ import annotations

import logging

from database import SessionLocal
from models import RespuestaPresentacion, SesionPresentacion
from presentaciones import (
    TIPOS_PREGUNTA_SOPORTADOS,
    _es_ultima_slide_de_seccion,
    _estudiante_tiene_piar,
    _seccion_de_slide,
    _slide_publico,
    _tiempo_limite_ms,
    calcular_podio,
    calcular_resultado,
    cerrar_slide,
    construir_estado_sincronizacion,
    finalizar_sesion,
    iniciar_slide,
    registrar_respuesta,
)
from security_utils import sanitizar_texto
from socket_events import _estudiantes_presentacion as _estudiantes
from socket_events import sio

logger = logging.getLogger(__name__)


def _sala(id_sesion: str) -> str:
    return f"presentacion_{id_sesion}"


def _contar_estudiantes_sala(id_sesion: str) -> int:
    return sum(1 for v in _estudiantes.values() if v.get("id_sesion") == id_sesion)


# ============================================================
# ESTUDIANTE → SERVIDOR
# ============================================================

@sio.on("presentacion:unirse")
async def presentacion_unirse(sid, data):
    data = data or {}
    codigo = (data.get("codigo") or "").strip().upper()
    nombre = (data.get("nombre") or "").strip()
    # SPRINT 8, Parte A: id de participante generado y persistido en
    # sessionStorage del lado del cliente — se reenvía en cada
    # (re)conexión para que el servidor identifique que es el MISMO
    # estudiante, no uno nuevo. Opcional por compatibilidad con un
    # cliente viejo que todavía no lo mande.
    participante_id = (data.get("participante_id") or "").strip() or None

    if not codigo or not nombre:
        logger.info(
            "presentacion:unirse rechazado — código/nombre faltante (sid=%s, codigo=%r, nombre=%r)",
            sid, codigo, nombre,
        )
        await sio.emit(
            "presentacion:error",
            {"message": "Código y nombre son obligatorios."},
            to=sid,
        )
        return

    db = SessionLocal()
    try:
        sesion = db.query(SesionPresentacion).filter(SesionPresentacion.codigo == codigo).first()
        if not sesion:
            logger.info(
                "presentacion:unirse — código no encontrado (codigo=%s, nombre=%r, sid=%s)",
                codigo, nombre, sid,
            )
            await sio.emit(
                "presentacion:error",
                {"message": "Código de sesión no encontrado."},
                to=sid,
            )
            return
        if sesion.estado == "finalizada":
            logger.info(
                "presentacion:unirse — sesión ya finalizada (codigo=%s, nombre=%r, sesion_id=%s, sid=%s)",
                codigo, nombre, sesion.id_sesion, sid,
            )
            await sio.emit(
                "presentacion:error",
                {"message": "Esta sesión ya finalizó."},
                to=sid,
            )
            return

        nombre_limpio = sanitizar_texto(nombre, 100) or "Anónimo"

        # SPRINT 8, Parte A: si este participante ya tenía OTRA conexión
        # viva (sid distinto) en la misma sesión, era la vieja — el
        # navegador se reconectó con un sid nuevo. La limpiamos para que
        # no quede un fantasma inflando el conteo de la sala ni
        # recibiendo eventos personalizados (tiempo PIAR, tu_resultado)
        # que ya no le sirven a nadie.
        if participante_id:
            for sid_viejo, info in list(_estudiantes.items()):
                if (
                    sid_viejo != sid
                    and info.get("id_sesion") == sesion.id_sesion
                    and info.get("participante_id") == participante_id
                ):
                    _estudiantes.pop(sid_viejo, None)
                    logger.info(
                        "presentacion:unirse — reconexión detectada, se limpia sid viejo "
                        "(participante_id=%s, sid_viejo=%s, sid_nuevo=%s)",
                        participante_id, sid_viejo, sid,
                    )

        _estudiantes[sid] = {
            "nombre": nombre_limpio, "id_sesion": sesion.id_sesion, "participante_id": participante_id,
        }
        await sio.enter_room(sid, _sala(sesion.id_sesion))

        await sio.emit(
            "presentacion:unido",
            {"nombre": nombre_limpio, "estado": sesion.estado, "sesion_id": sesion.id_sesion},
            to=sid,
        )
        logger.info(
            "presentacion:unirse OK (codigo=%s, nombre=%r, sesion_id=%s, sid=%s)",
            codigo, nombre_limpio, sesion.id_sesion, sid,
        )

        # Si el estudiante se une tarde y ya hay un slide abierto, lo
        # pone al día en vez de dejarlo esperando indefinidamente.
        presentacion = sesion.presentacion
        if sesion.slide_abierto and 0 <= sesion.slide_actual < len(presentacion.diapositivas or []):
            slide = presentacion.diapositivas[sesion.slide_actual]
            await sio.emit(
                "presentacion:slide_activo",
                {
                    "slide_data": _slide_publico(slide),
                    "slide_index": sesion.slide_actual,
                    "tiempo_s": slide.get("tiempo_s"),
                },
                to=sid,
            )

        total_respondido = db.query(RespuestaPresentacion).filter(
            RespuestaPresentacion.id_sesion == sesion.id_sesion,
            RespuestaPresentacion.slide_index == sesion.slide_actual,
        ).count()
        await sio.emit(
            "presentacion:nueva_respuesta",
            {
                "total_respondido": total_respondido,
                "total_sala": _contar_estudiantes_sala(sesion.id_sesion),
            },
            room=_sala(sesion.id_sesion),
        )
    except Exception:
        # Sin esto, una falla inesperada acá (DB, etc.) no le llega al
        # estudiante — el botón se queda en "Uniendo…" para siempre porque
        # nunca recibe ni presentacion:unido ni presentacion:error.
        logger.exception(
            "Error inesperado en presentacion:unirse (codigo=%s, nombre=%r, sid=%s)",
            codigo, nombre, sid,
        )
        await sio.emit(
            "presentacion:error",
            {"message": "Ocurrió un error al unirte — intenta de nuevo."},
            to=sid,
        )
    finally:
        db.close()


@sio.on("presentacion:sincronizar")
async def presentacion_sincronizar(sid, data):
    """
    SPRINT 8, Parte A — el cliente pide esto DESPUÉS de (re)emitir
    presentacion:unirse en cada reconexión (ver join.html: visibility-
    change/'connect' de socket.io). Devuelve el estado completo actual
    — diapositiva activa, pregunta abierta y su tiempo restante
    (calculado por el SERVIDOR), si ya respondió, puntaje y posición —
    para que el cliente pinte la pantalla correcta sin importar dónde
    se quedó colgado.
    """
    data = data or {}
    id_sesion = data.get("sesion_id")

    estudiante = _estudiantes.get(sid)
    if not estudiante or estudiante.get("id_sesion") != id_sesion:
        await sio.emit(
            "presentacion:error",
            {"message": "No estás unido a esta sesión."},
            to=sid,
        )
        return

    db = SessionLocal()
    try:
        sesion = db.query(SesionPresentacion).filter(SesionPresentacion.id_sesion == id_sesion).first()
        if not sesion:
            return
        estado = construir_estado_sincronizacion(db, sesion, sesion.presentacion, estudiante["nombre"])
        await sio.emit("presentacion:sincronizado", estado, to=sid)
    finally:
        db.close()


@sio.on("presentacion:responder")
async def presentacion_responder(sid, data):
    data = data or {}
    id_sesion = data.get("sesion_id")
    slide_index = data.get("slide_index")
    respuesta_raw = data.get("respuesta")
    tiempo_ms = data.get("tiempo_respuesta_ms")

    estudiante = _estudiantes.get(sid)
    if not estudiante or estudiante.get("id_sesion") != id_sesion:
        await sio.emit(
            "presentacion:error",
            {"message": "No estás unido a esta sesión."},
            to=sid,
        )
        return
    if not isinstance(slide_index, int) or respuesta_raw is None:
        return

    db = SessionLocal()
    try:
        sesion = db.query(SesionPresentacion).filter(SesionPresentacion.id_sesion == id_sesion).first()
        if not sesion:
            return
        presentacion = sesion.presentacion

        guardada = registrar_respuesta(
            db, sesion, presentacion, slide_index,
            estudiante["nombre"], str(respuesta_raw),
            tiempo_ms if isinstance(tiempo_ms, int) else None,
        )
        if guardada is None:
            await sio.emit(
                "presentacion:error",
                {"message": "Esta pregunta ya cerró — tu respuesta no cuenta."},
                to=sid,
            )
            return

        await sio.emit("presentacion:respuesta_registrada", {}, to=sid)

        total_respondido = db.query(RespuestaPresentacion).filter(
            RespuestaPresentacion.id_sesion == id_sesion,
            RespuestaPresentacion.slide_index == slide_index,
        ).count()
        await sio.emit(
            "presentacion:nueva_respuesta",
            {
                "total_respondido": total_respondido,
                "total_sala": _contar_estudiantes_sala(id_sesion),
            },
            room=_sala(id_sesion),
        )
    finally:
        db.close()


# ============================================================
# DOCENTE → SERVIDOR
# ============================================================

@sio.on("presentacion:iniciar_slide")
async def presentacion_iniciar_slide(sid, data):
    data = data or {}
    id_sesion = data.get("sesion_id")
    slide_index = data.get("slide_index")
    if not isinstance(slide_index, int):
        return

    db = SessionLocal()
    try:
        sesion = db.query(SesionPresentacion).filter(SesionPresentacion.id_sesion == id_sesion).first()
        if not sesion:
            await sio.emit("presentacion:error", {"message": "Sesión no encontrada."}, to=sid)
            return
        presentacion = sesion.presentacion
        if slide_index < 0 or slide_index >= len(presentacion.diapositivas or []):
            return

        iniciar_slide(db, sesion, slide_index)
        slide = presentacion.diapositivas[slide_index]
        await sio.enter_room(sid, _sala(id_sesion))
        slide_publico = _slide_publico(slide)
        tiempo_base_s = slide.get("tiempo_s")

        # Confirmación al docente — su propio control usa el tiempo base
        # (no personalizado; el docente ve todo igual, es quien decide
        # a quién le aplica el ajuste, no al revés).
        await sio.emit(
            "presentacion:slide_activo",
            {"slide_data": slide_publico, "slide_index": slide_index, "tiempo_s": tiempo_base_s},
            to=sid,
        )

        if slide.get("tipo") in TIPOS_PREGUNTA_SOPORTADOS and tiempo_base_s:
            # SPRINT 6, Parte B — cada estudiante recibe SU PROPIO
            # tiempo_s (extendido si tiene PIAR), nunca un broadcast
            # compartido: si todos recibieran el mismo payload, comparar
            # el `tiempo_s` entre compañeros delataría quién tiene el
            # ajuste. El tiempo extendido NUNCA se expone públicamente.
            for sid_estudiante, info in list(_estudiantes.items()):
                if info.get("id_sesion") != id_sesion:
                    continue
                tiene_piar = _estudiante_tiene_piar(db, presentacion.id_grupo, info["nombre"])
                tiempo_efectivo_s = round(_tiempo_limite_ms(presentacion, tiene_piar) / 1000)
                await sio.emit(
                    "presentacion:slide_activo",
                    {"slide_data": slide_publico, "slide_index": slide_index, "tiempo_s": tiempo_efectivo_s},
                    to=sid_estudiante,
                )
        else:
            # Diapositiva sin ajuste de tiempo relevante (poll/nube) —
            # nada que ocultar, un solo broadcast a la sala basta.
            await sio.emit(
                "presentacion:slide_activo",
                {"slide_data": slide_publico, "slide_index": slide_index, "tiempo_s": tiempo_base_s},
                room=_sala(id_sesion),
                skip_sid=sid,
            )
    finally:
        db.close()


@sio.on("presentacion:cerrar_slide")
async def presentacion_cerrar_slide(sid, data):
    data = data or {}
    id_sesion = data.get("sesion_id")

    db = SessionLocal()
    try:
        sesion = db.query(SesionPresentacion).filter(SesionPresentacion.id_sesion == id_sesion).first()
        if not sesion:
            return
        presentacion = sesion.presentacion
        cerrar_slide(db, sesion)

        # "Distribución antes de revelar": conteos por opción + cuál era
        # la correcta — va a la sala completa (docente y estudiantes),
        # no expone puntajes ni nombres de nadie.
        resultado = calcular_resultado(db, sesion, presentacion)
        await sio.emit("presentacion:resultado", resultado, room=_sala(id_sesion))

        # SPRINT 6, Parte C — podio con el ranking completo (nombres +
        # puntaje + cambio de posición) SOLO al docente, vía su room
        # docente_{id} (no la room de la sesión — ahí también están los
        # estudiantes, y "nunca mostrarle el ranking completo al
        # estudiante" es una regla explícita del sprint).
        podio = calcular_podio(db, sesion, presentacion)
        await sio.emit("presentacion:podio", podio, room=f"docente_{presentacion.id_docente}")

        # SPRINT 7, Parte C — "al terminar cada sección, mostrar el
        # podio parcial de esa sección": mismo cálculo (el puntaje es
        # acumulado de TODA la presentación, no se resetea por sección
        # — esto es sólo el MOMENTO en que se muestra), un evento
        # adicional sólo para que el proyector lo distinga visualmente
        # de un cierre de pregunta cualquiera.
        if _es_ultima_slide_de_seccion(presentacion, sesion.slide_actual):
            seccion = _seccion_de_slide(presentacion, sesion.slide_actual)
            await sio.emit(
                "presentacion:podio_seccion",
                {**podio, "seccion_tema": seccion.get("tema") if seccion else None},
                room=f"docente_{presentacion.id_docente}",
            )

        # Feedback personal por estudiante — sólo SU posición/puntos,
        # nunca el ranking de los demás.
        posicion_por_nombre = {e["nombre"]: i for i, e in enumerate(podio["ranking"])}
        for sid_estudiante, info in list(_estudiantes.items()):
            if info.get("id_sesion") != id_sesion:
                continue
            pos = posicion_por_nombre.get(info["nombre"])
            if pos is None:
                continue
            entrada = podio["ranking"][pos]
            respuesta_estudiante = db.query(RespuestaPresentacion).filter(
                RespuestaPresentacion.id_sesion == id_sesion,
                RespuestaPresentacion.slide_index == sesion.slide_actual,
                RespuestaPresentacion.nombre_estudiante == info["nombre"],
            ).first()
            await sio.emit(
                "presentacion:tu_resultado",
                {
                    "acerto": respuesta_estudiante.es_correcta if respuesta_estudiante else None,
                    "puntos_ganados": respuesta_estudiante.puntos_obtenidos if respuesta_estudiante else 0,
                    "puntaje_acumulado": entrada["puntaje_acumulado"],
                    "posicion": pos + 1,
                    "cambio_posicion": entrada["cambio_posicion"],
                },
                to=sid_estudiante,
            )
    finally:
        db.close()


@sio.on("presentacion:finalizar")
async def presentacion_finalizar(sid, data):
    data = data or {}
    id_sesion = data.get("sesion_id")

    db = SessionLocal()
    try:
        sesion = db.query(SesionPresentacion).filter(SesionPresentacion.id_sesion == id_sesion).first()
        if not sesion:
            return
        presentacion = sesion.presentacion
        finalizar_sesion(db, sesion)
        podio_final = calcular_podio(db, sesion, presentacion)

        # Trigger genérico de "se acabó" para ambos lados — la data rica
        # (podio con nombres para el docente, posición propia para cada
        # estudiante) va en eventos separados y dirigidos, mismo
        # criterio de privacidad que presentacion:podio/tu_resultado.
        await sio.emit("presentacion:finalizada", {}, room=_sala(id_sesion))
        await sio.emit(
            "presentacion:podio_final", podio_final, room=f"docente_{presentacion.id_docente}",
        )

        posicion_por_nombre = {e["nombre"]: i for i, e in enumerate(podio_final["ranking"])}
        for sid_estudiante, info in list(_estudiantes.items()):
            if info.get("id_sesion") != id_sesion:
                continue
            pos = posicion_por_nombre.get(info["nombre"])
            entrada = podio_final["ranking"][pos] if pos is not None else None
            await sio.emit(
                "presentacion:tu_resultado_final",
                {
                    "puntaje_acumulado": entrada["puntaje_acumulado"] if entrada else 0,
                    "posicion": (pos + 1) if pos is not None else None,
                    "total_participantes": len(podio_final["ranking"]),
                },
                to=sid_estudiante,
            )

        # Limpieza del estado en memoria de los estudiantes de esta sesión.
        for s in [s for s, v in _estudiantes.items() if v.get("id_sesion") == id_sesion]:
            _estudiantes.pop(s, None)
    finally:
        db.close()
