"""
Blindaje de los 2 bugs del panel-docente.html corregidos en el smoke test previo:

Fix 1: KPI "Estudiantes" debe sumar `estudiantes.length` real (no `cantidad_estudiantes`).
Fix 2: `construirFilas()` debe ejecutarse ANTES de `renderKPIs()`.

Estos tests parsean el HTML como texto — no cargan Selenium ni jsdom. La
intención es detectar si un futuro refactor rompe alguna de las invariantes.
"""
from __future__ import annotations

import re
from pathlib import Path

FRONTEND = Path(__file__).resolve().parent.parent.parent
PANEL = (FRONTEND / "panel-docente.html").read_text(encoding="utf-8")


def test_kpi_estudiantes_suma_reales_no_meta():
    """
    El cálculo del KPI 'Estudiantes' debe usar `estudiantes.length` real,
    NO `cantidad_estudiantes` del metadato del grupo.
    """
    # Ubica la función renderKPIs
    m = re.search(r"function renderKPIs\(\)\s*\{(.+?)^}", PANEL, re.S | re.M)
    assert m, "renderKPIs no encontrado en panel-docente.html"
    body = m.group(1)

    # Debe leer estudiantes.length de porGrupoData
    assert "estudiantes?.length" in body or "estudiantes.length" in body, (
        "renderKPIs no está sumando estudiantes reales — regresión del Fix 1"
    )
    # NO debe caer de nuevo en cantidad_estudiantes para el KPI.
    # Descartamos comentarios (// ... y /* ... */) antes de buscar.
    code_only = re.sub(r"//.*", "", body)
    code_only = re.sub(r"/\*.*?\*/", "", code_only, flags=re.S)
    assert "cantidad_estudiantes" not in code_only, (
        "renderKPIs volvió a usar cantidad_estudiantes en código ejecutable — "
        "regresión del Fix 1"
    )


def test_construirFilas_corre_antes_de_renderKPIs():
    """
    En la función de carga inicial, construirFilas() debe llamarse ANTES que
    renderKPIs() — de lo contrario el promedio general sale como '—'.
    """
    # Busca el bloque de orquestación (típicamente dentro de cargarPanel)
    m = re.search(r"async function cargarPanel\(\)\s*\{(.+?)^}", PANEL, re.S | re.M)
    assert m, "cargarPanel no encontrado"
    body = m.group(1)

    idx_construir = body.find("construirFilas(")
    idx_kpis = body.find("renderKPIs(")
    assert idx_construir >= 0, "construirFilas() no invocado en cargarPanel"
    assert idx_kpis >= 0, "renderKPIs() no invocado en cargarPanel"
    assert idx_construir < idx_kpis, (
        f"Orden incorrecto: renderKPIs (pos {idx_kpis}) corre antes que "
        f"construirFilas (pos {idx_construir}) — regresión del Fix 2"
    )
