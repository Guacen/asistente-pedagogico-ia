"""
Sprint H, Parte B — tablero de cohorte beta (GET /api/admin/cohorte) y
gestión de códigos de invitación (/api/admin/codigos).

Cubre:
- Verificación obligatoria #3: sin es_admin, 403 — incluido por API
  directa (no sólo "la página no muestra el link").
- Verificación obligatoria #4: la REGLA INVIOLABLE — el tablero no
  expone NINGÚN dato de estudiantes (nombres/códigos/contenido), sólo
  conteos y metadatos del docente.
- Verificación obligatoria #5: ACTIVADO excluye correctamente la
  actividad dentro del grupo de ejemplo (es_ejemplo=True) — un docente
  que sólo exploró el grupo de ejemplo nunca debe contar como activado.
"""
from __future__ import annotations

from datetime import datetime

from fastapi.testclient import TestClient

from auth import get_current_docente, hash_password
from database import get_db
from models import Docente, Grupo, Mensaje


def _client_como(app, db_session, docente):
    def _override_get_db():
        try:
            yield db_session
        finally:
            pass
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_docente] = lambda: docente
    return TestClient(app)


def _crear_docente_beta(db_session, email: str, **overrides) -> Docente:
    docente = Docente(
        nombre_completo="Docente Beta", email=email,
        password_hash=hash_password("x"), plan="beta",
        **overrides,
    )
    db_session.add(docente)
    db_session.commit()
    db_session.refresh(docente)
    return docente


def _crear_grupo(db_session, docente, *, es_ejemplo=False, nombre="Grupo"):
    grupo = Grupo(
        id_docente=docente.id_docente, nombre_grupo=nombre, grado="5",
        asignatura="Matematicas", anio_lectivo=2026, cantidad_estudiantes=1,
        es_ejemplo=es_ejemplo,
    )
    db_session.add(grupo)
    db_session.commit()
    db_session.refresh(grupo)
    return grupo


def _crear_planeacion(db_session, grupo, contenido="Planeación generada"):
    mensaje = Mensaje(
        id_grupo=grupo.id_grupo, remitente="sistema", contenido=contenido,
        modo="planeacion",
    )
    db_session.add(mensaje)
    db_session.commit()
    return mensaje


# ─── Verificación obligatoria #3 — sin es_admin, 403, también por API directa ─

def test_cohorte_sin_admin_devuelve_403(test_engine, db_session):
    from main import app

    docente = _crear_docente_beta(db_session, "no-admin-cohorte@test.com")
    client = _client_como(app, db_session, docente)
    r = client.get("/api/admin/cohorte")
    assert r.status_code == 403
    app.dependency_overrides.clear()


def test_codigos_sin_admin_devuelve_403(test_engine, db_session):
    from main import app

    docente = _crear_docente_beta(db_session, "no-admin-codigos@test.com")
    client = _client_como(app, db_session, docente)
    assert client.get("/api/admin/codigos").status_code == 403
    assert client.post("/api/admin/codigos", json={
        "codigo": "X", "fecha_expiracion": "2027-01-01T00:00:00",
    }).status_code == 403
    app.dependency_overrides.clear()


def test_cohorte_con_admin_funciona(test_engine, db_session):
    from main import app

    admin = Docente(
        nombre_completo="Admin", email="admin-cohorte@test.com",
        password_hash=hash_password("x"), es_admin=True,
    )
    db_session.add(admin)
    db_session.commit()
    db_session.refresh(admin)

    client = _client_como(app, db_session, admin)
    r = client.get("/api/admin/cohorte")
    assert r.status_code == 200
    body = r.json()
    assert "resumen" in body and "docentes" in body
    app.dependency_overrides.clear()


# ─── Verificación obligatoria #4 — REGLA INVIOLABLE: nada de estudiantes ─

def test_cohorte_no_expone_ningun_dato_de_estudiantes(test_engine, db_session):
    """
    Siembra un estudiante y una planeación con contenido CLARAMENTE
    identificable (strings únicos que no aparecerían por accidente) y
    confirma que ninguno de los dos aparece en ningún lugar del JSON
    crudo de respuesta — no sólo que el schema no los declara.
    """
    from main import app
    from models import Estudiante

    admin = Docente(
        nombre_completo="Admin", email="admin-regla-inviolable@test.com",
        password_hash=hash_password("x"), es_admin=True,
    )
    docente_beta = _crear_docente_beta(db_session, "con-estudiantes@test.com")
    db_session.add(admin)
    db_session.commit()
    db_session.refresh(admin)

    grupo = _crear_grupo(db_session, docente_beta, nombre="MARCADOR_NOMBRE_DE_GRUPO_UNICO")
    estudiante = Estudiante(
        id_grupo=grupo.id_grupo, codigo_estudiante="MARCADOR_CODIGO_ESTUDIANTE_UNICO",
        ajustes="MARCADOR_AJUSTES_UNICO",
    )
    db_session.add(estudiante)
    _crear_planeacion(db_session, grupo, contenido="MARCADOR_CONTENIDO_PLANEACION_UNICO")

    client = _client_como(app, db_session, admin)
    r = client.get("/api/admin/cohorte")
    assert r.status_code == 200

    crudo = r.text
    for marcador in (
        "MARCADOR_NOMBRE_DE_GRUPO_UNICO",
        "MARCADOR_CODIGO_ESTUDIANTE_UNICO",
        "MARCADOR_AJUSTES_UNICO",
        "MARCADOR_CONTENIDO_PLANEACION_UNICO",
    ):
        assert marcador not in crudo, (
            f"'{marcador}' se filtró al tablero de cohorte — viola la regla "
            f"inviolable de no exponer datos de estudiantes."
        )
    app.dependency_overrides.clear()


# ─── Verificación obligatoria #5 — ACTIVADO excluye el grupo de ejemplo ─

def test_activado_excluye_actividad_en_grupo_de_ejemplo(test_engine, db_session):
    from main import app

    admin = Docente(
        nombre_completo="Admin", email="admin-activado@test.com",
        password_hash=hash_password("x"), es_admin=True,
    )
    docente_beta = _crear_docente_beta(db_session, "solo-ejemplo@test.com")
    db_session.add(admin)
    db_session.commit()
    db_session.refresh(admin)

    # Sólo grupo de ejemplo + planeación DENTRO del grupo de ejemplo.
    grupo_ejemplo = _crear_grupo(db_session, docente_beta, es_ejemplo=True, nombre="Ejemplo")
    _crear_planeacion(db_session, grupo_ejemplo)

    client = _client_como(app, db_session, admin)
    r = client.get("/api/admin/cohorte")
    fila = next(d for d in r.json()["docentes"] if d["email"] == "solo-ejemplo@test.com")
    assert fila["activado"] is False, (
        "una planeación dentro del grupo de ejemplo no debe contar como activación"
    )
    assert r.json()["resumen"]["activados"] == 0

    # Ahora agrega un grupo REAL con una planeación REAL — recién ahí
    # debe quedar activado.
    grupo_real = _crear_grupo(db_session, docente_beta, es_ejemplo=False, nombre="Real")
    _crear_planeacion(db_session, grupo_real)

    r2 = client.get("/api/admin/cohorte")
    fila2 = next(d for d in r2.json()["docentes"] if d["email"] == "solo-ejemplo@test.com")
    assert fila2["activado"] is True
    assert r2.json()["resumen"]["activados"] == 1
    app.dependency_overrides.clear()


def test_activado_falso_con_grupo_real_pero_sin_planeacion(test_engine, db_session):
    """Grupo real sin ninguna planeación todavía → no activado."""
    from main import app

    admin = Docente(
        nombre_completo="Admin", email="admin-sin-planeacion@test.com",
        password_hash=hash_password("x"), es_admin=True,
    )
    docente_beta = _crear_docente_beta(db_session, "grupo-sin-planeacion@test.com")
    db_session.add(admin)
    db_session.commit()
    db_session.refresh(admin)

    _crear_grupo(db_session, docente_beta, es_ejemplo=False)

    client = _client_como(app, db_session, admin)
    r = client.get("/api/admin/cohorte")
    fila = next(d for d in r.json()["docentes"] if d["email"] == "grupo-sin-planeacion@test.com")
    assert fila["activado"] is False
    app.dependency_overrides.clear()


# ─── Gestión de códigos: crear, listar, desactivar/reactivar ──────────

def test_admin_crea_lista_y_desactiva_codigo(test_engine, db_session):
    from main import app

    admin = Docente(
        nombre_completo="Admin", email="admin-codigos-crud@test.com",
        password_hash=hash_password("x"), es_admin=True,
    )
    db_session.add(admin)
    db_session.commit()
    db_session.refresh(admin)

    client = _client_como(app, db_session, admin)

    r = client.post("/api/admin/codigos", json={
        "codigo": "nuevo-codigo-crud",
        "descripcion": "Para probar CRUD",
        "fecha_expiracion": "2027-01-01T00:00:00",
        "usos_maximos": 3,
    })
    assert r.status_code == 201, r.text
    assert r.json()["codigo"] == "NUEVO-CODIGO-CRUD"  # normalizado a mayúsculas

    r = client.get("/api/admin/codigos")
    assert any(c["codigo"] == "NUEVO-CODIGO-CRUD" for c in r.json())

    r = client.patch("/api/admin/codigos/nuevo-codigo-crud", json={"activo": False})
    assert r.status_code == 200
    assert r.json()["activo"] is False
    app.dependency_overrides.clear()
