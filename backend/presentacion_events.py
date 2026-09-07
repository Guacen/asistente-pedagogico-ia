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

from database import SessionLocal
from models import RespuestaPresentacion, SesionPresentacion
from presentaciones import (
    calcular_resultado,
    cerrar_slide,
    finalizar_sesion,
    iniciar_slide,
    registrar_respuesta,
)
from security_utils import sanitizar_texto
from socket_events import _estudiantes_presentacion as _estudiantes
from socket_events import sio


def _sala(id_sesion: str) -> str:
    return f"presentacion_{id_sesion}"


def _slide_publico(slide: dict) -> dict:
    """
    Versión del slide segura para difundir a la sala: nunca incluye
    `correcta` antes de que el docente cierre el slide y se revele el
    resultado (si no, cualquier estudiante podría leer la respuesta
    correcta directamente del payload del evento).
    """
    publico = dict(slide)
    publico.pop("correcta", None)
    return publico


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

    if not codigo or not nombre:
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
            await sio.emit(
                "presentacion:error",
                {"message": "Código de sesión no encontrado."},
                to=sid,
            )
            return
        if sesion.estado == "finalizada":
            await sio.emit(
                "presentacion:error",
                {"message": "Esta sesión ya finalizó."},
                to=sid,
            )
            return

        nombre_limpio = sanitizar_texto(nombre, 100) or "Anónimo"
        _estudiantes[sid] = {"nombre": nombre_limpio, "id_sesion": sesion.id_sesion}
        await sio.enter_room(sid, _sala(sesion.id_sesion))

        await sio.emit(
            "presentacion:unido",
            {"nombre": nombre_limpio, "estado": sesion.estado, "sesion_id": sesion.id_sesion},
            to=sid,
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
        await sio.emit(
            "presentacion:slide_activo",
            {
                "slide_data": _slide_publico(slide),
                "slide_index": slide_index,
                "tiempo_s": slide.get("tiempo_s"),
            },
            room=_sala(id_sesion),
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
        cerrar_slide(db, sesion)
        resultado = calcular_resultado(db, sesion, sesion.presentacion)
        await sio.emit("presentacion:resultado", resultado, room=_sala(id_sesion))
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
        finalizar_sesion(db, sesion)
        await sio.emit("presentacion:finalizada", {}, room=_sala(id_sesion))

        # Limpieza del estado en memoria de los estudiantes de esta sesión.
        for s in [s for s, v in _estudiantes.items() if v.get("id_sesion") == id_sesion]:
            _estudiantes.pop(s, None)
    finally:
        db.close()
