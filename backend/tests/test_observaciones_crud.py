"""
Sprint observaciones-seguimiento — Observador del Alumno + seguimiento
(Ley 1620 de 2013, Decreto 1965 de 2013, Ley 1098 de 2006 Art. 44,
Decreto 1421 de 2017).

NUNCA se llama a un proveedor de IA real: `_generar_observacion_ia` se
mockea con monkeypatch — mismo patrón que test_piar.py con
_sintetizar_conversacion_a_json.
"""
from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import AsyncMock

import observaciones as observaciones_module
from models import Estudiante, Observacion


CT_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


# ─── Helpers ──────────────────────────────────────────────────────

def _seed_estudiante(db_session, id_grupo, codigo="EST01", piar=False,
                      diag=None, ajustes=None):
    est = Estudiante(
        id_grupo=id_grupo,
        codigo_estudiante=codigo,
        tiene_piar=piar,
        diagnostico=diag,
        ajustes=ajustes,
    )
    db_session.add(est)
    db_session.commit()
    db_session.refresh(est)
    return est


def _canned(nivel="docente", texto="## Observación en el Observador del Alumno\n\nTexto."):
    return {
        "observacion_generada": texto,
        "nivel_escalacion": nivel,
        "acciones_recomendadas": ["Hablar con el estudiante", "Registrar en el observador"],
    }


def _mock_ia(monkeypatch, resultado=None):
    mock = AsyncMock(return_value=resultado or _canned())
    monkeypatch.setattr(observaciones_module, "_generar_observacion_ia", mock)
    return mock


# ═══════════════════════════════════════════════════════════════
# CRUD
# ═══════════════════════════════════════════════════════════════

def test_crear_observacion_academica(client, seed_docente, monkeypatch):
    mock = _mock_ia(monkeypatch)

    r = client.post("/api/observaciones", json={
        "id_grupo": seed_docente["grupo"].id_grupo,
        "tipo": "academica",
        "situacion_descrita": "El estudiante no entregó la tarea por tercera vez.",
    })
    assert r.status_code == 201
    body = r.json()
    assert body["tipo"] == "academica"
    assert body["estado"] == "abierta"
    assert body["nivel_escalacion"] == "docente"
    assert body["requiere_seguimiento"] is True
    assert "Observador del Alumno" in body["observacion_generada"]
    mock.assert_awaited_once()


def test_crear_observacion_tipo_invalido_devuelve_400(client, seed_docente, monkeypatch):
    _mock_ia(monkeypatch)
    r = client.post("/api/observaciones", json={
        "id_grupo": seed_docente["grupo"].id_grupo,
        "tipo": "no-existe",
        "situacion_descrita": "algo",
    })
    assert r.status_code == 400


def test_crear_observacion_grupal_sin_estudiante(client, seed_docente, monkeypatch):
    """id_estudiante es opcional — una observación puede ser grupal."""
    _mock_ia(monkeypatch)
    r = client.post("/api/observaciones", json={
        "id_grupo": seed_docente["grupo"].id_grupo,
        "tipo": "convivencia",
        "situacion_descrita": "El grupo completo tuvo un conflicto en el recreo.",
    })
    assert r.status_code == 201
    assert r.json()["id_estudiante"] is None


def test_crear_observacion_con_estudiante_ajeno_al_grupo_devuelve_404(
    client, seed_docente, seed_docente_b, db_session, monkeypatch,
):
    _mock_ia(monkeypatch)
    ajeno = _seed_estudiante(db_session, seed_docente_b["grupo"].id_grupo, "AJENO01")
    r = client.post("/api/observaciones", json={
        "id_grupo": seed_docente["grupo"].id_grupo,
        "id_estudiante": ajeno.id_estudiante,
        "tipo": "convivencia",
        "situacion_descrita": "algo",
    })
    assert r.status_code == 404


def test_listar_observaciones_filtra_por_estudiante_y_grupo(client, seed_docente, db_session, monkeypatch):
    _mock_ia(monkeypatch)
    est_a = _seed_estudiante(db_session, seed_docente["grupo"].id_grupo, "EST-A")
    est_b = _seed_estudiante(db_session, seed_docente["grupo"].id_grupo, "EST-B")

    for est, tipo in [(est_a, "academica"), (est_b, "convivencia")]:
        client.post("/api/observaciones", json={
            "id_grupo": seed_docente["grupo"].id_grupo,
            "id_estudiante": est.id_estudiante,
            "tipo": tipo,
            "situacion_descrita": "algo",
        })

    r_todas = client.get("/api/observaciones")
    assert r_todas.status_code == 200
    assert len(r_todas.json()) == 2

    r_filtrada = client.get(f"/api/observaciones?id_estudiante={est_a.id_estudiante}")
    assert len(r_filtrada.json()) == 1
    assert r_filtrada.json()[0]["tipo"] == "academica"


def test_detalle_observacion(client, seed_docente, monkeypatch):
    _mock_ia(monkeypatch)
    creada = client.post("/api/observaciones", json={
        "id_grupo": seed_docente["grupo"].id_grupo,
        "tipo": "logro",
        "situacion_descrita": "Ganó la feria de ciencias.",
    }).json()

    r = client.get(f"/api/observaciones/{creada['id_observacion']}")
    assert r.status_code == 200
    assert r.json()["tipo"] == "logro"


def test_detalle_observacion_inexistente_devuelve_404(client, seed_docente):
    r = client.get("/api/observaciones/no-existe")
    assert r.status_code == 404


def test_actualizar_estado_observacion(client, seed_docente, monkeypatch):
    _mock_ia(monkeypatch)
    creada = client.post("/api/observaciones", json={
        "id_grupo": seed_docente["grupo"].id_grupo,
        "tipo": "convivencia",
        "situacion_descrita": "Conflicto menor entre dos estudiantes.",
    }).json()

    r = client.patch(f"/api/observaciones/{creada['id_observacion']}", json={
        "estado": "en_seguimiento",
        "fecha_seguimiento": str(date.today() + timedelta(days=3)),
    })
    assert r.status_code == 200
    assert r.json()["estado"] == "en_seguimiento"
    assert r.json()["fecha_seguimiento"] == str(date.today() + timedelta(days=3))


def test_actualizar_a_cerrada_apaga_requiere_seguimiento(client, seed_docente, monkeypatch):
    _mock_ia(monkeypatch)
    creada = client.post("/api/observaciones", json={
        "id_grupo": seed_docente["grupo"].id_grupo,
        "tipo": "asistencia",
        "situacion_descrita": "Tercera inasistencia sin justificar.",
    }).json()
    assert creada["requiere_seguimiento"] is True

    r = client.patch(f"/api/observaciones/{creada['id_observacion']}", json={"estado": "cerrada"})
    assert r.status_code == 200
    assert r.json()["estado"] == "cerrada"
    assert r.json()["requiere_seguimiento"] is False


def test_actualizar_estado_invalido_devuelve_400(client, seed_docente, monkeypatch):
    _mock_ia(monkeypatch)
    creada = client.post("/api/observaciones", json={
        "id_grupo": seed_docente["grupo"].id_grupo,
        "tipo": "salud",
        "situacion_descrita": "algo",
    }).json()
    r = client.patch(f"/api/observaciones/{creada['id_observacion']}", json={"estado": "no-existe"})
    assert r.status_code == 400


def test_docente_b_no_ve_observaciones_de_docente_a(client_as_b, seed_docente, seed_docente_b, monkeypatch, db_session):
    """Aislamiento multi-tenant, mismo patrón que el resto del backend."""
    from models import Docente
    docente_a = db_session.query(Docente).filter_by(id_docente=seed_docente["docente"].id_docente).first()
    obs = Observacion(
        id_docente=docente_a.id_docente,
        id_grupo=seed_docente["grupo"].id_grupo,
        tipo="academica",
        situacion_descrita="algo",
        observacion_generada="## Observación en el Observador del Alumno",
        nivel_escalacion="docente",
    )
    db_session.add(obs)
    db_session.commit()

    r = client_as_b.get(f"/api/observaciones/{obs.id_observacion}")
    assert r.status_code == 404

    r_lista = client_as_b.get("/api/observaciones")
    assert r_lista.json() == []


# ═══════════════════════════════════════════════════════════════
# Tipo III — alerta ICBF / Ley 1098
# ═══════════════════════════════════════════════════════════════

def test_prompt_observaciones_cita_marco_legal_tipo3():
    """
    Compliance del prompt (mismo enfoque que test_piar_legal_compliance.py):
    el system prompt del modo debe instruir explícitamente sobre el Art. 44
    de la Ley 1098 y el reporte a ICBF para situaciones Tipo III.
    """
    from prompts import PROMPT_MODO_OBSERVACIONES

    assert "Ley 1620" in PROMPT_MODO_OBSERVACIONES
    assert "Decreto 1965" in PROMPT_MODO_OBSERVACIONES
    assert "Ley 1098" in PROMPT_MODO_OBSERVACIONES
    assert "Art. 44" in PROMPT_MODO_OBSERVACIONES
    assert "ICBF" in PROMPT_MODO_OBSERVACIONES
    assert "Tipo III" in PROMPT_MODO_OBSERVACIONES
    assert "Tipo II" in PROMPT_MODO_OBSERVACIONES
    assert "Tipo I" in PROMPT_MODO_OBSERVACIONES


def test_observaciones_tipo3_alerta(client, seed_docente, monkeypatch):
    """
    Si el proveedor de IA clasifica la situación como Tipo III (icbf), el
    registro persistido debe conservar esa clasificación y el texto debe
    mencionar ICBF y la Ley 1098 — sin que el backend los filtre o pierda.
    """
    texto_tipo3 = (
        "## Observación en el Observador del Alumno\n\n"
        "**Tipo de situación:** Tipo III\n\n"
        "Conforme al Art. 44 de la Ley 1098 de 2006, se debe reportar "
        "de inmediato al ICBF. No se debe investigar por cuenta propia."
    )
    _mock_ia(monkeypatch, _canned(nivel="icbf", texto=texto_tipo3))

    r = client.post("/api/observaciones", json={
        "id_grupo": seed_docente["grupo"].id_grupo,
        "tipo": "convivencia",
        "situacion_descrita": "Un estudiante reportó una situación grave en casa.",
    })
    assert r.status_code == 201
    body = r.json()
    assert body["nivel_escalacion"] == "icbf"
    assert "ICBF" in body["observacion_generada"]
    assert "Ley 1098" in body["observacion_generada"]


def test_generar_observacion_ia_nivel_invalido_cae_a_docente(monkeypatch, seed_docente, db_session):
    """Si el modelo devuelve un nivel_escalacion fuera del enum, no se rompe."""
    import asyncio
    from unittest.mock import AsyncMock
    import llm as llm_module

    monkeypatch.setattr(
        llm_module, "respuesta_completa",
        AsyncMock(return_value='{"observacion_generada": "texto", "nivel_escalacion": "urgente-ya", "acciones_recomendadas": []}'),
    )

    resultado = asyncio.run(observaciones_module._generar_observacion_ia(
        seed_docente["docente"], seed_docente["grupo"], None, "academica", "algo",
    ))
    assert resultado["nivel_escalacion"] == "docente"


# ═══════════════════════════════════════════════════════════════
# Seguimientos pendientes
# ═══════════════════════════════════════════════════════════════

def test_seguimientos_pendientes(client, seed_docente, db_session):
    hoy = date.today()
    vencida = Observacion(
        id_docente=seed_docente["docente"].id_docente,
        id_grupo=seed_docente["grupo"].id_grupo,
        tipo="convivencia", situacion_descrita="x",
        observacion_generada="x", nivel_escalacion="docente",
        estado="en_seguimiento", fecha_seguimiento=hoy - timedelta(days=1),
    )
    de_hoy = Observacion(
        id_docente=seed_docente["docente"].id_docente,
        id_grupo=seed_docente["grupo"].id_grupo,
        tipo="convivencia", situacion_descrita="x",
        observacion_generada="x", nivel_escalacion="docente",
        estado="abierta", fecha_seguimiento=hoy,
    )
    futura = Observacion(
        id_docente=seed_docente["docente"].id_docente,
        id_grupo=seed_docente["grupo"].id_grupo,
        tipo="convivencia", situacion_descrita="x",
        observacion_generada="x", nivel_escalacion="docente",
        estado="abierta", fecha_seguimiento=hoy + timedelta(days=5),
    )
    cerrada_vencida = Observacion(
        id_docente=seed_docente["docente"].id_docente,
        id_grupo=seed_docente["grupo"].id_grupo,
        tipo="convivencia", situacion_descrita="x",
        observacion_generada="x", nivel_escalacion="docente",
        estado="cerrada", fecha_seguimiento=hoy - timedelta(days=2),
    )
    sin_fecha = Observacion(
        id_docente=seed_docente["docente"].id_docente,
        id_grupo=seed_docente["grupo"].id_grupo,
        tipo="academica", situacion_descrita="x",
        observacion_generada="x", nivel_escalacion="docente",
        estado="abierta",
    )
    db_session.add_all([vencida, de_hoy, futura, cerrada_vencida, sin_fecha])
    db_session.commit()

    r = client.get("/api/observaciones/seguimientos-pendientes")
    assert r.status_code == 200
    ids = {o["id_observacion"] for o in r.json()}
    assert ids == {vencida.id_observacion, de_hoy.id_observacion}


# ═══════════════════════════════════════════════════════════════
# Exportar a DOCX
# ═══════════════════════════════════════════════════════════════

def test_exportar_observacion(client, seed_docente, monkeypatch):
    texto = (
        "## Observación en el Observador del Alumno\n\n"
        "**Fecha:** 01/01/2026 | **Hora:** 10:00 | **Lugar:** Aula 301\n\n"
        "### Descripción objetiva de los hechos\n\nTexto de prueba.\n\n"
        "### Acciones tomadas\n\nSe habló con el estudiante.\n\n"
        "### Acuerdos y compromisos\n\nAsistir puntual.\n\n"
        "### Nivel de atención requerido\n\nDocente.\n\n"
        "### Próxima fecha de seguimiento\n\n15/01/2026\n"
    )
    _mock_ia(monkeypatch, _canned(texto=texto))

    creada = client.post("/api/observaciones", json={
        "id_grupo": seed_docente["grupo"].id_grupo,
        "tipo": "convivencia",
        "situacion_descrita": "Situación de prueba para exportar.",
    }).json()

    r = client.post(f"/api/observaciones/{creada['id_observacion']}/exportar")
    assert r.status_code == 200
    assert r.headers["content-type"] == CT_DOCX
    assert len(r.content) > 0


def test_exportar_observacion_inexistente_devuelve_404(client, seed_docente):
    r = client.post("/api/observaciones/no-existe/exportar")
    assert r.status_code == 404
