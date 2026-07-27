"""
Sprint sesiones temáticas — cubre 6 contratos del sprint:

1. Crear sesión → asociar mensajes → historial aislado por sesión.
2. Admin bypasea rate limit (contador incrementa pero autoriza).
3. Cambiar de sesión no contamina el contexto (dos sesiones del mismo
   modo/grupo devuelven historiales distintos).
4. Sesión archivada no aparece en la lista activa (sí con incluir_archivadas).
5. Título automático se actualiza (mockeando llm.respuesta_completa).
6. Retro-compat: mensajes viejos sin id_sesion no rompen el listado normal
   y quedan disponibles bajo ?legacy=true.

Todo corre sobre SQLite in-memory (fixtures del conftest).
"""
from __future__ import annotations

import pytest


# ═══════════════════════════════════════════════════════════════
# 1. Crear sesión + persistir mensajes con id_sesion
# ═══════════════════════════════════════════════════════════════

def test_crear_sesion_y_persistir_mensajes(client, seed_docente, db_session):
    from models import Mensaje

    gid = seed_docente["grupo"].id_grupo
    r = client.post(f"/api/grupos/{gid}/sesiones", json={
        "modo": "planeacion", "titulo": "Álgebra semana 3",
    })
    assert r.status_code == 201, r.text
    ses = r.json()
    assert ses["titulo"] == "Álgebra semana 3"
    assert ses["archivada"] is False

    # Sembrar 2 mensajes en la sesión (simulando socket handler)
    db_session.add(Mensaje(
        id_grupo=gid, remitente="docente", contenido="Hola",
        modo="planeacion", id_sesion=ses["id_sesion"],
    ))
    db_session.add(Mensaje(
        id_grupo=gid, remitente="sistema", contenido="Bienvenido",
        modo="planeacion", id_sesion=ses["id_sesion"],
    ))
    db_session.commit()

    # GET /historial?id_sesion → devuelve solo los 2
    r2 = client.get(f"/api/grupos/{gid}/chat/historial?id_sesion={ses['id_sesion']}")
    assert r2.status_code == 200
    mensajes = r2.json()
    assert len(mensajes) == 2
    assert all(m["id_sesion"] == ses["id_sesion"] for m in mensajes)


# ═══════════════════════════════════════════════════════════════
# 3. Aislamiento entre sesiones
# ═══════════════════════════════════════════════════════════════

def test_dos_sesiones_del_mismo_modo_son_aisladas(client, seed_docente, db_session):
    from models import Mensaje

    gid = seed_docente["grupo"].id_grupo
    s1 = client.post(f"/api/grupos/{gid}/sesiones",
                     json={"modo": "planeacion", "titulo": "S1"}).json()
    s2 = client.post(f"/api/grupos/{gid}/sesiones",
                     json={"modo": "planeacion", "titulo": "S2"}).json()

    db_session.add(Mensaje(
        id_grupo=gid, remitente="docente", contenido="pertenece a S1",
        modo="planeacion", id_sesion=s1["id_sesion"],
    ))
    db_session.add(Mensaje(
        id_grupo=gid, remitente="docente", contenido="pertenece a S2",
        modo="planeacion", id_sesion=s2["id_sesion"],
    ))
    db_session.commit()

    r1 = client.get(f"/api/grupos/{gid}/chat/historial?id_sesion={s1['id_sesion']}").json()
    r2 = client.get(f"/api/grupos/{gid}/chat/historial?id_sesion={s2['id_sesion']}").json()
    assert [m["contenido"] for m in r1] == ["pertenece a S1"]
    assert [m["contenido"] for m in r2] == ["pertenece a S2"]


# ═══════════════════════════════════════════════════════════════
# 4. Sesión archivada
# ═══════════════════════════════════════════════════════════════

def test_sesion_archivada_no_aparece_en_lista_activa(client, seed_docente):
    gid = seed_docente["grupo"].id_grupo
    s = client.post(f"/api/grupos/{gid}/sesiones",
                    json={"modo": "planeacion", "titulo": "A archivar"}).json()

    r_arch = client.put(f"/api/sesiones/{s['id_sesion']}/archivar")
    assert r_arch.status_code == 200
    assert r_arch.json()["archivada"] is True

    # Sin flag → no aparece
    activas = client.get(f"/api/grupos/{gid}/sesiones").json()
    assert not any(x["id_sesion"] == s["id_sesion"] for x in activas)

    # Con incluir_archivadas=true → sí
    todas = client.get(f"/api/grupos/{gid}/sesiones?incluir_archivadas=true").json()
    assert any(x["id_sesion"] == s["id_sesion"] for x in todas)


# ═══════════════════════════════════════════════════════════════
# 5. Actualizar título (simula lo que hace _titular_sesion_con_ia)
# ═══════════════════════════════════════════════════════════════

def test_actualizar_titulo_de_sesion(client, seed_docente):
    gid = seed_docente["grupo"].id_grupo
    s = client.post(f"/api/grupos/{gid}/sesiones",
                    json={"modo": "planeacion"}).json()
    # Título provisional al crear
    assert s["titulo"].startswith("Sesión ")

    r = client.put(f"/api/sesiones/{s['id_sesion']}/titulo",
                   json={"titulo": "Fracciones 5A"})
    assert r.status_code == 200
    assert r.json()["titulo"] == "Fracciones 5A"


def test_titulo_automatico_llama_a_llm_y_actualiza_sesion(monkeypatch, db_session):
    """
    _titular_sesion_con_ia (socket_events) llama a llm.respuesta_completa
    y persiste el título. Aislado del socket handler para no depender
    del stack de Socket.io en el test.
    """
    from models import ChatSesion
    import asyncio
    import socket_events

    ses = ChatSesion(
        id_grupo="g1", id_docente="d1", modo="planeacion",
        titulo="Sesión 27/07/2026 15:00", archivada=False,
    )
    db_session.add(ses); db_session.commit(); db_session.refresh(ses)

    async def fake_completa(system_prompt, messages, max_tokens=4096, **kw):
        return "Álgebra vectorial 6B"

    import llm
    monkeypatch.setattr(llm, "respuesta_completa", fake_completa)

    nuevo = asyncio.run(socket_events._titular_sesion_con_ia(
        db_session, ses, "Ayudame a planear una clase de vectores",
    ))
    assert nuevo == "Álgebra vectorial 6B"
    db_session.refresh(ses)
    assert ses.titulo == "Álgebra vectorial 6B"


# ═══════════════════════════════════════════════════════════════
# 6. Retro-compat: mensajes sin id_sesion
# ═══════════════════════════════════════════════════════════════

def test_mensajes_legacy_sin_sesion_estan_disponibles_via_legacy_flag(
    client, seed_docente, db_session,
):
    from models import Mensaje

    gid = seed_docente["grupo"].id_grupo
    # Mensajes legacy sin id_sesion (como los que quedaron pre-sprint)
    db_session.add(Mensaje(
        id_grupo=gid, remitente="docente", contenido="viejo msg",
        modo="planeacion", id_sesion=None,
    ))
    db_session.commit()

    # Sesión nueva + mensaje nuevo
    ses = client.post(f"/api/grupos/{gid}/sesiones",
                      json={"modo": "planeacion"}).json()
    db_session.add(Mensaje(
        id_grupo=gid, remitente="docente", contenido="mensaje de sesion",
        modo="planeacion", id_sesion=ses["id_sesion"],
    ))
    db_session.commit()

    # historial de la sesión → sólo el mensaje nuevo
    hist_ses = client.get(
        f"/api/grupos/{gid}/chat/historial?id_sesion={ses['id_sesion']}"
    ).json()
    contenidos = [m["contenido"] for m in hist_ses]
    assert "mensaje de sesion" in contenidos
    assert "viejo msg" not in contenidos

    # ?legacy=true → el viejo
    hist_leg = client.get(
        f"/api/grupos/{gid}/chat/historial?legacy=true"
    ).json()
    contenidos_leg = [m["contenido"] for m in hist_leg]
    assert "viejo msg" in contenidos_leg


# ═══════════════════════════════════════════════════════════════
# 2. Admin bypasea rate limit
# ═══════════════════════════════════════════════════════════════

def test_admin_bypasea_rate_limit_diario(db_session):
    """
    _consumir_rate_limit con es_admin=True siempre autoriza; el contador
    sigue incrementando (para métricas). Se testea aislado del socket.
    """
    from models import Docente, RateLimitCounter
    from socket_events import _consumir_rate_limit, _hoy_iso
    from auth import hash_password

    admin = Docente(
        nombre_completo="Admin", email="admin@x.com",
        password_hash=hash_password("x"),
        es_admin=True,
    )
    db_session.add(admin); db_session.commit(); db_session.refresh(admin)

    # Simular que ya alcanzó el límite: contador = 999
    limite_actual = 999
    db_session.add(RateLimitCounter(
        id_docente=admin.id_docente, fecha=_hoy_iso(),
        modo="planeacion", count=limite_actual,
    ))
    db_session.commit()

    ok, usado, limite = _consumir_rate_limit(
        db_session, admin.id_docente, "planeacion", es_admin=True,
    )
    assert ok is True, "Admin debe pasar aunque supere el límite"
    assert usado == limite_actual + 1, "El contador sí incrementa (métricas)"


def test_no_admin_bloquea_al_pasar_limite(db_session):
    """Contraprueba: sin es_admin, superar el límite bloquea."""
    from models import Docente, RateLimitCounter
    from prompts import LIMITES_DIARIOS
    from socket_events import _consumir_rate_limit, _hoy_iso
    from auth import hash_password

    docente = Docente(
        nombre_completo="Regular", email="reg@x.com",
        password_hash=hash_password("x"),
        es_admin=False,
    )
    db_session.add(docente); db_session.commit(); db_session.refresh(docente)

    limite = LIMITES_DIARIOS.get("planeacion", 20)
    db_session.add(RateLimitCounter(
        id_docente=docente.id_docente, fecha=_hoy_iso(),
        modo="planeacion", count=limite,
    ))
    db_session.commit()

    ok, _, _ = _consumir_rate_limit(
        db_session, docente.id_docente, "planeacion", es_admin=False,
    )
    assert ok is False


# ═══════════════════════════════════════════════════════════════
# Filtros PIAR
# ═══════════════════════════════════════════════════════════════

def test_sesion_piar_requiere_id_estudiante(client, seed_docente):
    """Modo PIAR sin id_estudiante debe rechazarse."""
    gid = seed_docente["grupo"].id_grupo
    r = client.post(f"/api/grupos/{gid}/sesiones", json={"modo": "piar"})
    assert r.status_code == 400
    assert "id_estudiante" in r.json()["detail"].lower()


def test_sesion_no_piar_rechaza_id_estudiante(client, seed_docente, db_session):
    """id_estudiante en modo no-PIAR es error."""
    from models import Estudiante
    gid = seed_docente["grupo"].id_grupo
    e = Estudiante(id_grupo=gid, codigo_estudiante="X1", tiene_piar=True)
    db_session.add(e); db_session.commit(); db_session.refresh(e)

    r = client.post(f"/api/grupos/{gid}/sesiones", json={
        "modo": "planeacion", "id_estudiante": e.id_estudiante,
    })
    assert r.status_code == 400


# ═══════════════════════════════════════════════════════════════
# Aislamiento entre docentes
# ═══════════════════════════════════════════════════════════════

def test_docente_a_no_puede_archivar_sesion_de_b(client_two_docentes, db_session):
    from models import ChatSesion
    d = client_two_docentes
    ses_b = ChatSesion(
        id_grupo=d["data"]["b"]["grupo"].id_grupo,
        id_docente=d["data"]["b"]["docente"].id_docente,
        modo="planeacion", titulo="De B",
    )
    db_session.add(ses_b); db_session.commit(); db_session.refresh(ses_b)

    d["as_a"]()
    r = d["client"].put(f"/api/sesiones/{ses_b.id_sesion}/archivar")
    assert r.status_code == 404  # contrato: no revelar existencia
