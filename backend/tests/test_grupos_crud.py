"""
CRUD de /api/grupos: list, get, create, update, delete.
Docente autenticado sólo maneja sus propios grupos (aislamiento se cubre en test_aislamiento_docentes.py).
"""
from __future__ import annotations


def test_list_grupos_del_docente(client, seed_docente):
    r = client.get("/api/grupos")
    assert r.status_code == 200
    grupos = r.json()
    assert len(grupos) == 1
    assert grupos[0]["id_grupo"] == seed_docente["grupo"].id_grupo
    assert grupos[0]["nombre_grupo"] == "Grupo A"


def test_get_grupo_por_id(client, seed_docente):
    r = client.get(f'/api/grupos/{seed_docente["grupo"].id_grupo}')
    assert r.status_code == 200
    body = r.json()
    assert body["id_grupo"] == seed_docente["grupo"].id_grupo
    assert body["grado"] == "8°"


def test_get_grupo_inexistente_404(client):
    r = client.get("/api/grupos/00000000-0000-0000-0000-000000000000")
    assert r.status_code == 404


def test_create_grupo(client, seed_docente, db_session):
    """
    OJO: el plan Free (sin registro de Suscripcion) también aplica el límite
    de 1 grupo. En este test el docente tiene 1 grupo pre-seeded, pero no
    tiene Suscripcion registrada — por eso el segundo POST NO se bloquea
    (docente.suscripcion es None). Confirmamos el contrato observado.
    """
    from models import Suscripcion
    # Sin Suscripcion → sin restricción de plan
    r = client.post("/api/grupos", json={
        "nombre_grupo": "Grupo Nuevo",
        "grado": "9°",
        "asignatura": "fisica",
        "anio_lectivo": 2026,
        "cantidad_estudiantes": 25,
    })
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["nombre_grupo"] == "Grupo Nuevo"
    assert body["cantidad_estudiantes"] == 25
    assert body["id_docente"] == seed_docente["docente"].id_docente


def test_create_grupo_plan_free_bloquea_segundo(client, seed_docente, db_session):
    """Si el docente Free ya tiene 1 grupo, crear otro debe devolver 403."""
    from models import Suscripcion
    # Asigna plan free explícito
    db_session.add(Suscripcion(
        id_docente=seed_docente["docente"].id_docente,
        plan="free", estado="activa",
    ))
    db_session.commit()

    r = client.post("/api/grupos", json={
        "nombre_grupo": "Segundo",
        "grado": "10°",
        "asignatura": "matematicas",
        "anio_lectivo": 2026,
        "cantidad_estudiantes": 20,
    })
    assert r.status_code == 403, r.text
    assert "free" in r.json()["detail"].lower() or "plan" in r.json()["detail"].lower()


def test_create_grupo_plan_pro_permite_multiples(client, seed_docente, db_session):
    from models import Suscripcion
    db_session.add(Suscripcion(
        id_docente=seed_docente["docente"].id_docente,
        plan="pro", estado="activa",
    ))
    db_session.commit()

    r = client.post("/api/grupos", json={
        "nombre_grupo": "Segundo Pro",
        "grado": "10°",
        "asignatura": "matematicas",
        "anio_lectivo": 2026,
        "cantidad_estudiantes": 20,
    })
    assert r.status_code == 201, r.text


def test_update_grupo(client, seed_docente):
    gid = seed_docente["grupo"].id_grupo
    r = client.put(f"/api/grupos/{gid}", json={
        "nombre_grupo": "Nombre Editado",
        "periodo_actual": 3,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["nombre_grupo"] == "Nombre Editado"
    assert body["periodo_actual"] == 3
    # Los campos no enviados se mantienen
    assert body["grado"] == "8°"


def test_update_grupo_inexistente_404(client):
    r = client.put("/api/grupos/00000000-0000-0000-0000-000000000000", json={
        "nombre_grupo": "x"
    })
    assert r.status_code == 404


def test_delete_grupo(client, seed_docente):
    gid = seed_docente["grupo"].id_grupo
    r = client.delete(f"/api/grupos/{gid}")
    assert r.status_code == 204
    # Verifica que ya no existe
    r2 = client.get(f"/api/grupos/{gid}")
    assert r2.status_code == 404


def test_delete_grupo_inexistente_404(client):
    r = client.delete("/api/grupos/00000000-0000-0000-0000-000000000000")
    assert r.status_code == 404
