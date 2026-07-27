"""
Config / settings — cubre el contrato de nombres de variables de entorno.

CLAUDE_API_KEY (nombre histórico del proyecto) y ANTHROPIC_API_KEY
(nombre estándar del SDK de Anthropic) deben ser intercambiables. Bug
reportado por producción: Railway configurado con ANTHROPIC_API_KEY y
la app leía default → chat 401.
"""
from __future__ import annotations

import pytest


def _fresh_settings(monkeypatch, env: dict[str, str]):
    """
    Devuelve una instancia Settings recién construida con `env` como
    entorno. Limpiamos ANTES cualquier CLAUDE_API_KEY/ANTHROPIC_API_KEY
    que la sesión de tests haya heredado del shell del dev.
    """
    for k in ("CLAUDE_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    from config import Settings
    return Settings()


def test_env_claude_api_key_se_usa(monkeypatch):
    s = _fresh_settings(monkeypatch, {"CLAUDE_API_KEY": "sk-ant-legacy-123"})
    assert s.CLAUDE_API_KEY == "sk-ant-legacy-123"


def test_env_anthropic_api_key_tambien_se_usa(monkeypatch):
    """Alias oficial del SDK: si solo está ANTHROPIC_API_KEY, se toma."""
    s = _fresh_settings(monkeypatch, {"ANTHROPIC_API_KEY": "sk-ant-official-456"})
    assert s.CLAUDE_API_KEY == "sk-ant-official-456"


def test_claude_api_key_gana_sobre_anthropic_api_key_si_hay_ambas(monkeypatch):
    """
    AliasChoices toma el primero de la lista que exista. CLAUDE_API_KEY
    va primero por retro-compat con setups viejos que ya la tenían.
    """
    s = _fresh_settings(monkeypatch, {
        "CLAUDE_API_KEY": "sk-ant-legacy",
        "ANTHROPIC_API_KEY": "sk-ant-official",
    })
    assert s.CLAUDE_API_KEY == "sk-ant-legacy"


def test_sin_ninguna_env_se_cae_al_default_placeholder(monkeypatch):
    """Sin ninguna de las dos vars, el default XXXX activa el warning de startup."""
    s = _fresh_settings(monkeypatch, {})
    assert "XXXX" in s.CLAUDE_API_KEY
