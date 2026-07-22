"""
Tests de integración de la Fase B — rate limiting, historial filtrado y
aislamiento entre docentes con el nuevo campo `modo`.

NUNCA llama a Claude real: los tests que ejercitan el pipeline completo
(handler socket + generar_respuesta) usan monkeypatch de generar_respuesta
para simular la respuesta de la IA. El objetivo es validar la lógica
que rodea la llamada (rate limit, persistencia, filtrado), no la IA.
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


# ═══════════════════════════════════════════════════════════════
# RATE LIMITING — se prueba directamente contra _consumir_rate_limit
# ═══════════════════════════════════════════════════════════════

def test_rate_limit_incrementa_al_iniciar_generacion(db_session, seed_docente):
    """
    Cada llamada al helper debe consumir 1 unidad de la cuota diaria.
    El límite se define en prompts.LIMITES_DIARIOS.
    """
    from socket_events import _consumir_rate_limit
    from prompts import LIMITES_DIARIOS

    docente_id = seed_docente["docente"].id_docente
    modo = "planeacion"
    limite = LIMITES_DIARIOS[modo]

    # Primeras N llamadas: todas OK y count crece 1 a 1
    for i in range(1, limite + 1):
        ok, usado, lim = _consumir_rate_limit(db_session, docente_id, modo)
        assert ok is True, f"Iteración {i}: debía autorizar"
        assert usado == i
        assert lim == limite


def test_rate_limit_al_superar_limite_bloquea_con_mensaje_correcto(db_session, seed_docente):
    from socket_events import _consumir_rate_limit
    from prompts import LIMITES_DIARIOS
    docente_id = seed_docente["docente"].id_docente
    modo = "socioemocional"
    limite = LIMITES_DIARIOS[modo]

    # Consumir toda la cuota
    for _ in range(limite):
        ok, _, _ = _consumir_rate_limit(db_session, docente_id, modo)
        assert ok is True

    # Siguiente llamada debe fallar
    ok, usado, lim = _consumir_rate_limit(db_session, docente_id, modo)
    assert ok is False
    assert usado == limite
    assert lim == limite


def test_rate_limit_independiente_entre_modos(db_session, seed_docente):
    """
    Consumir toda la cuota de planeacion no debe afectar la cuota de otros modos.
    """
    from socket_events import _consumir_rate_limit
    from prompts import LIMITES_DIARIOS
    docente_id = seed_docente["docente"].id_docente

    # Consumir todo planeacion
    for _ in range(LIMITES_DIARIOS["planeacion"]):
        _consumir_rate_limit(db_session, docente_id, "planeacion")

    # Socioemocional todavía tiene cuota completa
    ok, usado, _ = _consumir_rate_limit(db_session, docente_id, "socioemocional")
    assert ok is True
    assert usado == 1

    # Calificacion también
    ok, usado, _ = _consumir_rate_limit(db_session, docente_id, "calificacion")
    assert ok is True
    assert usado == 1


def test_rate_limit_independiente_entre_docentes(db_session, seed_docente, seed_docente_b):
    """
    Consumir cuota del docente A no debe afectar al docente B.
    """
    from socket_events import _consumir_rate_limit
    from prompts import LIMITES_DIARIOS
    modo = "planeacion"

    # A consume toda su cuota
    for _ in range(LIMITES_DIARIOS[modo]):
        _consumir_rate_limit(db_session, seed_docente["docente"].id_docente, modo)

    # A está bloqueado
    ok_a, _, _ = _consumir_rate_limit(db_session, seed_docente["docente"].id_docente, modo)
    assert ok_a is False

    # B tiene cuota intacta
    ok_b, usado_b, _ = _consumir_rate_limit(db_session, seed_docente_b["docente"].id_docente, modo)
    assert ok_b is True
    assert usado_b == 1


def test_rate_limit_modo_desconocido_bloquea_fail_closed(db_session, seed_docente):
    """Un modo sin límite definido debe bloquearse por default."""
    from socket_events import _consumir_rate_limit
    ok, usado, lim = _consumir_rate_limit(
        db_session, seed_docente["docente"].id_docente, "modo-inexistente",
    )
    assert ok is False
    assert lim == 0


# ═══════════════════════════════════════════════════════════════
# HISTORIAL FILTRADO POR MODO
# ═══════════════════════════════════════════════════════════════

def _seed_mensajes_multi_modo(db_session, grupo_id):
    """Crea 6 mensajes: 2 planeación + 2 socioemocional + 2 calificación."""
    from models import Mensaje
    for modo in ("planeacion", "socioemocional", "calificacion"):
        db_session.add(Mensaje(id_grupo=grupo_id, remitente="docente",
                               contenido=f"pregunta {modo}", modo=modo))
        db_session.add(Mensaje(id_grupo=grupo_id, remitente="sistema",
                               contenido=f"respuesta {modo}", modo=modo))
    db_session.commit()


def test_historial_sin_modo_devuelve_todos(client, seed_docente, db_session):
    gid = seed_docente["grupo"].id_grupo
    _seed_mensajes_multi_modo(db_session, gid)
    r = client.get(f"/api/grupos/{gid}/chat/historial")
    assert r.status_code == 200
    assert len(r.json()) == 6


def test_historial_filtrado_por_modo_devuelve_solo_ese_modo(client, seed_docente, db_session):
    gid = seed_docente["grupo"].id_grupo
    _seed_mensajes_multi_modo(db_session, gid)

    r = client.get(f"/api/grupos/{gid}/chat/historial?modo=socioemocional")
    assert r.status_code == 200
    mensajes = r.json()
    assert len(mensajes) == 2
    for m in mensajes:
        assert m["modo"] == "socioemocional"
        assert "socioemocional" in m["contenido"]


def test_historial_modo_inexistente_devuelve_400(client, seed_docente):
    gid = seed_docente["grupo"].id_grupo
    r = client.get(f"/api/grupos/{gid}/chat/historial?modo=whatever")
    assert r.status_code == 400
    assert "modo" in r.json()["detail"].lower() or "válid" in r.json()["detail"].lower()


def test_historial_modo_sin_mensajes_devuelve_lista_vacia(client, seed_docente, db_session):
    """Si el modo no tiene mensajes aún, devuelve [] (frontend muestra empty state)."""
    from models import Mensaje
    gid = seed_docente["grupo"].id_grupo
    # Sólo planeacion
    db_session.add(Mensaje(id_grupo=gid, remitente="docente",
                           contenido="hola", modo="planeacion"))
    db_session.commit()

    r = client.get(f"/api/grupos/{gid}/chat/historial?modo=calificacion")
    assert r.status_code == 200
    assert r.json() == []


# ═══════════════════════════════════════════════════════════════
# AISLAMIENTO ENTRE DOCENTES CON EL CAMPO MODO
# ═══════════════════════════════════════════════════════════════

def test_historial_ajeno_devuelve_404_para_docente_a(client_two_docentes, db_session):
    """
    Docente A intentando leer historial del grupo de B — con filtro por modo,
    el aislamiento del sprint anterior sigue vigente (404 antes de que aplique
    el filtro).
    """
    from models import Mensaje
    grupo_b = client_two_docentes["data"]["b"]["grupo"]
    db_session.add(Mensaje(id_grupo=grupo_b.id_grupo, remitente="docente",
                           contenido="secreto de B", modo="planeacion"))
    db_session.commit()

    d = client_two_docentes
    d["as_a"]()
    r = d["client"].get(f"/api/grupos/{grupo_b.id_grupo}/chat/historial?modo=planeacion")
    assert r.status_code == 404
    r2 = d["client"].get(f"/api/grupos/{grupo_b.id_grupo}/chat/historial")
    assert r2.status_code == 404


# ═══════════════════════════════════════════════════════════════
# FALLBACK CUANDO NO HAY API KEY
# ═══════════════════════════════════════════════════════════════

def test_api_key_no_configurada_permite_al_frontend_deshabilitar_boton(monkeypatch):
    """
    Cuando la clave no está configurada, _api_key_configurada() devuelve False.
    El frontend usa esto para deshabilitar el botón antes de fallar
    silenciosamente en la llamada a Claude — política del owner.
    """
    from config import settings
    import ia

    # Placeholder por defecto → no configurada
    monkeypatch.setattr(settings, "CLAUDE_API_KEY", "sk-ant-XXXXXXXXXX")
    assert ia._api_key_configurada() is False

    # Clave real (formato sk-ant-*)
    monkeypatch.setattr(settings, "CLAUDE_API_KEY", "sk-ant-abcdefghijklmnop")
    assert ia._api_key_configurada() is True

    # Vacío también es no-configurada
    monkeypatch.setattr(settings, "CLAUDE_API_KEY", "")
    assert ia._api_key_configurada() is False
