"""
Capa de abstracción del proveedor de IA.

El proyecto usa Claude (Anthropic) como proveedor principal y Gemini
(Google) como fallback cuando el owner no tiene créditos en Anthropic.
Este módulo esconde la diferencia entre ambos SDKs para que ia.py y
piar.py no repitan lógica de selección.

Selección (proveedor_activo):
- Si CLAUDE_API_KEY parece real (starts with 'sk-ant-', sin XXXX) → 'claude'
- Elif GOOGLE_API_KEY tiene valor no vacío → 'gemini'
- Else → 'none'

Interfaz:
- proveedor_activo() -> str
- async stream_respuesta(system_prompt, messages, on_chunk, ...) -> str
- async respuesta_completa(system_prompt, messages, ...) -> str

`messages` usa el formato canónico de Claude:
    [{"role": "user"|"assistant", "content": str}, ...]
Los adapters lo traducen al formato de cada SDK.
"""
from __future__ import annotations

from typing import Awaitable, Callable, List, Optional

from config import settings


# ═══════════════════════════════════════════════════════════════
# ERRORES + SELECCIÓN DE PROVEEDOR
# ═══════════════════════════════════════════════════════════════

class ProveedorNoConfiguradoError(RuntimeError):
    """
    Se levanta cuando no hay ningún proveedor de IA configurado.
    El caller (chat, PIAR) debe capturar esto y devolver un error
    explícito al usuario, no una excepción cruda de SDK.
    """


def _claude_configurado() -> bool:
    key = (settings.CLAUDE_API_KEY or "").strip()
    if not key:
        return False
    if "XXXX" in key or "xxxx" in key:
        return False
    return key.startswith("sk-ant-")


def _gemini_configurado() -> bool:
    key = (settings.GOOGLE_API_KEY or "").strip()
    return bool(key)


def proveedor_activo() -> str:
    """
    Retorna 'claude' | 'gemini' | 'none'. Se recalcula en cada llamada,
    sin cache, para respetar monkeypatch en tests y hot-reload en dev.
    """
    if _claude_configurado():
        return "claude"
    if _gemini_configurado():
        return "gemini"
    return "none"


def _asegurar_proveedor() -> str:
    p = proveedor_activo()
    if p == "none":
        raise ProveedorNoConfiguradoError(
            "No hay proveedor de IA configurado. Set ANTHROPIC_API_KEY "
            "(o CLAUDE_API_KEY) o GOOGLE_API_KEY en el entorno."
        )
    return p


# ═══════════════════════════════════════════════════════════════
# CLIENTES — lazy singletons
# ═══════════════════════════════════════════════════════════════

_claude_client = None
_gemini_client = None
_gemini_configured_key: Optional[str] = None


def _get_claude_client():
    global _claude_client
    if _claude_client is None:
        import anthropic
        _claude_client = anthropic.AsyncAnthropic(api_key=settings.CLAUDE_API_KEY)
    return _claude_client


def _get_gemini_client():
    """
    Import y construcción lazy — la dep google-genai es pesada y solo se
    paga si el owner efectivamente eligió Gemini. Se recrea si la env var
    cambió (tests que hacen monkeypatch de GOOGLE_API_KEY).
    """
    global _gemini_client, _gemini_configured_key
    from google import genai
    if _gemini_client is None or _gemini_configured_key != settings.GOOGLE_API_KEY:
        _gemini_client = genai.Client(api_key=settings.GOOGLE_API_KEY)
        _gemini_configured_key = settings.GOOGLE_API_KEY
    return _gemini_client


# ═══════════════════════════════════════════════════════════════
# ADAPTERS — CLAUDE
# ═══════════════════════════════════════════════════════════════

async def _stream_claude(
    system_prompt: str,
    messages: List[dict],
    on_chunk: Callable[[str], Awaitable[None]],
    max_tokens: int,
    model: Optional[str],
) -> str:
    client = _get_claude_client()
    respuesta = ""
    async with client.messages.stream(
        model=model or settings.CLAUDE_MODEL,
        max_tokens=max_tokens,
        system=system_prompt,
        messages=messages,
    ) as stream:
        async for chunk in stream.text_stream:
            respuesta += chunk
            await on_chunk(chunk)
    return respuesta


async def _completa_claude(
    system_prompt: str,
    messages: List[dict],
    max_tokens: int,
    model: Optional[str],
) -> str:
    client = _get_claude_client()
    response = await client.messages.create(
        model=model or settings.CLAUDE_MODEL,
        max_tokens=max_tokens,
        system=system_prompt,
        messages=messages,
    )
    return response.content[0].text


# ═══════════════════════════════════════════════════════════════
# ADAPTERS — GEMINI
# ═══════════════════════════════════════════════════════════════

def _mensajes_a_gemini(messages: List[dict]):
    """
    Traduce el formato canónico Claude {role: user|assistant, content: str}
    al formato del SDK google-genai (types.Content con parts=[Part(text=...)]).
    Import lazy de types para no pagar la dep si el proveedor activo es Claude.
    """
    from google.genai import types
    return [
        types.Content(
            role="model" if m["role"] == "assistant" else "user",
            parts=[types.Part(text=m["content"])],
        )
        for m in messages
    ]


def _gemini_config(system_prompt: str, max_tokens: int):
    from google.genai import types
    return types.GenerateContentConfig(
        system_instruction=system_prompt,
        max_output_tokens=max_tokens,
    )


async def _stream_gemini(
    system_prompt: str,
    messages: List[dict],
    on_chunk: Callable[[str], Awaitable[None]],
    max_tokens: int,
    model: Optional[str],
) -> str:
    client = _get_gemini_client()
    contenido = _mensajes_a_gemini(messages)
    respuesta = ""
    # SDK nuevo: client.aio.models.generate_content_stream(...) es una
    # corutina que resuelve a un async iterator de chunks; cada chunk.text
    # es el delta del token generado. Algunos chunks vienen sin .text
    # (metadata de safety, function-call, etc.) — se saltan.
    stream = await client.aio.models.generate_content_stream(
        model=model or settings.GEMINI_MODEL,
        contents=contenido,
        config=_gemini_config(system_prompt, max_tokens),
    )
    async for chunk in stream:
        try:
            texto = chunk.text
        except Exception:
            continue
        if texto:
            respuesta += texto
            await on_chunk(texto)
    return respuesta


async def _completa_gemini(
    system_prompt: str,
    messages: List[dict],
    max_tokens: int,
    model: Optional[str],
) -> str:
    client = _get_gemini_client()
    contenido = _mensajes_a_gemini(messages)
    response = await client.aio.models.generate_content(
        model=model or settings.GEMINI_MODEL,
        contents=contenido,
        config=_gemini_config(system_prompt, max_tokens),
    )
    return response.text


# ═══════════════════════════════════════════════════════════════
# API PÚBLICA
# ═══════════════════════════════════════════════════════════════

async def stream_respuesta(
    system_prompt: str,
    messages: List[dict],
    on_chunk: Callable[[str], Awaitable[None]],
    *,
    max_tokens: int = 2048,
    model: Optional[str] = None,
) -> str:
    """Streaming con callback por chunk. Levanta ProveedorNoConfiguradoError."""
    p = _asegurar_proveedor()
    if p == "claude":
        return await _stream_claude(system_prompt, messages, on_chunk, max_tokens, model)
    return await _stream_gemini(system_prompt, messages, on_chunk, max_tokens, model)


async def respuesta_completa(
    system_prompt: str,
    messages: List[dict],
    *,
    max_tokens: int = 4096,
    model: Optional[str] = None,
) -> str:
    """Single-shot, sin streaming. Levanta ProveedorNoConfiguradoError."""
    p = _asegurar_proveedor()
    if p == "claude":
        return await _completa_claude(system_prompt, messages, max_tokens, model)
    return await _completa_gemini(system_prompt, messages, max_tokens, model)
