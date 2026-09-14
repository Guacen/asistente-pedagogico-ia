"""
Sprint archivar-presentaciones-flag — Presentaciones Interactivas se
congela para el lanzamiento de la beta gratuita: NO se borra nada
(código, modelos, tablas y migraciones quedan intactos), se oculta
detrás de FEATURE_PRESENTACIONES (default False, env var).

Con el flag apagado (el estado de producción tras este sprint):
- TODA la API bajo /api/presentaciones/* responde 404, indistinguible
  de una ruta que no existe — incluido el endpoint público
  GET /join/{codigo} (join.html sigue sirviéndose por URL directa,
  pero la API que necesitaría para funcionar de verdad también 404).
- GET /api/features (público, sin auth) expone el estado del flag para
  que el frontend decida si muestra entradas a la función.
- El resto de la app (login, grupos, chat, etc.) sigue funcionando
  exactamente igual — el flag es una dependency scoped al router de
  presentaciones, no toca nada más.

NUNCA se llama a Claude/Gemini real — igual que el resto de la suite
de presentaciones, aunque acá ni siquiera hace falta: con el flag
apagado la request nunca llega a ejecutar lógica de negocio.
"""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


# ═══════════════════════════════════════════════════════════════
# GET /api/features — expone el estado del flag al frontend
# ═══════════════════════════════════════════════════════════════

def test_features_reporta_presentaciones_apagado_por_default(client_no_auth):
    """Sin ningún override — el default real de producción."""
    from config import settings
    assert settings.FEATURE_PRESENTACIONES is False

    r = client_no_auth.get("/api/features")
    assert r.status_code == 200
    assert r.json() == {"presentaciones": False}


def test_features_reporta_presentaciones_prendido_si_el_flag_esta_activo(client_no_auth, monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "FEATURE_PRESENTACIONES", True)

    r = client_no_auth.get("/api/features")
    assert r.status_code == 200
    assert r.json() == {"presentaciones": True}


def test_features_no_requiere_autenticacion(client_no_auth):
    """join.html lo consulta sin sesión — debe funcionar sin token."""
    r = client_no_auth.get("/api/features")
    assert r.status_code == 200


# ═══════════════════════════════════════════════════════════════
# Flag apagado (default) — TODA /api/presentaciones/* responde 404
# ═══════════════════════════════════════════════════════════════

def test_generar_devuelve_404_con_flag_apagado(client, seed_docente):
    r = client.post("/api/presentaciones/generar", json={
        "grupo_id": seed_docente["grupo"].id_grupo,
        "secciones": [{"tema": "Fracciones", "n_slides_contenido": 4, "n_preguntas": 2}],
    })
    assert r.status_code == 404


def test_listar_presentaciones_devuelve_404_con_flag_apagado(client):
    r = client.get("/api/presentaciones/")
    assert r.status_code == 404


def test_obtener_presentacion_devuelve_404_con_flag_apagado(client):
    r = client.get("/api/presentaciones/cualquier-id")
    assert r.status_code == 404


def test_iniciar_sesion_devuelve_404_con_flag_apagado(client):
    r = client.post("/api/presentaciones/cualquier-id/iniciar")
    assert r.status_code == 404


def test_join_publico_devuelve_404_con_flag_apagado(client_no_auth):
    """El endpoint público que usa join.html — SIN auth, y aun así 404.
    join.html sigue sirviéndose por URL directa (eso lo maneja main.py,
    no este router), pero no puede unirse a nada de verdad."""
    r = client_no_auth.get("/api/presentaciones/join/ABC123")
    assert r.status_code == 404


def test_exportar_resultados_devuelve_404_con_flag_apagado(client):
    r = client.get("/api/presentaciones/sesiones/cualquier-id/exportar")
    assert r.status_code == 404


def test_estado_presentacion_devuelve_404_con_flag_apagado(client):
    r = client.get("/api/presentaciones/cualquier-id/estado")
    assert r.status_code == 404


def test_404_con_flag_apagado_es_indistinguible_de_ruta_inexistente(client):
    """El cuerpo de la respuesta no debe delatar que la función existe
    pero está apagada — mismo detail que el 404 default de FastAPI para
    cualquier ruta que de verdad no existe."""
    r_real = client.get("/api/presentaciones/")
    r_inexistente = client.get("/api/esto-no-existe-en-ningun-lado")
    assert r_real.status_code == r_inexistente.status_code == 404
    assert r_real.json() == r_inexistente.json() == {"detail": "Not Found"}


# ═══════════════════════════════════════════════════════════════
# Flag prendido — la API vuelve a responder normalmente (no quedó
# rota por la dependency nueva)
# ═══════════════════════════════════════════════════════════════

def test_listar_presentaciones_funciona_con_flag_prendido(client, monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "FEATURE_PRESENTACIONES", True)

    r = client.get("/api/presentaciones/")
    assert r.status_code == 200
    assert r.json() == []


# ═══════════════════════════════════════════════════════════════
# Apagar el flag no rompe NINGUNA otra parte de la app — el resto de
# los routers ni se enteran de que este dependency existe.
# ═══════════════════════════════════════════════════════════════

def test_health_funciona_con_flag_apagado(client_no_auth):
    r = client_no_auth.get("/health")
    assert r.status_code == 200


def test_login_funciona_con_flag_apagado(client_no_auth, seed_docente):
    r = client_no_auth.post(
        "/api/auth/login",
        data={"username": seed_docente["docente"].email, "password": seed_docente["password"]},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert r.status_code == 200
    assert "access_token" in r.json()


def test_grupos_funciona_con_flag_apagado(client):
    r = client.get("/api/grupos")
    assert r.status_code == 200


def test_dashboard_html_sigue_sirviendose_con_flag_apagado(client_no_auth):
    """La página estática en sí no depende del flag — sólo su JS decide
    si muestra la tarjeta, y eso no lo puede ver un test de backend."""
    r = client_no_auth.get("/dashboard.html")
    assert r.status_code == 200


def test_join_html_sigue_sirviendose_por_url_directa_con_flag_apagado(client_no_auth):
    """join.html se sirve igual (main.py, no el router con el flag) —
    lo que cambia es que su propio JS, al consultar /api/features,
    muestra el mensaje de función no disponible en vez del formulario."""
    r = client_no_auth.get("/join/ABC123")
    assert r.status_code == 200
    # Sirvió el archivo real (no un error genérico) — confirma que la
    # pantalla de "no disponible" que agrega este sprint está presente.
    assert b"pantalla-no-disponible" in r.content
    assert b"pantalla-entrada" in r.content
