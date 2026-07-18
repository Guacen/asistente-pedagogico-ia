"""
Tests de integración para POST /api/grupos/{grupo_id}/estudiantes/importar.

Cubre:
- Contrato de respuesta {creados, actualizados, fallidos, errores[]}.
- Upsert por (id_grupo, codigo_estudiante).
- Fila inválida / vacía → cuenta como fallida con mensaje.
- Encabezado incompleto → 400.
- Filas totalmente vacías → NO se cuentan (consistencia con preview del frontend).
- Rechazo de archivos que no sean .csv.
"""
from __future__ import annotations

import io

import pytest


ENDPOINT = "/api/grupos/{gid}/estudiantes/importar"


def _upload(client, grupo_id: str, csv_text: str, filename: str = "test.csv"):
    return client.post(
        ENDPOINT.format(gid=grupo_id),
        files={"file": (filename, io.BytesIO(csv_text.encode("utf-8")), "text/csv")},
    )


def test_creacion_basica(client, seed_docente):
    gid = seed_docente["grupo"].id_grupo
    csv = (
        "codigo_estudiante,genero,tiene_piar,diagnostico,ajustes\n"
        "E001,M,0,,\n"
        "E002,F,1,TDA,Instrucciones cortas\n"
    )
    r = _upload(client, gid, csv)
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body.keys()) == {"creados", "actualizados", "fallidos", "errores"}
    assert body["creados"] == 2
    assert body["actualizados"] == 0
    assert body["fallidos"] == 0
    assert body["errores"] == []


def test_upsert_actualiza_existente(client, seed_docente, db_session):
    """Segundo import del mismo codigo_estudiante debe actualizar, no duplicar."""
    from models import Estudiante
    gid = seed_docente["grupo"].id_grupo

    # Primer import
    csv1 = (
        "codigo_estudiante,genero,tiene_piar,diagnostico,ajustes\n"
        "E100,M,0,,\n"
    )
    r1 = _upload(client, gid, csv1)
    assert r1.status_code == 200
    assert r1.json()["creados"] == 1

    # Segundo import: mismo código, otros campos → actualiza
    csv2 = (
        "codigo_estudiante,genero,tiene_piar,diagnostico,ajustes\n"
        "E100,F,1,TDA,Ajustes nuevos\n"
    )
    r2 = _upload(client, gid, csv2)
    body2 = r2.json()
    assert body2["creados"] == 0
    assert body2["actualizados"] == 1
    assert body2["fallidos"] == 0

    # Verifica que sólo hay 1 estudiante en la DB y sus campos son los nuevos.
    ests = db_session.query(Estudiante).filter(Estudiante.id_grupo == gid).all()
    assert len(ests) == 1
    est = ests[0]
    assert est.codigo_estudiante == "E100"
    assert est.genero == "F"
    assert est.tiene_piar is True
    assert est.diagnostico == "TDA"
    assert est.ajustes == "Ajustes nuevos"


def test_fila_con_codigo_vacio_es_fallida(client, seed_docente):
    """Fila con codigo_estudiante vacío debe reportarse como fallida con mensaje."""
    gid = seed_docente["grupo"].id_grupo
    csv = (
        "codigo_estudiante,genero,tiene_piar,diagnostico,ajustes\n"
        "E001,M,0,,\n"
        ",F,1,,\n"  # fila con código vacío
        "E002,F,0,,\n"
    )
    body = _upload(client, gid, csv).json()
    assert body["creados"] == 2
    assert body["fallidos"] == 1
    assert len(body["errores"]) == 1
    # Mensaje debe mencionar la columna específica (no solo "fila inválida")
    err = body["errores"][0]
    assert "codigo_estudiante" in err.lower()
    assert "Fila 3" in err   # el número de línea del CSV


def test_fila_con_tiene_piar_no_reconocido_es_fallida(client, seed_docente):
    """
    tiene_piar='maybe' no está en {1,0,true,false,sí,no,...} → debe reportarse
    como fallida con mensaje que mencione la columna y el valor.
    """
    gid = seed_docente["grupo"].id_grupo
    csv = (
        "codigo_estudiante,genero,tiene_piar,diagnostico,ajustes\n"
        "E001,M,maybe,,\n"
        "E002,F,1,,\n"
    )
    body = _upload(client, gid, csv).json()
    assert body["creados"] == 1
    assert body["fallidos"] == 1
    err = body["errores"][0]
    assert "tiene_piar" in err
    assert "maybe" in err
    assert "Fila 2" in err


def test_filas_totalmente_vacias_se_ignoran(client, seed_docente):
    """
    Las filas donde TODAS las celdas son vacías deben filtrarse silenciosamente,
    para que el preview del frontend y el resultado del backend coincidan.
    """
    gid = seed_docente["grupo"].id_grupo
    csv = (
        "codigo_estudiante,genero,tiene_piar,diagnostico,ajustes\n"
        "E001,M,0,,\n"
        ",,,,\n"        # totalmente vacía → NO cuenta
        "E002,F,1,,\n"
        ",,,,\n"        # otra vacía
    )
    body = _upload(client, gid, csv).json()
    assert body["creados"] == 2
    assert body["actualizados"] == 0
    assert body["fallidos"] == 0, f"filas vacías no deben contar como fallidas — errores: {body['errores']}"


def test_encabezado_sin_codigo_estudiante_devuelve_400(client, seed_docente):
    gid = seed_docente["grupo"].id_grupo
    csv = "genero,tiene_piar\nM,0\n"
    r = _upload(client, gid, csv)
    assert r.status_code == 400
    assert "codigo_estudiante" in r.text


def test_archivo_no_csv_devuelve_400(client, seed_docente):
    gid = seed_docente["grupo"].id_grupo
    r = client.post(
        ENDPOINT.format(gid=gid),
        files={"file": ("data.txt", io.BytesIO(b"cualquier cosa"), "text/plain")},
    )
    assert r.status_code == 400


@pytest.mark.parametrize("piar_raw,expected", [
    ("1", True), ("0", False),
    ("true", True), ("false", False),
    ("True", True), ("FALSE", False),
    ("sí", True), ("no", False),
    ("SÍ", True), ("NO", False),
    ("si", True),
    ("", False),
])
def test_tiene_piar_es_case_insensitive(client, seed_docente, db_session, piar_raw, expected):
    """tiene_piar acepta 1/0/true/false/sí/no en mayúsculas y minúsculas."""
    from models import Estudiante
    gid = seed_docente["grupo"].id_grupo
    codigo = f"P_{piar_raw or 'empty'}_{expected}"
    csv = (
        "codigo_estudiante,genero,tiene_piar,diagnostico,ajustes\n"
        f"{codigo},M,{piar_raw},,\n"
    )
    r = _upload(client, gid, csv)
    assert r.status_code == 200, r.text
    est = db_session.query(Estudiante).filter(
        Estudiante.id_grupo == gid,
        Estudiante.codigo_estudiante == codigo,
    ).first()
    assert est is not None, f"No se creó estudiante para tiene_piar={piar_raw!r}"
    assert est.tiene_piar is expected, f"tiene_piar={piar_raw!r} → esperado {expected}, got {est.tiene_piar}"
