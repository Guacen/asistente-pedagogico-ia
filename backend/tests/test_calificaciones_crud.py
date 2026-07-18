"""
CRUD de columnas de evaluación y calificaciones (libro de notas).
Endpoints:
- POST/GET/PUT/DELETE /api/grupos/{id}/columnas
- POST/PUT/DELETE /api/grupos/{id}/calificaciones
- POST /api/grupos/{id}/calificaciones/upsert
"""
from __future__ import annotations


def _seed_grupo_con_estudiante_y_columna(client, gid):
    est = client.post(f"/api/grupos/{gid}/estudiantes", json={
        "codigo_estudiante": "E001",
    }).json()
    col = client.post(f"/api/grupos/{gid}/columnas", json={
        "nombre": "Quiz 1", "periodo": 1, "tipo": "quiz", "porcentaje": 100
    }).json()
    return est, col


# ─── COLUMNAS ─────────────────────────────────────────────────────────────

def test_create_columna(client, seed_docente):
    gid = seed_docente["grupo"].id_grupo
    r = client.post(f"/api/grupos/{gid}/columnas", json={
        "nombre": "Parcial", "periodo": 1, "tipo": "parcial", "porcentaje": 40
    })
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["nombre"] == "Parcial"
    assert body["porcentaje"] == 40


def test_list_columnas_ordenadas_por_periodo_orden(client, seed_docente):
    gid = seed_docente["grupo"].id_grupo
    for i, n in enumerate(["C", "A", "B"]):
        client.post(f"/api/grupos/{gid}/columnas", json={
            "nombre": n, "periodo": 1, "tipo": "quiz", "porcentaje": 33, "orden": i
        })
    r = client.get(f"/api/grupos/{gid}/columnas")
    assert r.status_code == 200
    ordered = [c["nombre"] for c in r.json()]
    assert ordered == ["C", "A", "B"]  # orden por columna 'orden' asc


def test_filter_columnas_por_periodo(client, seed_docente):
    gid = seed_docente["grupo"].id_grupo
    client.post(f"/api/grupos/{gid}/columnas", json={
        "nombre": "P1", "periodo": 1, "porcentaje": 50
    })
    client.post(f"/api/grupos/{gid}/columnas", json={
        "nombre": "P2", "periodo": 2, "porcentaje": 50
    })
    r = client.get(f"/api/grupos/{gid}/columnas?periodo=2")
    assert r.status_code == 200
    lst = r.json()
    assert [c["nombre"] for c in lst] == ["P2"]


def test_update_columna(client, seed_docente):
    gid = seed_docente["grupo"].id_grupo
    col = client.post(f"/api/grupos/{gid}/columnas", json={
        "nombre": "Original", "porcentaje": 30
    }).json()
    r = client.put(f"/api/grupos/{gid}/columnas/{col['id_columna']}", json={
        "nombre": "Actualizado", "porcentaje": 50
    })
    assert r.status_code == 200, r.text
    assert r.json()["nombre"] == "Actualizado"
    assert r.json()["porcentaje"] == 50


def test_delete_columna(client, seed_docente):
    gid = seed_docente["grupo"].id_grupo
    col = client.post(f"/api/grupos/{gid}/columnas", json={"nombre": "X"}).json()
    r = client.delete(f"/api/grupos/{gid}/columnas/{col['id_columna']}")
    assert r.status_code == 204
    assert client.get(f"/api/grupos/{gid}/columnas").json() == []


def test_delete_columna_inexistente_404(client, seed_docente):
    gid = seed_docente["grupo"].id_grupo
    r = client.delete(f"/api/grupos/{gid}/columnas/00000000-0000-0000-0000-000000000000")
    assert r.status_code == 404


# ─── CALIFICACIONES ─────────────────────────────────────────────────────────

def test_upsert_calificacion_crea_y_luego_actualiza(client, seed_docente):
    gid = seed_docente["grupo"].id_grupo
    est, col = _seed_grupo_con_estudiante_y_columna(client, gid)

    # Primer upsert → crea
    r1 = client.post(f"/api/grupos/{gid}/calificaciones/upsert", json={
        "id_estudiante": est["id_estudiante"],
        "id_columna": col["id_columna"],
        "valor": 4.5, "periodo": 1,
    })
    assert r1.status_code == 200
    assert r1.json()["valor"] == 4.5

    # Segundo upsert → actualiza (misma calificación, otro valor)
    r2 = client.post(f"/api/grupos/{gid}/calificaciones/upsert", json={
        "id_estudiante": est["id_estudiante"],
        "id_columna": col["id_columna"],
        "valor": 3.2, "periodo": 1,
    })
    assert r2.status_code == 200
    assert r2.json()["valor"] == 3.2

    # Debe haber exactamente 1 calificación (no dos)
    lst = client.get(f"/api/grupos/{gid}/calificaciones").json()
    filtered = [c for c in lst if c["id_estudiante"] == est["id_estudiante"] and c["id_columna"] == col["id_columna"]]
    assert len(filtered) == 1
    assert filtered[0]["valor"] == 3.2


def test_upsert_estudiante_ajeno_al_grupo_404(client, seed_docente, seed_docente_b, db_session):
    """
    Docente A intenta calificar a un estudiante que pertenece al grupo de B
    usando el path del grupo de A → 404.
    """
    from models import Estudiante
    est_b = Estudiante(id_grupo=seed_docente_b["grupo"].id_grupo, codigo_estudiante="EBX")
    db_session.add(est_b)
    db_session.commit()
    db_session.refresh(est_b)

    gid_a = seed_docente["grupo"].id_grupo
    _, col_a = _seed_grupo_con_estudiante_y_columna(client, gid_a)
    r = client.post(f"/api/grupos/{gid_a}/calificaciones/upsert", json={
        "id_estudiante": est_b.id_estudiante,
        "id_columna": col_a["id_columna"],
        "valor": 5.0, "periodo": 1,
    })
    assert r.status_code == 404


def test_upsert_columna_ajena_al_grupo_404(client, seed_docente, seed_docente_b, db_session):
    """Estudiante propio pero columna de otro grupo → 404."""
    from models import EvaluacionColumna
    col_b = EvaluacionColumna(
        id_grupo=seed_docente_b["grupo"].id_grupo,
        nombre="Col B", periodo=1, tipo="quiz", porcentaje=100, orden=0,
    )
    db_session.add(col_b)
    db_session.commit()
    db_session.refresh(col_b)

    gid_a = seed_docente["grupo"].id_grupo
    est_a, _ = _seed_grupo_con_estudiante_y_columna(client, gid_a)
    r = client.post(f"/api/grupos/{gid_a}/calificaciones/upsert", json={
        "id_estudiante": est_a["id_estudiante"],
        "id_columna": col_b.id_columna,
        "valor": 4.0, "periodo": 1,
    })
    assert r.status_code == 404


def test_list_calificaciones_incluye_fecha(client, seed_docente):
    gid = seed_docente["grupo"].id_grupo
    est, col = _seed_grupo_con_estudiante_y_columna(client, gid)
    client.post(f"/api/grupos/{gid}/calificaciones/upsert", json={
        "id_estudiante": est["id_estudiante"],
        "id_columna": col["id_columna"],
        "valor": 4.0, "periodo": 1,
    })
    lst = client.get(f"/api/grupos/{gid}/calificaciones").json()
    assert len(lst) == 1
    assert "fecha" in lst[0]


def test_create_calificacion_manual_y_update(client, seed_docente):
    """POST /calificaciones (no upsert) crea uno nuevo con tipo/descripcion."""
    gid = seed_docente["grupo"].id_grupo
    est = client.post(f"/api/grupos/{gid}/estudiantes", json={"codigo_estudiante": "E1"}).json()
    r = client.post(f"/api/grupos/{gid}/calificaciones", json={
        "id_estudiante": est["id_estudiante"],
        "periodo": 1, "tipo": "oral", "descripcion": "Exposición",
        "valor": 4.7, "porcentaje": 10,
    })
    assert r.status_code == 201, r.text
    cid = r.json()["id_calificacion"]

    r_upd = client.put(f"/api/grupos/{gid}/calificaciones/{cid}", json={"valor": 5.0})
    assert r_upd.status_code == 200
    assert r_upd.json()["valor"] == 5.0

    r_del = client.delete(f"/api/grupos/{gid}/calificaciones/{cid}")
    assert r_del.status_code == 204


def test_create_calificacion_estudiante_ajeno_404(client, seed_docente, seed_docente_b, db_session):
    from models import Estudiante
    est_b = Estudiante(id_grupo=seed_docente_b["grupo"].id_grupo, codigo_estudiante="EBY")
    db_session.add(est_b); db_session.commit(); db_session.refresh(est_b)
    gid_a = seed_docente["grupo"].id_grupo
    r = client.post(f"/api/grupos/{gid_a}/calificaciones", json={
        "id_estudiante": est_b.id_estudiante, "periodo": 1,
        "tipo": "quiz", "valor": 4.0,
    })
    assert r.status_code == 404
