"""
Módulo de integración con Claude (Anthropic).

La API Key se lee desde la variable de entorno CLAUDE_API_KEY
definida en el archivo .env

Los system prompts por modo viven en backend/prompts.py — este módulo
solo arma el contexto dinámico (grupo, estudiantes) y lo concatena.
"""

import re
from typing import Callable, List, Optional

import anthropic

from config import settings
from models import Calificacion, Estudiante, EvaluacionColumna, Grupo, Mensaje
from prompts import (
    MODO_CALIFICACION,
    MODO_DEFAULT,
    MODO_SOCIOEMOCIONAL,
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


# ============================================================
# CONTEXTO ESPECÍFICO POR MODO
# ============================================================
#
# Cada modo puede enriquecer el prompt con datos adicionales relevantes
# para su tarea. Los bloques se concatenan al final del contexto general
# del grupo, así el asistente ve primero la info compartida y después la
# info especializada.

def _detectar_codigos_mencionados(
    texto: str,
    codigos: List[str],
) -> List[str]:
    """
    Detecta qué códigos de estudiante del grupo aparecen en el texto libre
    que escribió el docente. Match case-insensitive con word boundary para
    evitar falsos positivos con substrings.

    Asume que los códigos son suficientemente distintivos (típicamente
    alfanuméricos como 'E001', '2024BAS08') — se documentó esta asunción
    en el sprint spec como decisión pragmática para el MVP.
    """
    if not texto or not codigos:
        return []
    texto_norm = texto.lower()
    encontrados: list[str] = []
    for codigo in codigos:
        if not codigo:
            continue
        # \b no funciona bien con caracteres no-word; construyo boundaries manuales
        pat = r"(?<![A-Za-z0-9])" + re.escape(codigo.lower()) + r"(?![A-Za-z0-9])"
        if re.search(pat, texto_norm):
            encontrados.append(codigo)
    # Preserva orden de aparición sin duplicados
    vistos: set[str] = set()
    unicos: list[str] = []
    for c in encontrados:
        if c not in vistos:
            vistos.add(c)
            unicos.append(c)
    return unicos


def _bloque_socioemocional(
    mensaje_texto: str,
    estudiantes: List[Estudiante],
    notas_por_estudiante: Optional[dict[str, List[float]]] = None,
) -> str:
    """
    Contexto adicional para modo socioemocional:
    - Si el docente menciona códigos de estudiantes → detalle enriquecido
      (diagnóstico, ajustes, tiene_piar, resumen de notas)
    - Si no menciona a nadie → estadísticas agregadas del grupo
    """
    codigos = [e.codigo_estudiante for e in estudiantes if e.codigo_estudiante]
    mencionados = _detectar_codigos_mencionados(mensaje_texto, codigos)
    notas_por_estudiante = notas_por_estudiante or {}

    if mencionados:
        est_por_codigo = {e.codigo_estudiante: e for e in estudiantes}
        bloque = "\n═══════════════════════════════════════════\n"
        bloque += "ESTUDIANTES MENCIONADOS POR EL DOCENTE\n"
        bloque += "═══════════════════════════════════════════\n"
        for c in mencionados:
            e = est_por_codigo.get(c)
            if not e:
                continue
            bloque += f"\n• Código: {e.codigo_estudiante}"
            bloque += f"\n  - PIAR: {'Sí' if e.tiene_piar else 'No'}"
            if e.tiene_piar:
                bloque += f"\n  - Diagnóstico: {e.diagnostico or 'No especificado'}"
                bloque += f"\n  - Ajustes actuales: {e.ajustes or 'No especificados'}"
            notas = notas_por_estudiante.get(e.id_estudiante, [])
            if notas:
                prom = round(sum(notas) / len(notas), 2)
                minv = round(min(notas), 1)
                maxv = round(max(notas), 1)
                bloque += (
                    f"\n  - Notas registradas ({len(notas)}): "
                    f"promedio {prom} / min {minv} / max {maxv}"
                )
            else:
                bloque += "\n  - Sin notas registradas aún"
            bloque += "\n"
        return bloque

    # Sin menciones — estadísticas agregadas
    n_total = len(estudiantes)
    n_piar = sum(1 for e in estudiantes if e.tiene_piar)
    bloque = "\n═══════════════════════════════════════════\n"
    bloque += "CONTEXTO SOCIOEMOCIONAL DEL GRUPO\n"
    bloque += "═══════════════════════════════════════════\n"
    bloque += f"\n• Estudiantes registrados: {n_total}"
    bloque += f"\n• Con PIAR: {n_piar} ({round(n_piar/n_total*100) if n_total else 0}%)"

    # Distribución de rendimiento por estudiante (si hay notas)
    if notas_por_estudiante:
        proms = [
            sum(v) / len(v)
            for v in notas_por_estudiante.values()
            if v
        ]
        if proms:
            bajos = sum(1 for p in proms if p < 3.0)
            riesgo = sum(1 for p in proms if 3.0 <= p < 3.5)
            aprobados = sum(1 for p in proms if p >= 3.5)
            bloque += (
                f"\n• Rendimiento (por promedio de notas registradas):"
                f"\n  - Aprobados (≥3.5): {aprobados}"
                f"\n  - En riesgo (3.0–3.4): {riesgo}"
                f"\n  - Reprobados (<3.0): {bajos}"
            )
    bloque += "\n"
    return bloque


def _bloque_calificacion(
    columnas_periodo_actual: List[EvaluacionColumna],
    estudiantes: List[Estudiante],
    periodo_actual: int,
) -> str:
    """
    Contexto adicional para modo calificación:
    - Columnas de evaluación del periodo actual (nombre, tipo, peso ponderado)
    - Estudiantes con PIAR (para que la rúbrica los considere)
    - Recordatorio de escala colombiana
    """
    bloque = "\n═══════════════════════════════════════════\n"
    bloque += "CONTEXTO DE EVALUACIÓN\n"
    bloque += "═══════════════════════════════════════════\n"
    bloque += f"\n• Periodo actual: {periodo_actual}"
    bloque += "\n• Escala colombiana: 1.0–5.0 (Decreto 1290)"
    bloque += "\n  Superior 4.6–5.0 · Alto 4.0–4.5 · Básico 3.0–3.9 · Bajo 1.0–2.9"
    bloque += "\n  Aprobación mínima: 3.0"

    if columnas_periodo_actual:
        peso_total = sum(c.porcentaje or 0 for c in columnas_periodo_actual)
        bloque += (
            f"\n\n• Evaluaciones registradas para el periodo "
            f"({len(columnas_periodo_actual)}, peso total {peso_total:.0f}%):"
        )
        for c in columnas_periodo_actual:
            peso = f"{c.porcentaje:.0f}%" if c.porcentaje else "sin peso"
            tipo = c.tipo or "sin tipo"
            bloque += f"\n  - {c.nombre} · {tipo} · {peso}"
    else:
        bloque += "\n\n• Aún no hay evaluaciones registradas para este periodo."

    piar = [e for e in estudiantes if e.tiene_piar]
    if piar:
        bloque += (
            f"\n\n• Estudiantes con PIAR en este grupo ({len(piar)}) — "
            f"la rúbrica debe incluir ajustes diferenciados:"
        )
        for e in piar:
            bloque += f"\n  - {e.codigo_estudiante}"
            if e.ajustes:
                bloque += f" · ajustes actuales: {e.ajustes[:80]}"
    bloque += "\n"
    return bloque


def construir_system_prompt(
    grupo: Grupo,
    estudiantes: List[Estudiante],
    modo: Optional[str] = None,
    *,
    mensaje_texto: Optional[str] = None,
    columnas_periodo_actual: Optional[List[EvaluacionColumna]] = None,
    notas_por_estudiante: Optional[dict[str, List[float]]] = None,
) -> str:
    """
    Construye el system prompt completo para una llamada a Claude:
      [prompt base + prompt del modo activo] + [contexto general del grupo]
      + [bloque específico del modo, si aplica]

    Args:
        grupo, estudiantes: contexto compartido (todos los modos).
        modo: activa el system prompt específico + el bloque contextual.
        mensaje_texto: texto del docente — usado por socioemocional para
            detectar menciones de estudiantes.
        columnas_periodo_actual: columnas del libro de notas del periodo
            actual — usado por calificacion.
        notas_por_estudiante: dict {id_estudiante: [valores]} — usado por
            socioemocional para dar contexto de rendimiento.

    Si `modo` no se pasa, cae a MODO_DEFAULT (planeacion) — retro-compat total.
    """
    modo_final = normalizar_modo(modo)
    base_y_modo = prompt_para_modo(modo_final)
    contexto_grupo = _bloque_contexto_grupo(grupo, estudiantes)

    # Bloque específico por modo (opcional)
    contexto_extra = ""
    if modo_final == MODO_SOCIOEMOCIONAL:
        contexto_extra = _bloque_socioemocional(
            mensaje_texto or "",
            estudiantes,
            notas_por_estudiante,
        )
    elif modo_final == MODO_CALIFICACION:
        contexto_extra = _bloque_calificacion(
            columnas_periodo_actual or [],
            estudiantes,
            grupo.periodo_actual or 1,
        )

    return f"{base_y_modo}\n{contexto_grupo}{contexto_extra}"


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
    *,
    columnas_periodo_actual: Optional[List[EvaluacionColumna]] = None,
    notas_por_estudiante: Optional[dict[str, List[float]]] = None,
) -> str:
    """
    Llama a Claude con streaming y dispara on_chunk() por cada token recibido.
    Retorna el texto completo al finalizar.

    El `modo` define qué system prompt se activa (planeacion / socioemocional /
    calificacion / piar). Si no se pasa, cae al MODO_DEFAULT — retro-compat
    con callers previos al sprint de modos.

    Kwargs opcionales de contexto extendido:
    - columnas_periodo_actual: usado por modo calificacion
    - notas_por_estudiante: dict {id_estudiante: [valores]} — socioemocional/calificacion
    """
    system_prompt = construir_system_prompt(
        grupo,
        estudiantes,
        modo=modo,
        mensaje_texto=mensaje_docente,
        columnas_periodo_actual=columnas_periodo_actual,
        notas_por_estudiante=notas_por_estudiante,
    )

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
