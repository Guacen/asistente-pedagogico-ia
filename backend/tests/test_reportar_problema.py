"""
Sprint primer-uso, Parte D — "Reportar un problema". Objetivo: cuando
un docente de la beta diga "no me funcionó la planeación", poder
investigar qué pasó exactamente — para eso el correlation_id que manda
el reporte tiene que ser EXACTAMENTE el mismo que genera errores.py.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from auth import get_current_docente, hash_password
from database import get_db
from models import Docente, ReporteProblema


def _client_como(app, db_session, docente):
    def _override_get_db():
        try:
            yield db_session
        finally:
            pass
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_docente] = lambda: docente
    return TestClient(app)


def _crear_docente(db_session, email, es_admin=False):
    docente = Docente(
        nombre_completo="Docente Prueba" if not es_admin else "Admin Prueba",
        email=email, password_hash=hash_password("x"), es_admin=es_admin,
    )
    db_session.add(docente)
    db_session.commit()
    db_session.refresh(docente)
    return docente


# ═══════════════════════════════════════════════════════════════
# Crear reporte
# ═══════════════════════════════════════════════════════════════

def test_crear_reporte_lo_guarda(test_engine, db_session):
    from main import app
    docente = _crear_docente(db_session, "docente1@test.com")
    client = _client_como(app, db_session, docente)

    r = client.post("/api/reportes", json={
        "descripcion": "No pude generar la planeación, se quedó cargando.",
        "pantalla": "/chat.html?grupo=abc123",
        "correlation_id": "A1B2C3D4",
        "navegador": "Chrome",
        "es_movil": False,
    })
    app.dependency_overrides.clear()
    assert r.status_code == 201, r.text

    guardado = db_session.query(ReporteProblema).filter(
        ReporteProblema.id_docente == docente.id_docente,
    ).first()
    assert guardado is not None
    assert guardado.descripcion == "No pude generar la planeación, se quedó cargando."
    assert guardado.pantalla == "/chat.html?grupo=abc123"
    assert guardado.correlation_id == "A1B2C3D4"
    assert guardado.navegador == "Chrome"
    assert guardado.es_movil is False


def test_crear_reporte_sin_correlation_id_es_valido(test_engine, db_session):
    """Un docente puede reportar algo sin que haya habido ningún error
    visible — el campo es opcional."""
    from main import app
    docente = _crear_docente(db_session, "docente2@test.com")
    client = _client_como(app, db_session, docente)

    r = client.post("/api/reportes", json={"descripcion": "El botón de guardar no responde."})
    app.dependency_overrides.clear()
    assert r.status_code == 201, r.text

    guardado = db_session.query(ReporteProblema).filter(
        ReporteProblema.id_docente == docente.id_docente,
    ).first()
    assert guardado.correlation_id is None


def test_crear_reporte_sanitiza_descripcion(test_engine, db_session):
    from main import app
    docente = _crear_docente(db_session, "docente3@test.com")
    client = _client_como(app, db_session, docente)

    r = client.post("/api/reportes", json={
        "descripcion": '<script>alert(1)</script>Se rompió el chat',
    })
    app.dependency_overrides.clear()
    assert r.status_code == 201, r.text

    guardado = db_session.query(ReporteProblema).filter(
        ReporteProblema.id_docente == docente.id_docente,
    ).first()
    assert "<script" not in guardado.descripcion.lower()
    assert "Se rompió el chat" in guardado.descripcion


def test_crear_reporte_con_descripcion_vacia_devuelve_400(test_engine, db_session):
    from main import app
    docente = _crear_docente(db_session, "docente4@test.com")
    client = _client_como(app, db_session, docente)

    r = client.post("/api/reportes", json={"descripcion": "   "})
    app.dependency_overrides.clear()
    assert r.status_code in (400, 422)


# ═══════════════════════════════════════════════════════════════
# Verificación obligatoria #1: correlation_id del reporte == el del error
# ═══════════════════════════════════════════════════════════════

def test_correlation_id_del_reporte_coincide_con_el_del_error(test_engine, db_session):
    """El escenario real: el docente ve un error (con su correlation_id
    real, generado por errores.py), y lo adjunta al reportar. Confirma
    que es EXACTAMENTE el mismo valor — sin transformación, sin
    truncar, sin regenerar uno nuevo del lado del backend."""
    from errores import nuevo_correlation_id
    from main import app

    correlation_id_real = nuevo_correlation_id()  # la MISMA función que usa el handler global

    docente = _crear_docente(db_session, "docente5@test.com")
    client = _client_como(app, db_session, docente)

    r = client.post("/api/reportes", json={
        "descripcion": "No me funcionó la planeación.",
        "correlation_id": correlation_id_real,
    })
    app.dependency_overrides.clear()
    assert r.status_code == 201, r.text

    guardado = db_session.query(ReporteProblema).filter(
        ReporteProblema.id_docente == docente.id_docente,
    ).first()
    assert guardado.correlation_id == correlation_id_real


# ═══════════════════════════════════════════════════════════════
# Verificación obligatoria #2: sólo es_admin puede listar
# ═══════════════════════════════════════════════════════════════

def test_listar_reportes_sin_admin_devuelve_403(test_engine, db_session):
    from main import app
    docente = _crear_docente(db_session, "noadmin@test.com", es_admin=False)
    client = _client_como(app, db_session, docente)

    r = client.get("/api/reportes")
    app.dependency_overrides.clear()
    assert r.status_code == 403


def test_listar_reportes_un_docente_no_ve_ni_los_suyos_propios(test_engine, db_session):
    """No existe NINGÚN endpoint "mis reportes" — un docente normal no
    ve reportes, ni los suyos ni los de nadie más, ni por API directa."""
    from main import app
    docente = _crear_docente(db_session, "propios@test.com", es_admin=False)
    client = _client_como(app, db_session, docente)

    client.post("/api/reportes", json={"descripcion": "Mi propio reporte"})
    r = client.get("/api/reportes")
    app.dependency_overrides.clear()
    assert r.status_code == 403


def test_listar_reportes_con_admin_funciona_y_trae_datos_del_docente(test_engine, db_session):
    from main import app
    docente = _crear_docente(db_session, "reportador@test.com", es_admin=False)
    admin = _crear_docente(db_session, "admin@test.com", es_admin=True)

    client_docente = _client_como(app, db_session, docente)
    client_docente.post("/api/reportes", json={
        "descripcion": "El chat se quedó cargando",
        "correlation_id": "DEADBEEF",
    })
    app.dependency_overrides.clear()

    client_admin = _client_como(app, db_session, admin)
    r = client_admin.get("/api/reportes")
    app.dependency_overrides.clear()

    assert r.status_code == 200, r.text
    reportes = r.json()
    assert len(reportes) == 1
    assert reportes[0]["docente_email"] == "reportador@test.com"
    assert reportes[0]["docente_nombre"] == "Docente Prueba"
    assert reportes[0]["correlation_id"] == "DEADBEEF"
    assert reportes[0]["descripcion"] == "El chat se quedó cargando"


def test_listar_reportes_admin_ve_reportes_de_varios_docentes(test_engine, db_session):
    from main import app
    docente_a = _crear_docente(db_session, "a@test.com", es_admin=False)
    docente_b = _crear_docente(db_session, "b@test.com", es_admin=False)
    admin = _crear_docente(db_session, "admin2@test.com", es_admin=True)

    client_a = _client_como(app, db_session, docente_a)
    client_a.post("/api/reportes", json={"descripcion": "Reporte de A"})
    app.dependency_overrides.clear()

    client_b = _client_como(app, db_session, docente_b)
    client_b.post("/api/reportes", json={"descripcion": "Reporte de B"})
    app.dependency_overrides.clear()

    client_admin = _client_como(app, db_session, admin)
    r = client_admin.get("/api/reportes")
    app.dependency_overrides.clear()

    assert r.status_code == 200
    emails = {rep["docente_email"] for rep in r.json()}
    assert emails == {"a@test.com", "b@test.com"}


# ═══════════════════════════════════════════════════════════════
# Verificación obligatoria #3: fallo de correo no pierde el reporte
# ═══════════════════════════════════════════════════════════════

def test_fallo_en_envio_de_correo_no_impide_guardar_el_reporte(test_engine, db_session, monkeypatch):
    import reportes
    from main import app

    def _enviar_que_rompe(**kwargs):
        raise RuntimeError("SMTP caído")

    monkeypatch.setattr(reportes, "enviar_correo_reporte_problema", _enviar_que_rompe)

    docente = _crear_docente(db_session, "docente6@test.com")
    client = _client_como(app, db_session, docente)

    r = client.post("/api/reportes", json={"descripcion": "Reporte importante"})
    app.dependency_overrides.clear()

    assert r.status_code == 201, r.text
    guardado = db_session.query(ReporteProblema).filter(
        ReporteProblema.id_docente == docente.id_docente,
    ).first()
    assert guardado is not None
    assert guardado.descripcion == "Reporte importante"


def test_envio_de_correo_falla_silenciosamente_sin_admin_email_configurado(test_engine, db_session, monkeypatch):
    """Sin ADMIN_EMAIL configurada, enviar_correo_reporte_problema()
    debe devolver False sin lanzar — y el reporte se guarda igual."""
    from config import settings
    from main import app

    monkeypatch.setattr(settings, "ADMIN_EMAIL", "")

    docente = _crear_docente(db_session, "docente7@test.com")
    client = _client_como(app, db_session, docente)

    r = client.post("/api/reportes", json={"descripcion": "Otro reporte"})
    app.dependency_overrides.clear()

    assert r.status_code == 201, r.text
    assert db_session.query(ReporteProblema).filter(
        ReporteProblema.id_docente == docente.id_docente,
    ).first() is not None


# ═══════════════════════════════════════════════════════════════
# email_service — unidad
# ═══════════════════════════════════════════════════════════════

def test_enviar_correo_reporte_problema_sin_admin_email_devuelve_false(monkeypatch):
    from config import settings
    from datetime import datetime
    import email_service

    monkeypatch.setattr(settings, "ADMIN_EMAIL", "")

    ok = email_service.enviar_correo_reporte_problema(
        descripcion="algo", docente_nombre="Ana", docente_email="ana@test.com",
        pantalla="/chat.html", correlation_id="ABCD1234", navegador="Chrome",
        es_movil=True, creado_en=datetime.utcnow(),
    )
    assert ok is False


def test_enviar_correo_reporte_problema_con_provider_inyectado(monkeypatch):
    from config import settings
    from datetime import datetime
    import email_service

    monkeypatch.setattr(settings, "ADMIN_EMAIL", "admin@usemaestria.co")

    class Doble:
        nombre = "doble"
        def __init__(self):
            self.llamadas = []
        def enviar(self, to_email, to_name, asunto, html, texto):
            self.llamadas.append({"to": to_email, "asunto": asunto, "texto": texto})
            return True

    doble = Doble()
    ok = email_service.enviar_correo_reporte_problema(
        descripcion="El chat no respondió", docente_nombre="Ana", docente_email="ana@test.com",
        pantalla="/chat.html", correlation_id="ABCD1234", navegador="Chrome",
        es_movil=True, creado_en=datetime.utcnow(), provider=doble,
    )
    assert ok is True
    assert len(doble.llamadas) == 1
    assert doble.llamadas[0]["to"] == "admin@usemaestria.co"
    assert "ABCD1234" in doble.llamadas[0]["texto"]
    assert "Ana" in doble.llamadas[0]["texto"]
