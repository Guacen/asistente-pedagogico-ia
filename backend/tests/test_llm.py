"""
llm.py — selección de proveedor y contrato de las funciones públicas.

Cubre:
- proveedor_activo() prioriza Claude sobre Gemini cuando ambos existen.
- Fallback a Gemini cuando Claude no está configurado.
- 'none' cuando ninguno está configurado.
- stream_respuesta/respuesta_completa levantan ProveedorNoConfiguradoError
  cuando no hay proveedor.
- El adapter delega en Claude o Gemini según proveedor_activo().

Ningún test hace requests reales a Claude o Gemini — todo se mockea a
nivel de los helpers _stream_* / _completa_* de llm.py.
"""
from __future__ import annotations

import asyncio

import pytest


def _set_keys(monkeypatch, claude: str, google: str):
    from config import settings
    monkeypatch.setattr(settings, "CLAUDE_API_KEY", claude)
    monkeypatch.setattr(settings, "GOOGLE_API_KEY", google)


# ═══════════════════════════════════════════════════════════════
# proveedor_activo
# ═══════════════════════════════════════════════════════════════

def test_proveedor_claude_cuando_clave_es_real(monkeypatch):
    import llm
    _set_keys(monkeypatch, "sk-ant-real-clave-aqui", "")
    assert llm.proveedor_activo() == "claude"


def test_proveedor_claude_placeholder_no_cuenta(monkeypatch):
    import llm
    _set_keys(monkeypatch, "sk-ant-XXXXXXXXXX", "")
    assert llm.proveedor_activo() == "none"


def test_fallback_a_gemini_sin_clave_claude(monkeypatch):
    import llm
    _set_keys(monkeypatch, "sk-ant-XXXXXXXXXX", "google-real-key")
    assert llm.proveedor_activo() == "gemini"


def test_claude_gana_cuando_ambos_configurados(monkeypatch):
    """
    Regla del sprint: Claude tiene precedencia si el owner recuperó
    créditos y volvió a poner ANTHROPIC_API_KEY.
    """
    import llm
    _set_keys(monkeypatch, "sk-ant-real-clave-aqui", "google-real-key")
    assert llm.proveedor_activo() == "claude"


def test_sin_ninguna_clave_es_none(monkeypatch):
    import llm
    _set_keys(monkeypatch, "", "")
    assert llm.proveedor_activo() == "none"


# ═══════════════════════════════════════════════════════════════
# API pública: error explícito sin proveedor
# ═══════════════════════════════════════════════════════════════

def test_stream_respuesta_sin_proveedor_levanta_error_explicito(monkeypatch):
    import llm
    _set_keys(monkeypatch, "", "")

    async def on_chunk(_):
        pass

    with pytest.raises(llm.ProveedorNoConfiguradoError) as exc:
        asyncio.run(llm.stream_respuesta("system", [{"role": "user", "content": "hola"}], on_chunk))
    assert "ANTHROPIC" in str(exc.value) or "GOOGLE" in str(exc.value)


def test_respuesta_completa_sin_proveedor_levanta_error_explicito(monkeypatch):
    import llm
    _set_keys(monkeypatch, "", "")
    with pytest.raises(llm.ProveedorNoConfiguradoError):
        asyncio.run(llm.respuesta_completa("system", [{"role": "user", "content": "hola"}]))


# ═══════════════════════════════════════════════════════════════
# Delegación al adapter correcto
# ═══════════════════════════════════════════════════════════════

def test_stream_delega_en_claude_cuando_proveedor_es_claude(monkeypatch):
    """Verificamos que llama al adapter _stream_claude, no al de Gemini."""
    import llm
    _set_keys(monkeypatch, "sk-ant-real", "google-real")

    llamado = {"proveedor": None}

    async def fake_claude(sp, msgs, on_chunk, max_tokens, model):
        llamado["proveedor"] = "claude"
        return "resp-claude"

    async def fake_gemini(sp, msgs, on_chunk, max_tokens, model):
        llamado["proveedor"] = "gemini"
        return "resp-gemini"

    monkeypatch.setattr(llm, "_stream_claude", fake_claude)
    monkeypatch.setattr(llm, "_stream_gemini", fake_gemini)

    async def on_chunk(_):
        pass
    resp = asyncio.run(llm.stream_respuesta("system", [{"role": "user", "content": "x"}], on_chunk))
    assert resp == "resp-claude"
    assert llamado["proveedor"] == "claude"


def test_stream_cae_a_gemini_cuando_claude_no_configurado(monkeypatch):
    import llm
    _set_keys(monkeypatch, "sk-ant-XXXXXXXXXX", "google-real")

    llamado = {"proveedor": None}

    async def fake_claude(sp, msgs, on_chunk, max_tokens, model):
        llamado["proveedor"] = "claude"
        return "resp-claude"

    async def fake_gemini(sp, msgs, on_chunk, max_tokens, model):
        llamado["proveedor"] = "gemini"
        return "resp-gemini"

    monkeypatch.setattr(llm, "_stream_claude", fake_claude)
    monkeypatch.setattr(llm, "_stream_gemini", fake_gemini)

    async def on_chunk(_):
        pass
    resp = asyncio.run(llm.stream_respuesta("system", [{"role": "user", "content": "x"}], on_chunk))
    assert resp == "resp-gemini"
    assert llamado["proveedor"] == "gemini"


# ═══════════════════════════════════════════════════════════════
# Traducción de mensajes al formato Gemini
# ═══════════════════════════════════════════════════════════════

def test_mensajes_a_gemini_traduce_assistant_a_model():
    from llm import _mensajes_a_gemini
    canonico = [
        {"role": "user", "content": "hola"},
        {"role": "assistant", "content": "qué tal"},
        {"role": "user", "content": "planificá una clase"},
    ]
    gemini = _mensajes_a_gemini(canonico)
    assert gemini == [
        {"role": "user", "parts": ["hola"]},
        {"role": "model", "parts": ["qué tal"]},
        {"role": "user", "parts": ["planificá una clase"]},
    ]
