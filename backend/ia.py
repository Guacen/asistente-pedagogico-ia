"""
Módulo de integración con Claude (Anthropic).

La API Key se lee desde la variable de entorno CLAUDE_API_KEY
definida en el archivo .env

Los system prompts por modo viven en backend/prompts.py — este módulo
solo arma el contexto dinámico (grupo, estudiantes) y lo concatena.
"""

from typing import Callable, List, Optional

import anthropic

from config import settings
from models import Estudiante, Grupo, Mensaje
from prompts import (
    MODO_DEFAULT,
    normalizar_modo,
    prompt_para_modo,
)

# Cliente async de Anthropic (usa CLAUDE_API_KEY del .env).
# Si no hay clave real (placeholder 'sk-ant-XXXXXXXXXX'), el cliente se
# instancia igual pero las llamadas fallarán — es responsabilidad del
# endpoint capturar y devolver el error al frontend.
client = anthropic.AsyncAnthropic(api_key=settings.CLAUDE_API_KEY)


def _api_key_configurada() -> bool:
    """
    True si la clave de Claude parece real (no es el placeholder por defecto
    ni está vacía). Se usa para deshabilitar el botón/mostrar mensaje explícito
    en vez de hacer requests que van a fallar.
    """
    key = (settings.CLAUDE_API_KEY or "").strip()
    if not key:
        return False
    if "XXXX" in key or "xxxx" in key:
        return False
    return key.startswith("sk-ant-")


# ============================================================
# CONTEXTO DEL GRUPO — común a todos los modos
# ============================================================

def _bloque_contexto_grupo(grupo: Grupo, estudiantes: List[Estudiante]) -> str:
    """
    Sección de contexto del grupo que se inyecta después del system prompt del modo.
    Incluye datos del grupo + resumen de estudiantes con PIAR.
    """
    piar = [e for e in estudiantes if e.tiene_piar]
    recursos = grupo.recursos_disponibles or []

    ctx = f"""
═══════════════════════════════════════════
CONTEXTO DEL GRUPO
═══════════════════════════════════════════
• Asignatura : {grupo.asignatura}
• Grado      : {grupo.grado}
• Año lectivo: {grupo.anio_lectivo} — Período {grupo.periodo_actual}
• Total estudiantes: {grupo.cantidad_estudiantes}
• Recursos disponibles: {', '.join(recursos) if recursos else 'No especificados'}
"""

    if piar:
        ctx += f"""
═══════════════════════════════════════════
ESTUDIANTES CON PIAR ({len(piar)} estudiante{'s' if len(piar) > 1 else ''})
═══════════════════════════════════════════
"""
        for e in piar:
            ctx += (
                f"\n• Estudiante {e.codigo_estudiante}"
                f"\n  - Diagnóstico : {e.diagnostico or 'No especificado'}"
                f"\n  - Ajustes PIAR: {e.ajustes or 'No especificados'}\n"
            )
    else:
        ctx += "\n• Ningún estudiante tiene PIAR registrado actualmente.\n"

    return ctx


def construir_system_prompt(
    grupo: Grupo,
    estudiantes: List[Estudiante],
    modo: Optional[str] = None,
) -> str:
    """
    Construye el system prompt completo para una llamada a Claude:
      [prompt base + prompt del modo activo] + [contexto del grupo]

    `modo` es opcional para retro-compat con los llamadores previos al sprint
    de modos — si no se pasa, cae a MODO_DEFAULT (planeacion), que preserva
    el comportamiento histórico del asistente.
    """
    modo_final = normalizar_modo(modo)
    base_y_modo = prompt_para_modo(modo_final)
    contexto = _bloque_contexto_grupo(grupo, estudiantes)
    return f"{base_y_modo}\n{contexto}"


# ============================================================
# GENERACIÓN DE RESPUESTA CON STREAMING
# ============================================================

async def generar_respuesta(
    mensaje_docente: str,
    historial: List[Mensaje],
    grupo: Grupo,
    estudiantes: List[Estudiante],
    on_chunk: Callable[[str], None],
    modo: Optional[str] = None,
) -> str:
    """
    Llama a Claude con streaming y dispara on_chunk() por cada token recibido.
    Retorna el texto completo al finalizar.

    El `modo` define qué system prompt se activa (planeacion / socioemocional /
    calificacion / piar). Si no se pasa, cae al MODO_DEFAULT — retro-compat
    con callers previos al sprint de modos.
    """
    system_prompt = construir_system_prompt(grupo, estudiantes, modo=modo)

    # Construir historial de conversación (últimos 20 mensajes)
    messages = []
    for msg in historial[-20:]:
        role = "user" if msg.remitente == "docente" else "assistant"
        # Claude requiere que no haya dos mensajes consecutivos del mismo rol
        if messages and messages[-1]["role"] == role:
            messages[-1]["content"] += "\n\n" + msg.contenido
        else:
            messages.append({"role": role, "content": msg.contenido})

    # Agregar el mensaje actual del docente
    if messages and messages[-1]["role"] == "user":
        messages[-1]["content"] += "\n\n" + mensaje_docente
    else:
        messages.append({"role": "user", "content": mensaje_docente})

    # Llamar a Claude con streaming
    respuesta_completa = ""

    async with client.messages.stream(
        model=settings.CLAUDE_MODEL,
        max_tokens=2048,
        system=system_prompt,
        messages=messages,
    ) as stream:
        async for chunk in stream.text_stream:
            respuesta_completa += chunk
            await on_chunk(chunk)

    return respuesta_completa


# ============================================================
# MENSAJE DE BIENVENIDA / INICIALIZACIÓN DE CONTEXTO
# ============================================================

async def generar_mensaje_bienvenida(grupo: Grupo, estudiantes: List[Estudiante]) -> tuple:
    """
    Genera un mensaje inicial de bienvenida cuando se crea un grupo.
    Claude recibe el contexto completo del grupo y responde con
    sugerencias pedagógicas iniciales. Retorna (msg_docente, msg_ia).
    """
    system_prompt = construir_system_prompt(grupo, estudiantes)
    piar_count = len([e for e in estudiantes if e.tiene_piar])

    msg_docente = (
        f"Acabo de crear el grupo **{grupo.nombre_grupo}** para la asignatura de "
        f"**{grupo.asignatura}**, grado **{grupo.grado}**, año {grupo.anio_lectivo} "
        f"(período {grupo.periodo_actual}). "
        f"El grupo tiene {grupo.cantidad_estudiantes} estudiantes"
        + (f", de los cuales {piar_count} tienen PIAR." if piar_count else ".")
        + " Por favor preséntate brevemente y dame 3 sugerencias concretas para "
        "comenzar a planear mis primeras clases con este grupo de forma inclusiva."
    )

    response = await client.messages.create(
        model=settings.CLAUDE_MODEL,
        max_tokens=800,
        system=system_prompt,
        messages=[{"role": "user", "content": msg_docente}],
    )

    return msg_docente, response.content[0].text
