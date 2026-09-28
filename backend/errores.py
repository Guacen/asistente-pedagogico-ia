"""
errores.py — sprint primer-uso: ningún error técnico debe llegar a la
pantalla del docente (nada de stack traces, SQL, nombres de tablas,
tokens, "500 Internal Server Error"), pero tampoco se puede perder la
capacidad de diagnosticar — cada error genera un correlation_id corto
que se muestra al docente Y se loguea con el detalle técnico completo.
Ese mismo ID es lo que Parte D (Reportar un problema) adjunta al
reporte — sin eso, un docente escribiendo "no me funcionó la
planeación" no sirve para investigar nada.

Centralizado acá para que main.py (handler global de excepciones no
capturadas) y cada endpoint con su propio try/except (documento.py,
grupos.py, piar.py, observaciones.py, suscripciones.py,
socket_events.py) usen EXACTAMENTE el mismo formato de ID y el mismo
logger, en vez de que cada uno invente el suyo.
"""
from __future__ import annotations

import logging
import uuid
from typing import Optional

from fastapi import HTTPException

logger = logging.getLogger("errores")


def nuevo_correlation_id() -> str:
    """
    8 caracteres hex en mayúsculas — corto para que un docente lo pueda
    leer/escribir/dictar por teléfono sin transcribir un UUID completo,
    suficientemente único para cruzarlo contra el log del mismo día.
    """
    return uuid.uuid4().hex[:8].upper()


def loggear_error(correlation_id: str, contexto: str, exc: Optional[BaseException] = None) -> None:
    """
    Loguea el detalle técnico completo (traceback incluido si `exc` viene)
    bajo el correlation_id — esto es lo único que debería hacer falta
    grepear en los logs de Railway para investigar un reporte.
    """
    logger.error(f"[{correlation_id}] {contexto}", exc_info=exc is not None)


def error_manejable(
    status_code: int,
    mensaje: str,
    *,
    contexto: str,
    exc: Optional[BaseException] = None,
) -> HTTPException:
    """
    Reemplazo directo de `raise HTTPException(status_code, detail=f"...{exc}")`
    — genera un correlation_id, loguea el detalle técnico REAL (nunca lo
    pierde), y devuelve una HTTPException cuyo detail es sólo lo que un
    docente puede entender + el ID para reportarlo. Mismo shape de
    `detail` en todos lados: {"message": ..., "correlation_id": ...}.
    """
    correlation_id = nuevo_correlation_id()
    loggear_error(correlation_id, contexto, exc)
    return HTTPException(
        status_code=status_code,
        detail={"message": mensaje, "correlation_id": correlation_id},
    )
