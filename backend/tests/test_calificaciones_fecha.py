"""
Test: /api/grupos/{id}/calificaciones expone Calificacion.fecha en la respuesta.

Panel Docente usa este campo para la alerta de "grupo inactivo hace 14 días+"
(parseFechaISO en panel-docente.html). Sin este campo la alerta falla silenciosa.
"""
from __future__ import annotations


def _crear_estudiante_y_columna(client, gid):
    est = client.post(
        f"/api/grupos/{gid}/estudiantes",
        json={"codigo_estudiante": "E001", "genero": "M"},
    ).json()
    col = client.post(
        f"/api/grupos/{gid}/columnas",
        json={"nombre": "Quiz 1", "periodo": 1, "tipo": "quiz", "porcentaje": 100},
    ).json()
    return est["id_estudiante"], col["id_columna"]


def test_get_calificaciones_incluye_fecha_iso_parseable(client, seed_docente):
    gid = seed_docente["grupo"].id_grupo
    est_id, col_id = _crear_estudiante_y_columna(client, gid)

    # Crea una nota vía upsert
    r_upsert = client.post(
        f"/api/grupos/{gid}/calificaciones/upsert",
        json={"id_estudiante": est_id, "id_columna": col_id, "valor": 4.5, "periodo": 1},
    )
    assert r_upsert.status_code == 200, r_upsert.text

    # GET debe devolver la nota con `fecha` en formato ISO 8601 parseable
    r_list = client.get(f"/api/grupos/{gid}/calificaciones")
    assert r_list.status_code == 200
    notas = r_list.json()
    assert len(notas) == 1
    nota = notas[0]

    # Contrato observado por el frontend (panel-docente.html usa Date.parse(fecha))
    assert "fecha" in nota, f"Falta campo 'fecha' en la respuesta: {nota}"
    from datetime import datetime
    fecha_str = nota["fecha"]
    parsed = datetime.fromisoformat(fecha_str.replace("Z", "+00:00")) if fecha_str.endswith("Z") \
        else datetime.fromisoformat(fecha_str)
    assert parsed.year >= 2020, f"Fecha implausible: {fecha_str}"


def test_upsert_devuelve_fecha_en_response(client, seed_docente):
    """El endpoint de upsert también debe devolver `fecha` en su response."""
    gid = seed_docente["grupo"].id_grupo
    est_id, col_id = _crear_estudiante_y_columna(client, gid)

    r = client.post(
        f"/api/grupos/{gid}/calificaciones/upsert",
        json={"id_estudiante": est_id, "id_columna": col_id, "valor": 3.2, "periodo": 1},
    )
    assert r.status_code == 200
    body = r.json()
    assert "fecha" in body, f"upsert response sin 'fecha': {body}"
    assert body["valor"] == 3.2
