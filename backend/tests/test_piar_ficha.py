"""
Issue #48 — PIAR desde ficha del estudiante.

Cubre el cambio a `GET /api/piar/estudiante/{id_estudiante}`:
- Response ahora usa PIARResumenOut (sin `contenido` — pesado).
- Permisos multi-institución: docente dueño + coord/rector de la
  institución del docente-dueño pueden ver los PIARs; el resto → 404.
- Lista vacía → 200 [] (no 404) cuando el estudiante no tiene PIARs
  todavía; la ficha necesita distinguir "sin acceso" (404) de "sin
  historial aún" (200 []).

Todo corre sobre SQLite in-memory; ningún test llama a Claude.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


# ═══════════════════════════════════════════════════════════════
# Fixture — escenario con 2 instituciones + PIAR sembrado
# ═══════════════════════════════════════════════════════════════

@pytest.fixture
def escenario_piar_multi_inst(db_session):
    """
    Inst1 (Colegio Andes, plan='institucional'): rector R1, docente D1
    con grupo G1 y estudiante E1 con PIAR (con 2 versiones sembradas).
    Inst2 (Colegio Bosque, plan='free'): docente D2 con grupo G2 y
    estudiante E2 con PIAR (sin versiones sembradas — lista vacía).
    """
    from models import Docente, Grupo, Estudiante, Institucion, PIAR
    from auth import hash_password

    def _doc(email, nombre, inst, rol="docente"):
        # plan="activo" (sprint trial-7-dias) — ver nota en test_multi_institucion.py.
        d = Docente(
            nombre_completo=nombre, email=email,
            password_hash=hash_password("t"),
            id_institucion=inst.id_institucion, rol=rol,
            plan="activo",
        )
        db_session.add(d); db_session.commit(); db_session.refresh(d)
        return d

    def _grp(doc, nombre):
        g = Grupo(
            id_docente=doc.id_docente, nombre_grupo=nombre,
            grado="8°", asignatura="matematicas",
            anio_lectivo=2026, periodo_actual=1, cantidad_estudiantes=1,
        )
        db_session.add(g); db_session.commit(); db_session.refresh(g)
        return g

    def _est(g, codigo):
        e = Estudiante(id_grupo=g.id_grupo, codigo_estudiante=codigo, tiene_piar=True)
        db_session.add(e); db_session.commit(); db_session.refresh(e)
        return e

    inst1 = Institucion(nombre="Colegio Andes", plan="institucional")
    inst2 = Institucion(nombre="Colegio Bosque", plan="free")
    db_session.add_all([inst1, inst2]); db_session.commit()
    db_session.refresh(inst1); db_session.refresh(inst2)

    r1 = _doc("r1@andes.edu", "Rector Andes", inst1, rol="rector")
    d1 = _doc("d1@andes.edu", "Docente Andes", inst1)
    d2 = _doc("d2@bosque.edu", "Docente Bosque", inst2)

    g1 = _grp(d1, "Grupo Andes")
    g2 = _grp(d2, "Grupo Bosque")

    e1 = _est(g1, "ANDES01")
    e2 = _est(g2, "BOSQUE01")

    # 2 versiones de PIAR para e1 (para probar orden y count)
    for v, estado in [(1, "aprobado"), (2, "borrador")]:
        db_session.add(PIAR(
            id_estudiante=e1.id_estudiante, id_grupo=g1.id_grupo,
            id_docente=d1.id_docente,
            periodo=1, anio=2026, version=v,
            contenido={"caracterizacion": "sample"},
            estado=estado,
        ))
    db_session.commit()

    return {
        "inst1": inst1, "inst2": inst2,
        "r1": r1, "d1": d1, "d2": d2,
        "g1": g1, "g2": g2,
        "e1": e1, "e2": e2,
    }


@pytest.fixture
def client_piar_multi(test_engine, db_session, escenario_piar_multi_inst):
    from main import app
    from auth import get_current_docente
    from database import get_db

    def _override_get_db():
        try:
            yield db_session
        finally:
            pass
    app.dependency_overrides[get_db] = _override_get_db

    esc = escenario_piar_multi_inst
    current = {"actor": esc["d1"]}
    app.dependency_overrides[get_current_docente] = lambda: current["actor"]

    def como(nombre):
        current["actor"] = esc[nombre]

    with TestClient(app) as c:
        yield {"client": c, "como": como, "data": esc}

    app.dependency_overrides.clear()


# ═══════════════════════════════════════════════════════════════
# Tests — permisos y shape del response
# ═══════════════════════════════════════════════════════════════

def test_response_no_incluye_contenido(client_piar_multi):
    """
    El endpoint devuelve PIARResumenOut — sin el JSON pesado de contenido.
    La ficha materializa el DOCX vía descargar_docx cuando el docente lo pide.
    """
    d = client_piar_multi
    d["como"]("d1")
    r = d["client"].get(f'/api/piar/estudiante/{d["data"]["e1"].id_estudiante}')
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 2
    for p in body:
        assert "contenido" not in p, "Debe usar PIARResumenOut (sin contenido)"
        for campo in ("id_piar", "periodo", "anio", "version", "estado", "creado_en"):
            assert campo in p


def test_docente_dueno_ve_lista_ordenada_desc(client_piar_multi):
    """La lista viene ordenada por (anio, periodo, version) desc — la más nueva primero."""
    d = client_piar_multi
    d["como"]("d1")
    r = d["client"].get(f'/api/piar/estudiante/{d["data"]["e1"].id_estudiante}')
    assert r.status_code == 200
    versiones = [p["version"] for p in r.json()]
    assert versiones == [2, 1]  # v2 (borrador) primero, luego v1 (aprobado)


def test_docente_ajeno_recibe_404(client_piar_multi):
    """D2 (otra inst, otro docente) → 404, contrato: no revelar."""
    d = client_piar_multi
    d["como"]("d2")
    r = d["client"].get(f'/api/piar/estudiante/{d["data"]["e1"].id_estudiante}')
    assert r.status_code == 404


def test_rector_de_la_institucion_ve_piars_de_docente_de_su_inst(client_piar_multi):
    """
    R1 no es dueño del grupo, pero es rector de inst1 (misma inst que D1).
    Debe ver los PIARs de E1 (retro-compat con Issue #5).
    """
    d = client_piar_multi
    d["como"]("r1")
    r = d["client"].get(f'/api/piar/estudiante/{d["data"]["e1"].id_estudiante}')
    assert r.status_code == 200
    assert len(r.json()) == 2


def test_lista_vacia_devuelve_200_no_404(client_piar_multi):
    """
    E2 tiene tiene_piar=True pero cero PIARs sembrados. El endpoint devuelve
    lista vacía (200 []) — la ficha necesita distinguir "sin acceso" (404)
    de "todavía no generó ninguno" (200 []).
    """
    d = client_piar_multi
    d["como"]("d2")
    r = d["client"].get(f'/api/piar/estudiante/{d["data"]["e2"].id_estudiante}')
    assert r.status_code == 200
    assert r.json() == []
