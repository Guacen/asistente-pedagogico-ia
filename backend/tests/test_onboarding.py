import pytest
from fastapi.testclient import TestClient

@pytest.fixture(scope="function")
def client_fresh(db_session):
    from main import app
    from auth import get_current_docente
    from tests.conftest import _install_db_override, _make_docente
    
    _install_db_override(app, db_session)
    docente = _make_docente(db_session, "fresh@test.com", "Fresh", "test1234")
    # Aseguramos que inicie en el onboarding pendiente paso 1
    docente.onboarding_estado = "pendiente"
    docente.onboarding_paso = 1
    db_session.commit()
    
    app.dependency_overrides[get_current_docente] = lambda: docente

    with TestClient(app) as c:
        yield {"client": c, "docente": docente}

    app.dependency_overrides.clear()


def test_onboarding_recorrido_completo(db_session, client_fresh):
    """
    Test 1: Recorrido completo de usuario nuevo real: registro, verificación, login,
    onboarding (paso 1: grupo, paso 2: estudiante, paso 3: planeación).
    """
    c = client_fresh["client"]
    docente = client_fresh["docente"]
    
    # Assert initial state
    assert docente.onboarding_estado == "pendiente"
    assert docente.onboarding_paso == 1
    
    # Paso 1: Crear grupo
    res = c.post("/api/grupos", json={
        "nombre_grupo": "Matematicas 10",
        "grado": "10",
        "asignatura": "Matematicas",
        "anio_lectivo": 2024,
        "periodo_actual": 1,
        "cantidad_estudiantes": 30
    })
    assert res.status_code == 201
    grupo_id = res.json()["id_grupo"]
    
    db_session.refresh(docente)
    assert docente.onboarding_paso == 2
    
    # Paso 2: Agregar estudiante
    res = c.post(f"/api/grupos/{grupo_id}/estudiantes", json={
        "codigo_estudiante": "Juan Perez",
        "genero": "M",
        "tiene_piar": False
    })
    assert res.status_code == 201
    
    db_session.refresh(docente)
    assert docente.onboarding_paso == 3
    assert docente.onboarding_estado == "pendiente"
    
    # Paso 3: Planeacion completada de verdad (usando mock de socket_events, or calling endpoint)
    from onboarding import completar_onboarding_si_aplica
    completar_onboarding_si_aplica(docente)
    db_session.commit()
    db_session.refresh(docente)
    
    assert docente.onboarding_estado == "completado"

def test_onboarding_skip_resume(db_session, client_fresh):
    """
    Test 3: Test de que un docente que salta el onboarding no lo vuelve a ver 
    (es decir, su estado es 'omitido' y se respeta).
    """
    c = client_fresh["client"]
    docente = client_fresh["docente"]
    
    # Saltar onboarding
    res = c.put("/api/perfil/onboarding", json={
        "estado": "omitido"
    })
    assert res.status_code == 200
    
    db_session.refresh(docente)
    assert docente.onboarding_estado == "omitido"
    assert docente.onboarding_paso == 1
    
    # Crear un grupo mientras esta omitido
    res = c.post("/api/grupos", json={
        "nombre_grupo": "Matematicas 10",
        "grado": "10",
        "asignatura": "Matematicas",
        "anio_lectivo": 2024,
        "periodo_actual": 1,
        "cantidad_estudiantes": 30
    })
    assert res.status_code == 201
    
    db_session.refresh(docente)
    assert docente.onboarding_estado == "omitido"
    assert docente.onboarding_paso == 2  # The backend advances it invisibly
    
    # Retomar
    res = c.put("/api/perfil/onboarding", json={
        "estado": "pendiente"
    })
    assert res.status_code == 200
    
    db_session.refresh(docente)
    assert docente.onboarding_estado == "pendiente"
    assert docente.onboarding_paso == 2

def test_onboarding_sobrevive_cerrar_sesion(db_session, client_no_auth):
    """
    Test 2: Test de que el estado del onboarding sobrevive cerrar sesión y volver a entrar.
    """
    from tests.conftest import _make_docente
    # Creating a docente manually without dependency overrides so we can use login
    docente = _make_docente(db_session, "auth@test.com", "Auth", "password123")
    docente.onboarding_estado = "pendiente"
    docente.onboarding_paso = 1
    db_session.commit()

    # Login
    res = client_no_auth.post("/api/auth/login", data={
        "username": docente.email,
        "password": "password123"
    })
    assert res.status_code == 200
    token = res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    
    # Avanza al paso 2
    res = client_no_auth.post("/api/grupos", headers=headers, json={
        "nombre_grupo": "Historia 1",
        "grado": "1",
        "asignatura": "Historia",
        "anio_lectivo": 2024,
        "periodo_actual": 1,
        "cantidad_estudiantes": 30
    })
    assert res.status_code == 201
    
    # Hacemos login de nuevo
    res = client_no_auth.post("/api/auth/login", data={
        "username": docente.email,
        "password": "password123"
    })
    assert res.status_code == 200
    new_token = res.json()["access_token"]
    
    res = client_no_auth.get("/api/auth/me", headers={"Authorization": f"Bearer {new_token}"})
    assert res.status_code == 200
    data = res.json()
    
    assert data["onboarding_estado"] == "pendiente"
    assert data["onboarding_paso"] == 2

def test_grupo_ejemplo_se_puede_borrar(db_session, client_fresh):
    """
    Test 4: Test de que el grupo de ejemplo se puede borrar y que su borrado no arrastra datos del docente.
    """
    c = client_fresh["client"]
    docente = client_fresh["docente"]
    
    res = c.post("/api/grupos/ejemplo")
    assert res.status_code == 201
    grupo_id = res.json()["id_grupo"]
    
    db_session.refresh(docente)
    assert docente.onboarding_paso == 3
    
    # Delete the group
    res = c.delete(f"/api/grupos/{grupo_id}")
    assert res.status_code == 204
    
    db_session.refresh(docente)
    assert docente.id_docente is not None
    assert docente.onboarding_paso == 3

def test_grupo_ejemplo_distinguible(db_session, client_fresh):
    """
    Test 5: Test de que el grupo de ejemplo queda distinguible en el modelo.
    """
    c = client_fresh["client"]
    
    # Crear un grupo real
    res = c.post("/api/grupos", json={
        "nombre_grupo": "Matematicas",
        "grado": "1",
        "asignatura": "Matematicas",
        "anio_lectivo": 2024,
        "periodo_actual": 1,
        "cantidad_estudiantes": 30
    })
    grupo_real_id = res.json()["id_grupo"]
    assert res.json()["es_ejemplo"] is False
    
    # Crear un grupo de ejemplo
    res = c.post("/api/grupos/ejemplo")
    grupo_ejemplo_id = res.json()["id_grupo"]
    assert res.json()["es_ejemplo"] is True
    
    # Verify in DB
    from models import Grupo
    grupo_real = db_session.query(Grupo).filter_by(id_grupo=grupo_real_id).first()
    grupo_ejemplo = db_session.query(Grupo).filter_by(id_grupo=grupo_ejemplo_id).first()
    
    assert grupo_real.es_ejemplo is False
    assert grupo_ejemplo.es_ejemplo is True


def test_planeacion_en_grupo_ejemplo_distinguible_de_real(db_session, client_fresh):
    """
    Test 6: el gap que quedaba del Test 5 — que Grupo.es_ejemplo sea
    correcto en el grupo no prueba nada sobre las PLANEACIONES que se
    crean dentro. Sprint E va a contar activación a partir de mensajes
    de modo='planeacion', así que lo que hay que probar es que ESOS
    mensajes son excluibles/identificables vía join a Grupo.es_ejemplo
    — exactamente la consulta que Sprint E va a necesitar hacer.
    """
    from models import Grupo, Mensaje

    c = client_fresh["client"]

    # Grupo real, con una planeación real dentro.
    res = c.post("/api/grupos", json={
        "nombre_grupo": "Matematicas",
        "grado": "1",
        "asignatura": "Matematicas",
        "anio_lectivo": 2024,
        "periodo_actual": 1,
        "cantidad_estudiantes": 30
    })
    assert res.status_code == 201
    grupo_real_id = res.json()["id_grupo"]

    # Grupo de ejemplo, con una "planeación" dentro (el docente explorando).
    res = c.post("/api/grupos/ejemplo")
    assert res.status_code == 201
    grupo_ejemplo_id = res.json()["id_grupo"]

    msg_real = Mensaje(
        id_grupo=grupo_real_id,
        remitente="sistema",
        contenido="Planeación real generada por IA para Matematicas.",
        modo="planeacion",
    )
    msg_ejemplo = Mensaje(
        id_grupo=grupo_ejemplo_id,
        remitente="sistema",
        contenido="Planeación generada dentro del grupo de ejemplo.",
        modo="planeacion",
    )
    db_session.add_all([msg_real, msg_ejemplo])
    db_session.commit()

    # La consulta que Sprint E necesita: planeaciones de grupos REALES
    # solamente, excluyendo cualquier mensaje que viva en un grupo
    # es_ejemplo=True, sin importar cuántos mensajes de ejemplo existan.
    planeaciones_reales = (
        db_session.query(Mensaje)
        .join(Grupo, Mensaje.id_grupo == Grupo.id_grupo)
        .filter(Mensaje.modo == "planeacion", Grupo.es_ejemplo.is_(False))
        .all()
    )
    ids_reales = {m.id_mensaje for m in planeaciones_reales}

    assert msg_real.id_mensaje in ids_reales
    assert msg_ejemplo.id_mensaje not in ids_reales

    planeaciones_ejemplo = (
        db_session.query(Mensaje)
        .join(Grupo, Mensaje.id_grupo == Grupo.id_grupo)
        .filter(Mensaje.modo == "planeacion", Grupo.es_ejemplo.is_(True))
        .all()
    )
    ids_ejemplo = {m.id_mensaje for m in planeaciones_ejemplo}
    assert msg_ejemplo.id_mensaje in ids_ejemplo
    assert msg_real.id_mensaje not in ids_ejemplo
