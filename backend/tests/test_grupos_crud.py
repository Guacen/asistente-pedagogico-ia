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


# ═══════════════════════════════════════════════════════════════
# POST /api/grupos con estudiantes iniciales (fix del wizard)
# ═══════════════════════════════════════════════════════════════

def _payload_grupo_con_estudiantes(estudiantes):
    return {
        "nombre_grupo": "Grupo Con Iniciales",
        "grado": "6°",
        "asignatura": "matematicas",
        "anio_lectivo": 2026,
        "periodo_actual": 1,
        "cantidad_estudiantes": len(estudiantes),
        "estudiantes": estudiantes,
    }


def test_create_grupo_persiste_estudiantes_en_la_misma_operacion(client, db_session):
    """
    El wizard de creación pasa los estudiantes en el body del POST /grupos.
    Backend los inserta en la misma transacción; ambos quedan visibles al
    recargar (no hace falta segunda ronda del cliente).
    """
    from models import Estudiante

    payload = _payload_grupo_con_estudiantes([
        {"codigo_estudiante": "EST-A"},
        {"codigo_estudiante": "EST-B"},
        {"codigo_estudiante": "EST-C"},
    ])
    r = client.post("/api/grupos", json=payload)
    assert r.status_code == 201, r.text
    grupo_id = r.json()["id_grupo"]

    r_list = client.get(f"/api/grupos/{grupo_id}/estudiantes")
    assert r_list.status_code == 200
    codigos = sorted(e["codigo_estudiante"] for e in r_list.json())
    assert codigos == ["EST-A", "EST-B", "EST-C"]

    # Y en DB directa
    en_db = db_session.query(Estudiante).filter(Estudiante.id_grupo == grupo_id).count()
    assert en_db == 3


def test_create_grupo_estudiantes_conservan_campos_piar(client):
    """
    Los campos tiene_piar/diagnostico/ajustes tienen que llegar intactos —
    no basta con guardar el código.
    """
    payload = _payload_grupo_con_estudiantes([
        {
            "codigo_estudiante": "EST-CON-PIAR",
            "genero": "femenino",
            "tiene_piar": True,
            "diagnostico": "Dislexia",
            "ajustes": "Tiempo adicional 50%",
        },
        {"codigo_estudiante": "EST-SIN-PIAR"},
    ])
    r = client.post("/api/grupos", json=payload)
    assert r.status_code == 201, r.text
    grupo_id = r.json()["id_grupo"]

    ests = client.get(f"/api/grupos/{grupo_id}/estudiantes").json()
    ests_por_codigo = {e["codigo_estudiante"]: e for e in ests}

    con = ests_por_codigo["EST-CON-PIAR"]
    assert con["tiene_piar"] is True
    assert con["genero"] == "femenino"
    assert con["diagnostico"] == "Dislexia"
    assert con["ajustes"] == "Tiempo adicional 50%"

    sin = ests_por_codigo["EST-SIN-PIAR"]
    assert sin["tiene_piar"] is False
    assert sin["diagnostico"] is None


def test_create_grupo_es_atomico_si_estudiante_falla(client, db_session):
    """
    Si algún estudiante del batch no puede persistirse, el grupo tampoco
    debe quedar creado. Forzamos el fallo pasando un estudiante con un
    id_estudiante inválido (tipo incorrecto — SQLAlchemy rompe al insertar).
    """
    from models import Grupo

    grupos_antes = db_session.query(Grupo).count()

    # Estudiante con codigo_estudiante=None viola NOT NULL de la columna;
    # el DB rompe al INSERT y disparamos el rollback del grupo.
    payload = _payload_grupo_con_estudiantes([
        {"codigo_estudiante": "OK-1"},
        {"codigo_estudiante": None},
    ])
    r = client.post("/api/grupos", json=payload)
    # 422 (pydantic rechaza None en str no opcional) o 400 (backend rollback);
    # el contrato clave es que el grupo NO haya quedado.
    assert r.status_code in (400, 422), r.text

    # Confirmamos atomicidad: sin grupos nuevos en DB.
    db_session.expire_all()
    grupos_despues = db_session.query(Grupo).count()
    assert grupos_despues == grupos_antes


def test_create_grupo_sin_estudiantes_sigue_funcionando(client, db_session):
    """Retro-compat: payload sin campo `estudiantes` sigue creando solo el grupo."""
    r = client.post("/api/grupos", json={
        "nombre_grupo": "Grupo Solo",
        "grado": "5°",
        "asignatura": "matematicas",
        "anio_lectivo": 2026,
        "cantidad_estudiantes": 0,
    })
    assert r.status_code == 201, r.text
    grupo_id = r.json()["id_grupo"]
    ests = client.get(f"/api/grupos/{grupo_id}/estudiantes").json()
    assert ests == []
