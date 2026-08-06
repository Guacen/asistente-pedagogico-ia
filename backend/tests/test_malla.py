"""
Sprint malla-curricular — Seguidor de Malla Curricular (DBA del MEN).

NUNCA se llama a un proveedor de IA real: `llm.respuesta_completa` se
mockea con monkeypatch — mismo patrón que test_observaciones_crud.py.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock

from models import DBA


def _seed_dbas(db_session, asignatura="Lenguaje", grado="8°", cantidad=6):
    creados = []
    for i in range(1, cantidad + 1):
        dba = DBA(
            asignatura=asignatura, grado=grado, numero=i,
            enunciado=f"DBA de prueba número {i} de {asignatura} grado {grado}.",
            evidencias=[f"Evidencia {i}"],
        )
        db_session.add(dba)
        creados.append(dba)
    db_session.commit()
    for d in creados:
        db_session.refresh(d)
    return creados


def _mock_llm_distribucion(monkeypatch, distribucion=None):
    """Mockea llm.respuesta_completa para devolver una distribución canned."""
    import llm as llm_module
    payload = distribucion or {
        "distribucion": [
            {"periodo": 1, "dba_numeros": [1, 2, 3]},
            {"periodo": 2, "dba_numeros": [4, 5, 6]},
        ]
    }
    mock = AsyncMock(return_value=json.dumps(payload))
    monkeypatch.setattr(llm_module, "respuesta_completa", mock)
    return mock


# ═══════════════════════════════════════════════════════════════
# Catálogo de DBA
# ═══════════════════════════════════════════════════════════════

def test_get_asignaturas(client, seed_docente, db_session):
    _seed_dbas(db_session, asignatura="Lenguaje", grado="8°")
    _seed_dbas(db_session, asignatura="Ciencias Naturales", grado="8°", cantidad=3)

    r = client.get("/api/malla/asignaturas")
    assert r.status_code == 200
    data = r.json()
    assert "Lenguaje" in data
    assert "8°" in data["Lenguaje"]
    assert "Ciencias Naturales" in data


def test_get_dbas(client, seed_docente, db_session):
    _seed_dbas(db_session, asignatura="Lenguaje", grado="8°", cantidad=6)

    r = client.get("/api/malla/dbas?asignatura=Lenguaje&grado=8°")
    assert r.status_code == 200
    dbas = r.json()
    assert len(dbas) == 6
    assert dbas[0]["numero"] == 1
    assert "enunciado" in dbas[0]


# ═══════════════════════════════════════════════════════════════
# Malla por grupo
# ═══════════════════════════════════════════════════════════════

def test_malla_vacia_sin_generar(client, seed_docente, db_session):
    _seed_dbas(db_session, asignatura="Lenguaje", grado="8°")
    grupo = seed_docente["grupo"]  # grado="8°" (conftest._make_grupo)

    r = client.get(f"/api/malla/grupo/{grupo.id_grupo}?asignatura=Lenguaje")
    assert r.status_code == 200
    assert r.json()["malla"] is None
    assert r.json()["items"] == []


def test_generar_y_consultar_malla(client, seed_docente, db_session, monkeypatch):
    _seed_dbas(db_session, asignatura="Lenguaje", grado="8°", cantidad=6)
    _mock_llm_distribucion(monkeypatch)
    grupo = seed_docente["grupo"]

    r = client.post("/api/malla/generar", json={
        "id_grupo": grupo.id_grupo, "asignatura": "Lenguaje", "periodos": 4,
    })
    assert r.status_code == 200
    assert r.json()["total_dbas"] == 6

    r2 = client.get(f"/api/malla/grupo/{grupo.id_grupo}?asignatura=Lenguaje")
    assert r2.status_code == 200
    body = r2.json()
    assert body["malla"] is not None
    assert body["malla"]["tipo"] == "generada"
    assert len(body["items"]) == 6
    # La distribución mockeada puso los DBA 1-3 en el período 1
    periodo_1 = [i for i in body["items"] if i["periodo"] == 1]
    assert {i["dba"]["numero"] for i in periodo_1} == {1, 2, 3}


def test_generar_malla_sin_dbas_en_catalogo_devuelve_404(client, seed_docente, monkeypatch):
    _mock_llm_distribucion(monkeypatch)
    grupo = seed_docente["grupo"]

    r = client.post("/api/malla/generar", json={
        "id_grupo": grupo.id_grupo, "asignatura": "Asignatura Inexistente", "periodos": 4,
    })
    assert r.status_code == 404


def test_generar_malla_con_ia_fallando_usa_fallback_parejo(client, seed_docente, db_session, monkeypatch):
    """Si la IA no configura o responde basura, el reparto parejo no debe fallar."""
    _seed_dbas(db_session, asignatura="Lenguaje", grado="8°", cantidad=6)
    import llm as llm_module
    monkeypatch.setattr(
        llm_module, "respuesta_completa",
        AsyncMock(side_effect=RuntimeError("proveedor no configurado")),
    )
    grupo = seed_docente["grupo"]

    r = client.post("/api/malla/generar", json={
        "id_grupo": grupo.id_grupo, "asignatura": "Lenguaje", "periodos": 3,
    })
    assert r.status_code == 200

    r2 = client.get(f"/api/malla/grupo/{grupo.id_grupo}?asignatura=Lenguaje")
    assert len(r2.json()["items"]) == 6  # los 6 DBA quedaron repartidos igual


def test_generar_malla_regenera_reemplaza_la_anterior(client, seed_docente, db_session, monkeypatch):
    _seed_dbas(db_session, asignatura="Lenguaje", grado="8°", cantidad=6)
    _mock_llm_distribucion(monkeypatch)
    grupo = seed_docente["grupo"]

    client.post("/api/malla/generar", json={"id_grupo": grupo.id_grupo, "asignatura": "Lenguaje", "periodos": 4})
    r1 = client.get(f"/api/malla/grupo/{grupo.id_grupo}?asignatura=Lenguaje")
    id_malla_1 = r1.json()["malla"]["id_malla"]

    client.post("/api/malla/generar", json={"id_grupo": grupo.id_grupo, "asignatura": "Lenguaje", "periodos": 4})
    r2 = client.get(f"/api/malla/grupo/{grupo.id_grupo}?asignatura=Lenguaje")
    id_malla_2 = r2.json()["malla"]["id_malla"]

    assert id_malla_1 != id_malla_2
    assert len(r2.json()["items"]) == 6  # no quedaron duplicados


def test_docente_b_no_ve_ni_genera_malla_de_grupo_ajeno(client_as_b, seed_docente, db_session, monkeypatch):
    _seed_dbas(db_session, asignatura="Lenguaje", grado="8°")
    _mock_llm_distribucion(monkeypatch)
    grupo_de_a = seed_docente["grupo"]

    r_get = client_as_b.get(f"/api/malla/grupo/{grupo_de_a.id_grupo}?asignatura=Lenguaje")
    assert r_get.status_code == 404

    r_post = client_as_b.post("/api/malla/generar", json={
        "id_grupo": grupo_de_a.id_grupo, "asignatura": "Lenguaje", "periodos": 4,
    })
    assert r_post.status_code == 404


# ═══════════════════════════════════════════════════════════════
# Seguimiento
# ═══════════════════════════════════════════════════════════════

def test_seguimiento_dba(client, seed_docente, db_session, monkeypatch):
    _seed_dbas(db_session, asignatura="Lenguaje", grado="8°", cantidad=6)
    _mock_llm_distribucion(monkeypatch)
    grupo = seed_docente["grupo"]

    client.post("/api/malla/generar", json={"id_grupo": grupo.id_grupo, "asignatura": "Lenguaje", "periodos": 4})
    malla = client.get(f"/api/malla/grupo/{grupo.id_grupo}?asignatura=Lenguaje").json()
    primer_item = malla["items"][0]
    assert primer_item["cubierto"] is False

    r = client.post("/api/malla/seguimiento", json={
        "id_grupo": grupo.id_grupo,
        "id_dba": primer_item["dba"]["id_dba"],
        "periodo": primer_item["periodo"],
        "cubierto": True,
    })
    assert r.status_code == 200

    malla2 = client.get(f"/api/malla/grupo/{grupo.id_grupo}?asignatura=Lenguaje").json()
    item_actualizado = next(
        i for i in malla2["items"]
        if i["dba"]["id_dba"] == primer_item["dba"]["id_dba"] and i["periodo"] == primer_item["periodo"]
    )
    assert item_actualizado["cubierto"] is True


def test_seguimiento_se_puede_desmarcar(client, seed_docente, db_session, monkeypatch):
    _seed_dbas(db_session, asignatura="Lenguaje", grado="8°", cantidad=6)
    _mock_llm_distribucion(monkeypatch)
    grupo = seed_docente["grupo"]

    client.post("/api/malla/generar", json={"id_grupo": grupo.id_grupo, "asignatura": "Lenguaje", "periodos": 4})
    item = client.get(f"/api/malla/grupo/{grupo.id_grupo}?asignatura=Lenguaje").json()["items"][0]

    client.post("/api/malla/seguimiento", json={
        "id_grupo": grupo.id_grupo, "id_dba": item["dba"]["id_dba"],
        "periodo": item["periodo"], "cubierto": True,
    })
    client.post("/api/malla/seguimiento", json={
        "id_grupo": grupo.id_grupo, "id_dba": item["dba"]["id_dba"],
        "periodo": item["periodo"], "cubierto": False,
    })

    malla = client.get(f"/api/malla/grupo/{grupo.id_grupo}?asignatura=Lenguaje").json()
    actualizado = next(i for i in malla["items"] if i["dba"]["id_dba"] == item["dba"]["id_dba"])
    assert actualizado["cubierto"] is False


# ═══════════════════════════════════════════════════════════════
# Progreso
# ═══════════════════════════════════════════════════════════════

def test_progreso_sin_malla_generada(client, seed_docente):
    grupo = seed_docente["grupo"]
    r = client.get(f"/api/malla/progreso/{grupo.id_grupo}?asignatura=Lenguaje")
    assert r.status_code == 200
    assert r.json() == {"total": 0, "cubiertos": 0, "porcentaje": 0, "items": []}


def test_progreso(client, seed_docente, db_session, monkeypatch):
    _seed_dbas(db_session, asignatura="Lenguaje", grado="8°", cantidad=6)
    _mock_llm_distribucion(monkeypatch)
    grupo = seed_docente["grupo"]

    client.post("/api/malla/generar", json={"id_grupo": grupo.id_grupo, "asignatura": "Lenguaje", "periodos": 4})

    r = client.get(f"/api/malla/progreso/{grupo.id_grupo}?asignatura=Lenguaje")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 6
    assert data["cubiertos"] == 0
    assert data["porcentaje"] == 0

    item = client.get(f"/api/malla/grupo/{grupo.id_grupo}?asignatura=Lenguaje").json()["items"][0]
    client.post("/api/malla/seguimiento", json={
        "id_grupo": grupo.id_grupo, "id_dba": item["dba"]["id_dba"],
        "periodo": item["periodo"], "cubierto": True,
    })

    r2 = client.get(f"/api/malla/progreso/{grupo.id_grupo}?asignatura=Lenguaje")
    data2 = r2.json()
    assert data2["cubiertos"] == 1
    assert data2["porcentaje"] == round(1 / 6 * 100)


def test_progreso_filtra_por_periodo(client, seed_docente, db_session, monkeypatch):
    _seed_dbas(db_session, asignatura="Lenguaje", grado="8°", cantidad=6)
    _mock_llm_distribucion(monkeypatch)
    grupo = seed_docente["grupo"]

    client.post("/api/malla/generar", json={"id_grupo": grupo.id_grupo, "asignatura": "Lenguaje", "periodos": 4})

    r = client.get(f"/api/malla/progreso/{grupo.id_grupo}?asignatura=Lenguaje&periodo=1")
    assert r.status_code == 200
    assert r.json()["total"] == 3  # DBA 1,2,3 según la distribución mockeada
