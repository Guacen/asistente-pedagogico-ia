"""
Hotfix — etiquetas ?v= desincronizadas entre páginas.

Incidente real: el Sprint H (PR #100) subió ?v= a 20261015 sólo en
admin-beta.html (la página nueva que agregó) — el resto de las páginas
siguió pidiendo ?v=20260803 (o alguna otra fecha vieja, acumulada de
sprints anteriores que tampoco actualizaron todas las páginas a la
vez). Resultado: dos copias cacheadas del mismo css/brand.css,
css/main.css, js/api.js, etc. — una página nueva pedía la versión de
hoy, el resto seguía sirviendo (y cacheando) la de hace semanas.
Reproducido en navegador limpio: login.html se renderizaba sin
estilos de Tailwind porque el navegador tenía cacheada una versión
vieja de brand.css bajo una URL distinta a la que login.html pedía.

Este test existe para que la PRÓXIMA página nueva de un sprint futuro
no repita esto: si cualquier archivo estático (css/js propio, no
vendor ni CDN) aparece con más de un valor de ?v= entre todas las
páginas de frontend/, falla.

Análisis estático de texto — no requiere navegador, corre en CI vía
pytest normal (mismo estilo que test_frontend_css_fallbacks.py).
"""
from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

# href="css/algo.css?v=123" o src="js/algo.js?v=123" — sólo archivos
# PROPIOS (ruta relativa css/ o js/), nunca CDN (URL absoluta) ni
# vendor/ (librerías de terceros vendoreadas, que no siguen el mismo
# ciclo de versión que el código de la app).
_REF_CON_VERSION = re.compile(r'(?:href|src)="((?:css|js)/[^"?]+)\?v=(\d+)"')
# [^"?]+" exige que no haya un ?v=... antes de la comilla de cierre —
# si lo hubiera, esto simplemente no matchea esa referencia (la cubre
# el regex de arriba). Antes acá decía [^"]+", que se comía el
# "?v=20261015" completo como parte de la ruta y producía falsos
# positivos (CADA referencia versionada aparecía también como "sin
# versión", con la query string pegada al nombre de archivo).
_REF_SIN_VERSION = re.compile(r'(?:href|src)="((?:css|js)/[^"?]+)"')

# join.html es la única página sin ningún estático versionado a
# propósito — CLAUDE.md la documenta como autosuficiente (inlinea todo
# su CSS, SVG inline, pensada para un estudiante en un dispositivo/red
# que no controlamos). No es una omisión, es la regla.
_PAGINAS_SIN_VERSION_A_PROPOSITO = {"join.html"}

# Vendoreado localmente (DOMPurify) — no sigue el ciclo de versión de
# la app, se actualiza manualmente cuando se bump-ea la librería.
_RUTAS_EXENTAS = {"js/vendor/dompurify.min.js"}


def _paginas_html() -> list[Path]:
    paginas = sorted(FRONTEND_DIR.glob("*.html"))
    assert paginas, f"No se encontró ninguna página .html en {FRONTEND_DIR}"
    return paginas


def test_cada_estatico_propio_tiene_un_unico_valor_de_v_en_todas_las_paginas():
    # archivo -> {version: [páginas que la usan]}
    versiones_por_archivo: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))

    for pagina in _paginas_html():
        texto = pagina.read_text(encoding="utf-8")
        for archivo, version in _REF_CON_VERSION.findall(texto):
            versiones_por_archivo[archivo][version].append(pagina.name)

    assert versiones_por_archivo, (
        "No se encontró ninguna referencia css/js con ?v= en ninguna página — "
        "¿cambió el formato de versionado? Revisar este test."
    )

    ofensores = []
    for archivo, por_version in versiones_por_archivo.items():
        if len(por_version) > 1:
            detalle = "; ".join(
                f"v={v} en {', '.join(sorted(paginas))}"
                for v, paginas in sorted(por_version.items())
            )
            ofensores.append(f"{archivo}: {detalle}")

    assert ofensores == [], (
        "Estos archivos estáticos tienen MÁS DE UN valor de ?v= entre las "
        "páginas de frontend/ — dos copias cacheadas del mismo archivo, "
        "exactamente el incidente del hotfix de versiones desincronizadas:\n"
        + "\n".join(ofensores)
    )


def test_ninguna_referencia_propia_se_queda_sin_version():
    """
    Complementa el test de arriba: además de que todas las versiones
    coincidan, confirma que nadie referencia un css/js propio SIN
    ningún ?v= — eso también rompe el cache-busting (el navegador no
    tiene forma de saber que cambió).
    """
    ofensores = []
    for pagina in _paginas_html():
        if pagina.name in _PAGINAS_SIN_VERSION_A_PROPOSITO:
            continue
        texto = pagina.read_text(encoding="utf-8")
        con_version = {m.group(1) for m in _REF_CON_VERSION.finditer(texto)}
        for ruta in _REF_SIN_VERSION.findall(texto):
            if ruta in _RUTAS_EXENTAS or ruta in con_version:
                continue
            ofensores.append(f"{pagina.name}: {ruta} sin ?v=")

    assert ofensores == [], (
        "Referencias a estáticos propios sin ?v= (rompe cache-busting):\n"
        + "\n".join(ofensores)
    )
