"""
Módulo de integración con Claude (Anthropic).

La API Key se lee desde la variable de entorno CLAUDE_API_KEY
definida en el archivo .env
"""

from typing import Callable, List

import anthropic

from config import settings
from models import Estudiante, Grupo, Mensaje

# Cliente async de Anthropic (usa CLAUDE_API_KEY del .env)
client = anthropic.AsyncAnthropic(api_key=settings.CLAUDE_API_KEY)


# ============================================================
# SYSTEM PROMPT PEDAGÓGICO
# ============================================================

def construir_system_prompt(grupo: Grupo, estudiantes: List[Estudiante]) -> str:
    """
    Construye el system prompt contextualizado para el grupo.
    Incluye información sobre estudiantes con PIAR para orientar
    las respuestas pedagógicas.
    """
    piar = [e for e in estudiantes if e.tiene_piar]
    recursos = grupo.recursos_disponibles or []

    prompt = f"""Eres un asistente pedagógico especializado en educación inclusiva para Colombia.
Apoyas a docentes de educación básica y media en la planificación de clases adaptadas.

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
        prompt += f"""═══════════════════════════════════════════
ESTUDIANTES CON PIAR ({len(piar)} estudiante{'s' if len(piar) > 1 else ''})
═══════════════════════════════════════════
"""
        for e in piar:
            prompt += f"""
• Estudiante {e.codigo_estudiante}
  - Diagnóstico : {e.diagnostico or 'No especificado'}
  - Ajustes PIAR: {e.ajustes or 'No especificados'}
"""
    else:
        prompt += "• Ningún estudiante tiene PIAR registrado actualmente.\n"

    prompt += """
═══════════════════════════════════════════
TU ROL Y FORMA DE RESPONDER
═══════════════════════════════════════════
1. Ayuda al docente a planear clases INCLUSIVAS basadas en DUA
   (Diseño Universal para el Aprendizaje).
2. Sugiere estrategias concretas y aplicables para los estudiantes con PIAR.
3. Diseña evaluaciones adaptadas cuando se solicite.
4. Propón actividades diferenciadas según los niveles del grupo.
5. Brinda fundamentación pedagógica respaldada por teoría.
6. Considera siempre el contexto de las instituciones educativas públicas colombianas.

FORMATO:
- Responde siempre en español.
- Usa markdown para estructurar (listas, negritas, encabezados).
- Sé concreto y práctico; evita respuestas genéricas.
- Si diseñas actividades, incluye tiempo estimado y materiales.
- Si hay estudiantes con PIAR, incluye SIEMPRE una sección de adaptaciones específicas.
"""

    return prompt


# ============================================================
# GENERACIÓN DE RESPUESTA CON STREAMING
# ============================================================

async def generar_respuesta(
    mensaje_docente: str,
    historial: List[Mensaje],
    grupo: Grupo,
    estudiantes: List[Estudiante],
    on_chunk: Callable[[str], None],
) -> str:
    """
    Llama a Claude con streaming y dispara on_chunk() por cada token recibido.
    Retorna el texto completo al finalizar.
    """
    system_prompt = construir_system_prompt(grupo, estudiantes)

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
