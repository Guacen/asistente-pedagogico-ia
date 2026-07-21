"""
Fase B — Aislamiento entre docentes.

Confirma que un docente autenticado NUNCA puede ver/editar/borrar recursos
que pertenecen a otro docente, ni manipulando IDs en la URL.

Modelo actual: Grupo.id_docente FK → 1 docente = N grupos, no hay compartir.
El día que se implemente coordinador/multi-docente (Issue #5), estos tests
tendrán que actualizarse para reflejar los nuevos permisos.

Contrato observado: el backend responde 404 (no 403) para recursos ajenos.
Esto es intencional — no revela existencia del recurso.
"""
from __future__ import annotations

import io


def _upload_csv(client, gid, text):
    return client.post(
        f"/api/grupos/{gid}/estudiantes/importar",
        files={"file": ("t.csv", io.BytesIO(text.encode()), "text/csv")},
    )


# ─── GRUPOS ────────────────────────────────────────────────────────────────

def test_a_no_ve_grupo_de_b_en_lista(client_two_docentes):
    """
    Docente A hace GET /api/grupos → sólo debe ver su propio grupo,
    aunque en la DB también exista el de B.
    """
    d = client_two_docentes
    d["as_a"]()
    r = d["client"].get("/api/grupos")
    assert r.status_code == 200
    grupos = r.json()
    ids = [g["id_grupo"] for g in grupos]
    assert d["data"]["a"]["grupo"].id_grupo in ids
    assert d["data"]["b"]["grupo"].id_grupo not in ids


def test_a_no_puede_leer_grupo_de_b_por_id(client_two_docentes):
    d = client_two_docentes
    d["as_a"]()
    r = d["client"].get(f'/api/grupos/{d["data"]["b"]["grupo"].id_grupo}')
    assert r.status_code == 404


def test_a_no_puede_editar_grupo_de_b(client_two_docentes):
    d = client_two_docentes
    d["as_a"]()
    r = d["client"].put(
        f'/api/grupos/{d["data"]["b"]["grupo"].id_grupo}',
        json={"nombre_grupo": "hackeado"},
    )
    assert r.status_code == 404
    # Y el nombre real del grupo B no cambió — cambio a B para confirmar
    d["as_b"]()
    r2 = d["client"].get(f'/api/grupos/{d["data"]["b"]["grupo"].id_grupo}')
    assert r2.status_code == 200
    assert r2.json()["nombre_grupo"] == "Grupo B"


def test_a_no_puede_borrar_grupo_de_b(client_two_docentes):
    d = client_two_docentes
    d["as_a"]()
    r = d["client"].delete(f'/api/grupos/{d["data"]["b"]["grupo"].id_grupo}')
    assert r.status_code == 404
    # B todavía puede verlo
    d["as_b"]()
    r2 = d["client"].get(f'/api/grupos/{d["data"]["b"]["grupo"].id_grupo}')
    assert r2.status_code == 200


# ─── ESTUDIANTES ───────────────────────────────────────────────────────────

def test_a_no_puede_listar_estudiantes_de_grupo_de_b(client_two_docentes):
    d = client_two_docentes
    # Primero, B crea un estudiante en su grupo
    d["as_b"]()
    d["client"].post(
        f'/api/grupos/{d["data"]["b"]["grupo"].id_grupo}/estudiantes',
        json={"codigo_estudiante": "EB01"},
    )
    # A intenta listar → 404
    d["as_a"]()
    r = d["client"].get(f'/api/grupos/{d["data"]["b"]["grupo"].id_grupo}/estudiantes')
    assert r.status_code == 404


def test_a_no_puede_crear_estudiante_en_grupo_de_b(client_two_docentes):
    d = client_two_docentes
    d["as_a"]()
    r = d["client"].post(
        f'/api/grupos/{d["data"]["b"]["grupo"].id_grupo}/estudiantes',
        json={"codigo_estudiante": "INJECT"},
    )
    assert r.status_code == 404


def test_a_no_puede_editar_estudiante_de_b(client_two_docentes, db_session):
    from models import Estudiante
    est_b = Estudiante(
        id_grupo=client_two_docentes["data"]["b"]["grupo"].id_grupo,
        codigo_estudiante="EBEDIT",
    )
    db_session.add(est_b); db_session.commit(); db_session.refresh(est_b)

    d = client_two_docentes
    d["as_a"]()
    # Camino 1: path grupo de A + estudiante de B → 404 (estudiante no está en A)
    r1 = d["client"].put(
        f'/api/grupos/{d["data"]["a"]["grupo"].id_grupo}/estudiantes/{est_b.id_estudiante}',
        json={"codigo_estudiante": "hack"},
    )
    assert r1.status_code == 404

    # Camino 2: path grupo de B + estudiante de B → 404 (grupo no es de A)
    r2 = d["client"].put(
        f'/api/grupos/{d["data"]["b"]["grupo"].id_grupo}/estudiantes/{est_b.id_estudiante}',
        json={"codigo_estudiante": "hack"},
    )
    assert r2.status_code == 404


def test_a_no_puede_borrar_estudiante_de_b(client_two_docentes, db_session):
    from models import Estudiante
    est_b = Estudiante(
        id_grupo=client_two_docentes["data"]["b"]["grupo"].id_grupo,
        codigo_estudiante="EBDEL",
    )
    db_session.add(est_b); db_session.commit(); db_session.refresh(est_b)

    d = client_two_docentes
    d["as_a"]()
    r = d["client"].delete(
        f'/api/grupos/{d["data"]["b"]["grupo"].id_grupo}/estudiantes/{est_b.id_estudiante}'
    )
    assert r.status_code == 404


# ─── IMPORT CSV ────────────────────────────────────────────────────────────

def test_a_no_puede_importar_csv_en_grupo_de_b(client_two_docentes):
    d = client_two_docentes
    d["as_a"]()
    csv = "codigo_estudiante\nHACK1\nHACK2\n"
    r = _upload_csv(d["client"], d["data"]["b"]["grupo"].id_grupo, csv)
    assert r.status_code == 404
    # Confirmar que no se creó nada
    d["as_b"]()
    ests_b = d["client"].get(
        f'/api/grupos/{d["data"]["b"]["grupo"].id_grupo}/estudiantes'
    ).json()
    assert not any(e["codigo_estudiante"].startswith("HACK") for e in ests_b)


# ─── CALIFICACIONES Y COLUMNAS ─────────────────────────────────────────────

def test_a_no_puede_leer_calificaciones_de_b(client_two_docentes):
    d = client_two_docentes
    d["as_a"]()
    r = d["client"].get(
        f'/api/grupos/{d["data"]["b"]["grupo"].id_grupo}/calificaciones'
    )
    assert r.status_code == 404


def test_a_no_puede_crear_columna_en_grupo_de_b(client_two_docentes):
    d = client_two_docentes
    d["as_a"]()
    r = d["client"].post(
        f'/api/grupos/{d["data"]["b"]["grupo"].id_grupo}/columnas',
        json={"nombre": "Inyectada", "porcentaje": 100},
    )
    assert r.status_code == 404


def test_a_no_puede_borrar_columna_de_b(client_two_docentes, db_session):
    from models import EvaluacionColumna
    col_b = EvaluacionColumna(
        id_grupo=client_two_docentes["data"]["b"]["grupo"].id_grupo,
        nombre="Col B", periodo=1, tipo="quiz", porcentaje=100, orden=0,
    )
    db_session.add(col_b); db_session.commit(); db_session.refresh(col_b)

    d = client_two_docentes
    d["as_a"]()
    # A intenta borrar la columna de B usando cualquier grupo del path
    r1 = d["client"].delete(
        f'/api/grupos/{d["data"]["a"]["grupo"].id_grupo}/columnas/{col_b.id_columna}'
    )
    assert r1.status_code == 404
    r2 = d["client"].delete(
        f'/api/grupos/{d["data"]["b"]["grupo"].id_grupo}/columnas/{col_b.id_columna}'
    )
    assert r2.status_code == 404


def test_a_no_puede_upsert_calificacion_en_grupo_de_b(client_two_docentes, db_session):
    """
    Prueba de vector completo: A intenta calificar a un estudiante de B
    usando la columna de B, apuntando al grupo de B en el path.
    """
    from models import Estudiante, EvaluacionColumna
    grupo_b_id = client_two_docentes["data"]["b"]["grupo"].id_grupo
    est_b = Estudiante(id_grupo=grupo_b_id, codigo_estudiante="EBCAL")
    col_b = EvaluacionColumna(id_grupo=grupo_b_id, nombre="C", periodo=1, porcentaje=100)
    db_session.add_all([est_b, col_b]); db_session.commit()
    db_session.refresh(est_b); db_session.refresh(col_b)

    d = client_two_docentes
    d["as_a"]()
    r = d["client"].post(
        f'/api/grupos/{grupo_b_id}/calificaciones/upsert',
        json={
            "id_estudiante": est_b.id_estudiante,
            "id_columna": col_b.id_columna,
            "valor": 1.0, "periodo": 1,
        },
    )
    assert r.status_code == 404


# ─── NOTAS ─────────────────────────────────────────────────────────────────

def test_a_no_puede_leer_notas_de_grupo_de_b(client_two_docentes):
    d = client_two_docentes
    d["as_b"]()
    d["client"].post(
        f'/api/grupos/{d["data"]["b"]["grupo"].id_grupo}/notas',
        json={"contenido": "Nota privada de B"},
    )
    d["as_a"]()
    r = d["client"].get(f'/api/grupos/{d["data"]["b"]["grupo"].id_grupo}/notas')
    assert r.status_code == 404


# ─── ARCHIVOS ──────────────────────────────────────────────────────────────

def test_a_no_puede_listar_archivos_de_b(client_two_docentes):
    d = client_two_docentes
    d["as_a"]()
    r = d["client"].get(f'/api/grupos/{d["data"]["b"]["grupo"].id_grupo}/archivos')
    assert r.status_code == 404
