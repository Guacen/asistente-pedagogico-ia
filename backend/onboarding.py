"""
onboarding.py — sprint primer-uso, Parte D3. Helpers compartidos para
avanzar/completar el estado de onboarding de un docente como efecto
secundario de acciones REALES (crear grupo, agregar estudiante, primera
planeación con IA) — nunca algo que el cliente pueda setear directo, así
nunca queda desincronizado con lo que el docente de verdad hizo, ni se
puede "hacer trampa" para saltarse pasos.

Usado por grupos.py (crear grupo / agregar estudiante / grupo de
ejemplo) y socket_events.py (primera planeación completada de verdad).
"""
from __future__ import annotations

from models import Docente


def avanzar_onboarding_si_aplica(docente: Docente, paso_minimo: int) -> None:
    """
    Adelanta docente.onboarding_paso a paso_minimo si todavía no llegó
    ahí — nunca lo retrocede, nunca lo toca si ya completó el recorrido.
    Corre aunque el docente haya "omitido" el onboarding a propósito:
    así, si después usa el link discreto de "retomar", el paso que ve
    ya refleja lo que de verdad hizo mientras tanto, no queda pegado en
    el paso 1.

    No hace commit — el caller ya está dentro de una transacción que va
    a commitear de todos modos (la del grupo/estudiante que se acaba de
    crear).
    """
    if docente.onboarding_estado == "completado":
        return
    if docente.onboarding_paso < paso_minimo:
        docente.onboarding_paso = paso_minimo


def completar_onboarding_si_aplica(docente: Docente) -> None:
    """
    Se llama tras una interacción de chat exitosa (send_message, DESPUÉS
    de persistir la respuesta de la IA). Si el docente estaba en el
    último paso del recorrido y todavía no completó, lo marca
    completado — es la señal de que "creó su primera planeación con IA
    de verdad", no un checkbox que el frontend pueda marcar solo.
    """
    if docente.onboarding_estado == "pendiente" and docente.onboarding_paso >= 3:
        docente.onboarding_estado = "completado"
