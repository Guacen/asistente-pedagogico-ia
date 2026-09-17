"""
Sprint auto-refresh-jwt-frontend, Parte B — el streaming del chat con IA
no tenía timeout: mismo patrón que causó el 502 de Cloudflare en
Presentaciones antes del Sprint 4 (PR #81), pero en la función más usada
de toda la app.

Invoca el handler real `socket_events.send_message` (no un helper
extraído) con `generar_respuesta` monkeypatcheada para simular un
timeout — mismo patrón que tests/test_presentacion_events.py usa para
`presentacion_events.presentacion_unirse`: handler real, `sio.emit`
mockeado, SessionLocal apuntando al engine efímero del test. NUNCA llama
a Claude/Gemini real.

Cubre:
- llm.stream_respuesta con timeout_s excedido levanta asyncio.TimeoutError
  (probado directo contra el adapter, con un "proveedor" fake que tarda
  más que el timeout — sin red real).
- send_message captura ese asyncio.TimeoutError específicamente y emite
  ia_error con code="timeout" y un mensaje claro — nunca deja el socket
  sin ningún evento de vuelta (el "spinner mudo indefinido" del ticket).
- La duración de la llamada se loguea (logger.warning en el caso de
  timeout) — se confirma capturando el log, no re-implementando el
  cálculo.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import socket_events  # noqa: E402


# ═══════════════════════════════════════════════════════════════
# llm.stream_respuesta — el timeout en sí, sin red real
# ═══════════════════════════════════════════════════════════════

def test_stream_respuesta_excede_timeout_levanta_timeouterror(monkeypatch):
    import llm

    async def _stream_lento(system_prompt, messages, on_chunk, max_tokens, model):
        await asyncio.sleep(0.5)  # más lento que el timeout_s de abajo
        return "nunca debería llegar acá"

    monkeypatch.setattr(llm, "_asegurar_proveedor", lambda: "claude")
    monkeypatch.setattr(llm, "_stream_claude", _stream_lento)

    async def _run():
        with pytest.raises(asyncio.TimeoutError):
            await llm.stream_respuesta(
                "system", [{"role": "user", "content": "hola"}],
                on_chunk=AsyncMock(), timeout_s=0.05,
            )
    asyncio.run(_run())


def test_stream_respuesta_loguea_duracion_al_exceder_timeout(monkeypatch, caplog):
    import llm

    async def _stream_lento(system_prompt, messages, on_chunk, max_tokens, model):
        await asyncio.sleep(0.5)
        return "x"

    monkeypatch.setattr(llm, "_asegurar_proveedor", lambda: "claude")
    monkeypatch.setattr(llm, "_stream_claude", _stream_lento)

    async def _run():
        with pytest.raises(asyncio.TimeoutError):
            with caplog.at_level("WARNING", logger="llm"):
                await llm.stream_respuesta(
                    "system", [{"role": "user", "content": "hola"}],
                    on_chunk=AsyncMock(), timeout_s=0.05,
                )
    asyncio.run(_run())

    assert any("TIMEOUT" in r.message and "duracion_s" in r.message for r in caplog.records)


def test_stream_respuesta_sin_timeout_completa_normal(monkeypatch):
    """Sanity check: timeout_s=None (default) no cambia el comportamiento
    normal — no queremos que envolver en asyncio.wait_for rompa el path feliz."""
    import llm

    async def _stream_rapido(system_prompt, messages, on_chunk, max_tokens, model):
        await on_chunk("hola")
        return "hola"

    monkeypatch.setattr(llm, "_asegurar_proveedor", lambda: "claude")
    monkeypatch.setattr(llm, "_stream_claude", _stream_rapido)

    async def _run():
        return await llm.stream_respuesta(
            "system", [{"role": "user", "content": "hola"}], on_chunk=AsyncMock(),
        )
    resultado = asyncio.run(_run())
    assert resultado == "hola"


# ═══════════════════════════════════════════════════════════════
# send_message — el handler real captura el timeout y avisa al docente
# ═══════════════════════════════════════════════════════════════

def _mock_sio(monkeypatch):
    emit_mock = AsyncMock()
    monkeypatch.setattr(socket_events.sio, "emit", emit_mock)
    return emit_mock


def _eventos_emitidos(emit_mock):
    return [c.args[0] for c in emit_mock.call_args_list]


def _payload_de(emit_mock, evento):
    for c in emit_mock.call_args_list:
        if c.args[0] == evento:
            return c.args[1]
    return None


def test_send_message_con_timeout_emite_ia_error_code_timeout(monkeypatch, test_engine, db_session, seed_docente):
    TestSessionLocal = sessionmaker(bind=test_engine, autocommit=False, autoflush=False)
    monkeypatch.setattr(socket_events, "SessionLocal", TestSessionLocal)

    sid = "sid-timeout-test"
    socket_events._sesiones[sid] = seed_docente["docente"].id_docente

    async def _generar_respuesta_timeout(*args, **kwargs):
        raise asyncio.TimeoutError()

    monkeypatch.setattr(socket_events, "generar_respuesta", _generar_respuesta_timeout)
    emit_mock = _mock_sio(monkeypatch)

    async def _run():
        await socket_events.send_message(sid, {
            "grupo_id": seed_docente["grupo"].id_grupo,
            "mensaje": "Hazme una planeación de fracciones",
            "modo": "planeacion",
        })
    try:
        asyncio.run(_run())
    finally:
        socket_events._sesiones.pop(sid, None)

    eventos = _eventos_emitidos(emit_mock)
    assert "ia_error" in eventos, f"send_message no emitió ningún ia_error — eventos: {eventos}"
    payload = _payload_de(emit_mock, "ia_error")
    assert payload["code"] == "timeout"
    assert payload["message"]  # mensaje no vacío, claro para el docente
    assert "intenta" in payload["message"].lower() or "tardando" in payload["message"].lower()

    # Nunca queda "nada" — o hay un ia_complete, o hay un ia_error, jamás
    # ningún evento en absoluto (eso es el spinner mudo indefinido).
    assert "ia_complete" not in eventos


def test_send_message_con_error_generico_sigue_emitiendo_ia_error_normal(monkeypatch, test_engine, db_session, seed_docente):
    """No-regresión: el except genérico (para cualquier OTRO error, no
    timeout) sigue funcionando — el nuevo except asyncio.TimeoutError no
    debe robarle el control a errores no relacionados."""
    TestSessionLocal = sessionmaker(bind=test_engine, autocommit=False, autoflush=False)
    monkeypatch.setattr(socket_events, "SessionLocal", TestSessionLocal)

    sid = "sid-error-generico-test"
    socket_events._sesiones[sid] = seed_docente["docente"].id_docente

    async def _generar_respuesta_rompe(*args, **kwargs):
        raise ValueError("algo totalmente distinto a un timeout")

    monkeypatch.setattr(socket_events, "generar_respuesta", _generar_respuesta_rompe)
    emit_mock = _mock_sio(monkeypatch)

    async def _run():
        await socket_events.send_message(sid, {
            "grupo_id": seed_docente["grupo"].id_grupo,
            "mensaje": "Hola",
            "modo": "planeacion",
        })
    try:
        asyncio.run(_run())
    finally:
        socket_events._sesiones.pop(sid, None)

    payload = _payload_de(emit_mock, "ia_error")
    assert payload is not None
    assert payload.get("code") != "timeout"
