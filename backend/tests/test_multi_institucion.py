"""
Sprint multi-institución (Issue #5) — tests de integración.

Cubre los tres pilares del sprint:

1. Aislamiento cross-institución
   - Un docente 'docente' no ve grupos de otra institución (retro-compat total).
   - Un coordinador SÍ ve grupos de su institución (via /api/institucion/grupos).
   - Un coordinador NO ve grupos de OTRA institución.
   - Un rol 'docente' recibe 403 en endpoints admin.

2. Endpoints /api/institucion (get / put / docentes / invitar / rol / delete)
   - Invitar sin plan='institucional' → 403.
   - Invitar a docente solo en su institución uni-personal → mueve + borra huérfana.
   - Invitar a docente en institución compartida → 409.
   - Rector cambia rol → 200; auto-modificación → 409.
   - Promover a coord/rector sin plan institucional → 403.
   - Remover docente → crea institución uni-personal nueva para el removido.

3. Dashboard institucional (agregados)
   - KPIs consolidados incluyen todos los docentes de la institución.

Todos los tests corren sobre SQLite in-memory (fixtures del conftest).
NUNCA se llama a Claude real. NUNCA se toca la DB de dev.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


# ═══════════════════════════════════════════════════════════════
# Fixtures — dos instituciones completas
# ═══════════════════════════════════════════════════════════════

def _mk_docente(db, email, nombre, id_institucion=None, rol="docente"):
    from models import Docente
    from auth import hash_password
    d = Docente(
        nombre_completo=nombre,
        email=email,
        password_hash=hash_password("test1234"),
        id_institucion=id_institucion,
        rol=rol,
    )
    db.add(d)
    db.commit()
    db.refresh(d)
    return d


def _mk_grupo(db, docente, nombre):
    from models import Grupo
    g = Grupo(
        id_docente=docente.id_docente,
        nombre_grupo=nombre,
        grado="8°",
        asignatura="matematicas",
        anio_lectivo=2026,
        periodo_actual=1,
        cantidad_estudiantes=5,
    )
    db.add(g)
    db.commit()
    db.refresh(g)
    return g


@pytest.fixture
def escenario_dos_instituciones(db_session):
    """
    Escenario:
    - Inst1 (Colegio Andes, plan='institucional'): rector R1, coord C1,
      docentes D1a y D1b, cada uno con un grupo.
    - Inst2 (Colegio Bosque, plan='free'): docente D2 con su grupo,
      uni-personal (típica del backfill de migración).
    """
    from models import Institucion

    inst1 = Institucion(nombre="Colegio Andes", plan="institucional")
    inst2 = Institucion(nombre="Colegio Bosque", plan="free")
    db_session.add_all([inst1, inst2])
    db_session.commit()
    db_session.refresh(inst1)
    db_session.refresh(inst2)

    r1 = _mk_docente(db_session, "rector@andes.edu", "Rector Andes",
                     id_institucion=inst1.id_institucion, rol="rector")
    c1 = _mk_docente(db_session, "coord@andes.edu", "Coord Andes",
                     id_institucion=inst1.id_institucion, rol="coordinador")
    d1a = _mk_docente(db_session, "d1a@andes.edu", "Docente 1A",
                      id_institucion=inst1.id_institucion, rol="docente")
    d1b = _mk_docente(db_session, "d1b@andes.edu", "Docente 1B",
                      id_institucion=inst1.id_institucion, rol="docente")

    d2 = _mk_docente(db_session, "d2@bosque.edu", "Docente Bosque",
                     id_institucion=inst2.id_institucion, rol="docente")

    g1a = _mk_grupo(db_session, d1a, "Grupo 1A")
    g1b = _mk_grupo(db_session, d1b, "Grupo 1B")
    g2 = _mk_grupo(db_session, d2, "Grupo Bosque")

    return {
        "inst1": inst1, "inst2": inst2,
        "r1": r1, "c1": c1, "d1a": d1a, "d1b": d1b, "d2": d2,
        "g1a": g1a, "g1b": g1b, "g2": g2,
    }


@pytest.fixture
def client_multi(test_engine, db_session, escenario_dos_instituciones):
    """
    TestClient con actor swappeable — as(nombre) cambia el docente
    autenticado al vuelo. Usa el patrón de client_two_docentes.
    """
    from main import app
    from auth import get_current_docente
    from database import get_db

    def _override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = _override_get_db

    esc = escenario_dos_instituciones
    current = {"actor": esc["r1"]}
    app.dependency_overrides[get_current_docente] = lambda: current["actor"]

    def como(nombre):
        current["actor"] = esc[nombre]

    with TestClient(app) as c:
        yield {"client": c, "como": como, "data": esc}

    app.dependency_overrides.clear()


# ═══════════════════════════════════════════════════════════════
# 1) Aislamiento cross-institución
# ═══════════════════════════════════════════════════════════════

def test_docente_no_ve_grupos_de_otra_institucion(client_multi):
    """
    D2 (rol='docente', inst2) hace GET /api/grupos → sólo ve su propio
    grupo. El listado no incluye grupos de inst1 aunque estén en la misma DB.
    """
    d = client_multi
    d["como"]("d2")
    r = d["client"].get("/api/grupos")
    assert r.status_code == 200
    ids = {g["id_grupo"] for g in r.json()}
    assert d["data"]["g2"].id_grupo in ids
    assert d["data"]["g1a"].id_grupo not in ids
    assert d["data"]["g1b"].id_grupo not in ids


def test_docente_no_puede_leer_grupo_de_otra_institucion_por_id(client_multi):
    """
    D2 (inst2) intenta leer G1A (inst1) por id → 404 (contrato: no revelar).
    """
    d = client_multi
    d["como"]("d2")
    r = d["client"].get(f'/api/grupos/{d["data"]["g1a"].id_grupo}')
    assert r.status_code == 404


def test_coordinador_ve_grupos_de_su_institucion(client_multi):
    """
    C1 (coordinador inst1) hace GET /api/institucion/grupos → ve G1A y G1B,
    NO ve el grupo de inst2. Este es el endpoint agregado nuevo.
    """
    d = client_multi
    d["como"]("c1")
    r = d["client"].get("/api/institucion/grupos")
    assert r.status_code == 200
    ids = {g["id_grupo"] for g in r.json()}
    assert d["data"]["g1a"].id_grupo in ids
    assert d["data"]["g1b"].id_grupo in ids
    assert d["data"]["g2"].id_grupo not in ids


def test_coordinador_no_puede_editar_grupo_ajeno_dentro_de_su_institucion(client_multi):
    """
    C1 puede VER G1A (mismo colegio), pero PUT devuelve 404 porque la
    edición sigue reservada al dueño (Docente 1A). Regla del sprint.
    """
    d = client_multi
    d["como"]("c1")
    # Confirmar que sí lo ve
    r_get = d["client"].get(f'/api/grupos/{d["data"]["g1a"].id_grupo}')
    assert r_get.status_code == 200
    # Pero no lo edita
    r_put = d["client"].put(
        f'/api/grupos/{d["data"]["g1a"].id_grupo}',
        json={"nombre_grupo": "renombrado"},
    )
    assert r_put.status_code == 404


def test_rol_docente_recibe_403_en_endpoints_admin(client_multi):
    """
    D1A (rol='docente') → 403 en dashboard, invitar, cambiar rol, etc.
    """
    d = client_multi
    d["como"]("d1a")
    endpoints_admin = [
        ("GET", "/api/institucion/dashboard"),
        ("GET", "/api/institucion/docentes"),
        ("GET", "/api/institucion/grupos"),
        ("GET", "/api/institucion/piar"),
    ]
    for method, url in endpoints_admin:
        r = d["client"].request(method, url)
        assert r.status_code == 403, (
            f"esperaba 403 en {method} {url}, obtuve {r.status_code}"
        )


# ═══════════════════════════════════════════════════════════════
# 2) Endpoints /api/institucion — invitar
# ═══════════════════════════════════════════════════════════════

def test_invitar_requiere_plan_institucional(client_multi, db_session):
    """
    Bajamos el plan de inst1 a 'free'. Rector intenta invitar → 403.
    """
    d = client_multi
    d["data"]["inst1"].plan = "free"
    db_session.commit()

    d["como"]("r1")
    r = d["client"].post(
        "/api/institucion/invitar",
        json={"email": "d2@bosque.edu"},
    )
    assert r.status_code == 403
    assert "plan" in r.json()["detail"].lower() or "institucional" in r.json()["detail"].lower()


def test_invitar_docente_solo_en_uni_personal_lo_mueve_y_borra_orfana(
    client_multi, db_session,
):
    """
    D2 está solo en inst2 (uni-personal, 1 docente).
    R1 lo invita → D2 pasa a inst1 con rol='docente' y inst2 se borra.
    """
    from models import Institucion, Docente
    d = client_multi
    inst2_id = d["data"]["inst2"].id_institucion
    inst1_id = d["data"]["inst1"].id_institucion

    d["como"]("r1")
    r = d["client"].post(
        "/api/institucion/invitar",
        json={"email": "d2@bosque.edu"},
    )
    assert r.status_code in (200, 201), r.text

    db_session.expire_all()
    d2_reload = db_session.query(Docente).filter(
        Docente.email == "d2@bosque.edu",
    ).first()
    assert d2_reload.id_institucion == inst1_id
    assert d2_reload.rol == "docente"

    inst2_reload = db_session.query(Institucion).filter(
        Institucion.id_institucion == inst2_id,
    ).first()
    assert inst2_reload is None, "la institución uni-personal huérfana debía borrarse"


def test_invitar_falla_si_docente_esta_en_institucion_compartida(
    client_multi, db_session,
):
    """
    Agregamos un segundo docente a inst2 (ahora ya no es uni-personal).
    Invitar a D2 → 409 con mensaje pedagógico.
    """
    from models import Institucion
    inst2 = client_multi["data"]["inst2"]
    _mk_docente(db_session, "colega@bosque.edu", "Colega Bosque",
                id_institucion=inst2.id_institucion)

    d = client_multi
    d["como"]("r1")
    r = d["client"].post(
        "/api/institucion/invitar",
        json={"email": "d2@bosque.edu"},
    )
    assert r.status_code == 409
    # Y confirmamos que inst2 sigue existiendo (no se borra por accidente)
    db_session.expire_all()
    inst2_reload = db_session.query(Institucion).filter(
        Institucion.id_institucion == inst2.id_institucion,
    ).first()
    assert inst2_reload is not None


# ═══════════════════════════════════════════════════════════════
# 2) Endpoints /api/institucion — cambiar rol
# ═══════════════════════════════════════════════════════════════

def test_rector_cambia_rol_de_otro_docente(client_multi, db_session):
    """R1 promueve a D1A → coordinador."""
    from models import Docente
    d = client_multi
    d1a_id = d["data"]["d1a"].id_docente

    d["como"]("r1")
    r = d["client"].put(
        f"/api/institucion/docentes/{d1a_id}/rol",
        json={"rol": "coordinador"},
    )
    assert r.status_code == 200, r.text

    db_session.expire_all()
    d1a_reload = db_session.query(Docente).filter(
        Docente.id_docente == d1a_id,
    ).first()
    assert d1a_reload.rol == "coordinador"


def test_rector_no_puede_cambiar_su_propio_rol(client_multi):
    """R1 intenta modificarse a sí mismo → 409."""
    d = client_multi
    r1_id = d["data"]["r1"].id_docente
    d["como"]("r1")
    r = d["client"].put(
        f"/api/institucion/docentes/{r1_id}/rol",
        json={"rol": "docente"},
    )
    assert r.status_code == 409


def test_promover_a_admin_requiere_plan_institucional(client_multi, db_session):
    """
    inst1 baja a 'free'. R1 intenta promover a D1A → 403.
    (Nota: cambiar el rol de admin a docente NO requiere plan — solo promover.)
    """
    d = client_multi
    d["data"]["inst1"].plan = "free"
    db_session.commit()

    d["como"]("r1")
    r = d["client"].put(
        f'/api/institucion/docentes/{d["data"]["d1a"].id_docente}/rol',
        json={"rol": "coordinador"},
    )
    assert r.status_code == 403


# ═══════════════════════════════════════════════════════════════
# 2) Endpoints /api/institucion — remover
# ═══════════════════════════════════════════════════════════════

def test_remover_docente_crea_institucion_uni_personal(client_multi, db_session):
    """
    R1 remueve a D1A. Verificamos que:
    - D1A queda con rol='docente' y una nueva institución.
    - La nueva institución tiene plan='free'.
    - Los grupos de D1A siguen siendo suyos (no se transfieren).
    """
    from models import Docente, Institucion
    d = client_multi
    d1a_id = d["data"]["d1a"].id_docente
    inst1_id = d["data"]["inst1"].id_institucion
    g1a_id = d["data"]["g1a"].id_grupo

    d["como"]("r1")
    r = d["client"].delete(f"/api/institucion/docentes/{d1a_id}")
    assert r.status_code in (200, 204), r.text

    db_session.expire_all()
    d1a_reload = db_session.query(Docente).filter(
        Docente.id_docente == d1a_id,
    ).first()
    assert d1a_reload.id_institucion != inst1_id
    assert d1a_reload.rol == "docente"

    nueva_inst = db_session.query(Institucion).filter(
        Institucion.id_institucion == d1a_reload.id_institucion,
    ).first()
    assert nueva_inst is not None
    assert nueva_inst.plan == "free"

    # El grupo sigue siendo de D1A
    from models import Grupo
    g = db_session.query(Grupo).filter(Grupo.id_grupo == g1a_id).first()
    assert g.id_docente == d1a_id


# ═══════════════════════════════════════════════════════════════
# 3) Dashboard institucional
# ═══════════════════════════════════════════════════════════════

def test_dashboard_institucional_agrega_docentes_y_grupos(client_multi):
    """
    C1 (coord) llama al dashboard → KPIs consolidados sobre inst1.
    - total_docentes: 4 (r1, c1, d1a, d1b)
    - total_grupos: 2 (g1a, g1b)
    - No incluye g2 ni d2 de inst2.
    """
    d = client_multi
    d["como"]("c1")
    r = d["client"].get("/api/institucion/dashboard")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total_docentes"] == 4
    assert body["total_grupos"] == 2
    assert body["nombre_institucion"] == "Colegio Andes"
    assert body["plan"] == "institucional"
    # No hay estudiantes en el escenario → 0
    assert body["total_estudiantes"] == 0
    assert body["total_piar"] == 0
