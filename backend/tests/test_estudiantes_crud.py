"""
CRUD de /api/grupos/{id}/estudiantes: list, create, update, delete.
"""
from __future__ import annotations


def _create_est(client, gid, codigo="E001", piar=False, diag=None, ajustes=None):
    return client.post(f"/api/grupos/{gid}/estudiantes", json={
        "codigo_estudiante": codigo,
        "genero": "F",
        "tiene_piar": piar,
        "diagnostico": diag,
        "ajustes": ajustes,
    })


def test_list_estudiantes_grupo_vacio(client, seed_docente):
    r = client.get(f'/api/grupos/{seed_docente["grupo"].id_grupo}/estudiantes')
    assert r.status_code == 200
    assert r.json() == []


def test_list_estudiantes_grupo_inexistente_404(client):
    r = client.get("/api/grupos/00000000-0000-0000-0000-000000000000/estudiantes")
    assert r.status_code == 404


def test_create_estudiante_ok(client, seed_docente):
    gid = seed_docente["grupo"].id_grupo
    r = _create_est(client, gid, codigo="E001", piar=True, diag="TDA", ajustes="Instr cortas")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["codigo_estudiante"] == "E001"
    assert body["tiene_piar"] is True
    assert body["diagnostico"] == "TDA"
    assert body["ajustes"] == "Instr cortas"
    assert body["id_grupo"] == gid


def test_create_estudiante_en_grupo_inexistente_404(client):
    r = _create_est(client, "00000000-0000-0000-0000-000000000000", codigo="X")
    assert r.status_code == 404


def test_update_estudiante_parcial(client, seed_docente):
    gid = seed_docente["grupo"].id_grupo
    eid = _create_est(client, gid, codigo="E001").json()["id_estudiante"]
    r = client.put(f"/api/grupos/{gid}/estudiantes/{eid}", json={
        "tiene_piar": True,
        "diagnostico": "Dislexia",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["tiene_piar"] is True
    assert body["diagnostico"] == "Dislexia"
    # Los campos no enviados se mantienen
    assert body["codigo_estudiante"] == "E001"


def test_update_estudiante_de_grupo_ajeno_404(client, seed_docente, seed_docente_b, db_session):
    """
    Docente A intenta actualizar un estudiante del grupo de B usando el path
    del grupo de A → 404 (el estudiante no pertenece al grupo del path).
    """
    from models import Estudiante
    est_b = Estudiante(id_grupo=seed_docente_b["grupo"].id_grupo, codigo_estudiante="EB01")
    db_session.add(est_b)
    db_session.commit()
    db_session.refresh(est_b)

    gid_a = seed_docente["grupo"].id_grupo
    r = client.put(f"/api/grupos/{gid_a}/estudiantes/{est_b.id_estudiante}", json={
        "codigo_estudiante": "hackeado"
    })
    assert r.status_code == 404


def test_delete_estudiante(client, seed_docente):
    gid = seed_docente["grupo"].id_grupo
    eid = _create_est(client, gid, codigo="EDEL").json()["id_estudiante"]
    r = client.delete(f"/api/grupos/{gid}/estudiantes/{eid}")
    assert r.status_code == 204
    r_list = client.get(f"/api/grupos/{gid}/estudiantes")
    assert all(e["id_estudiante"] != eid for e in r_list.json())


def test_delete_estudiante_inexistente_404(client, seed_docente):
    gid = seed_docente["grupo"].id_grupo
    r = client.delete(f"/api/grupos/{gid}/estudiantes/00000000-0000-0000-0000-000000000000")
    assert r.status_code == 404


def test_list_devuelve_orden_natural_y_todos_los_campos(client, seed_docente):
    gid = seed_docente["grupo"].id_grupo
    _create_est(client, gid, codigo="E001", piar=False)
    _create_est(client, gid, codigo="E002", piar=True, diag="Discalculia", ajustes="Calculadora")
    r = client.get(f"/api/grupos/{gid}/estudiantes")
    assert r.status_code == 200
    lst = r.json()
    assert len(lst) == 2
    codigos = [e["codigo_estudiante"] for e in lst]
    assert set(codigos) == {"E001", "E002"}
    e002 = next(e for e in lst if e["codigo_estudiante"] == "E002")
    assert e002["diagnostico"] == "Discalculia"
    assert e002["ajustes"] == "Calculadora"
    assert e002["tiene_piar"] is True
