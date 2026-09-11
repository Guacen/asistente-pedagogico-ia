"""
SPRINT 6 (puntaje/podio/contraste), Parte A — verificación automatizada
de que la paleta de diagramas SVG (--diagram-stroke/--diagram-accent/
--diagram-second/--diagram-label) tiene contraste suficiente contra el
fondo oscuro de la presentación (--brand-dark, #0B3D2E).

VERIFICACIÓN OBLIGATORIA #3: calcula la razón de contraste real de cada
color leído directo de brand.css (no un valor hardcodeado en el test —
si alguien cambia la CSS a un color no conforme, este test debe fallar)
y falla si alguno baja de 4.5:1.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

_UMBRAL_MINIMO = 4.5

_TOKENS_DIAGRAMA = [
    "--diagram-stroke",
    "--diagram-accent",
    "--diagram-second",
    "--diagram-label",
]

def _leer_brand_css() -> str:
    return (BACKEND_DIR / "frontend" / "css" / "brand.css").read_text(encoding="utf-8")


def _hex_a_rgb(hexcolor: str) -> tuple[int, int, int]:
    hexcolor = hexcolor.lstrip("#")
    return tuple(int(hexcolor[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _luminancia_relativa(rgb: tuple[int, int, int]) -> float:
    """Fórmula WCAG 2.x de luminancia relativa."""
    canales = []
    for c in rgb:
        c_srgb = c / 255
        c_lin = c_srgb / 12.92 if c_srgb <= 0.03928 else ((c_srgb + 0.055) / 1.055) ** 2.4
        canales.append(c_lin)
    r, g, b = canales
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contraste(hex1: str, hex2: str) -> float:
    l1 = _luminancia_relativa(_hex_a_rgb(hex1))
    l2 = _luminancia_relativa(_hex_a_rgb(hex2))
    claro, oscuro = max(l1, l2), min(l1, l2)
    return (claro + 0.05) / (oscuro + 0.05)


def _valor_de_token(css: str, token: str) -> str:
    match = re.search(re.escape(token) + r":\s*(#[0-9A-Fa-f]{6})\s*;", css)
    assert match, f"No se encontró la definición de {token} en brand.css"
    return match.group(1)


def _brand_dark_hex(css: str) -> str:
    return _valor_de_token(css, "--brand-dark")


def test_cada_color_de_diagrama_tiene_contraste_minimo_4_5_contra_fondo_oscuro():
    css = _leer_brand_css()
    fondo = _brand_dark_hex(css)
    fallos = []
    for token in _TOKENS_DIAGRAMA:
        color = _valor_de_token(css, token)
        ratio = _contraste(color, fondo)
        if ratio < _UMBRAL_MINIMO:
            fallos.append(f"{token} ({color}) vs {fondo} = {ratio:.2f}:1")
    assert not fallos, "Contraste insuficiente (<4.5:1): " + "; ".join(fallos)


def test_brand_primary_confirmado_insuficiente_documenta_el_motivo_del_sprint():
    """No es una regresión — es la constatación del problema original que
    motivó este sprint (--brand-primary sobre --brand-dark = 3.59:1)."""
    css = _leer_brand_css()
    fondo = _brand_dark_hex(css)
    primary = _valor_de_token(css, "--brand-primary")
    ratio = _contraste(primary, fondo)
    assert ratio < _UMBRAL_MINIMO


def test_diagramas_no_usan_brand_primary_como_trazo():
    """PROHIBIDO (regla explícita del sprint): --brand-primary como
    stroke de línea/trazo en ningún renderer — es el color que medía
    3.59:1 contra el fondo oscuro, insuficiente para proyector."""
    html = (BACKEND_DIR / "frontend" / "presentacion-docente.html").read_text(encoding="utf-8")
    inicio = html.index("_SVG_MARKER_FLECHA")
    fin = html.index("const _DIAGRAMA_RENDERERS")
    seg = html[inicio:fin]
    assert "stroke:var(--brand-primary" not in seg


def test_grosor_minimo_de_trazo_en_diagramas():
    """SPRINT 6, Parte A: en proyector las líneas finas desaparecen —
    ningún stroke-width de los diagramas debe bajar de 2.5px."""
    html = (BACKEND_DIR / "frontend" / "presentacion-docente.html").read_text(encoding="utf-8")
    inicio = html.index("_SVG_MARKER_FLECHA")
    fin = html.index("const _DIAGRAMA_RENDERERS")
    seg = html[inicio:fin]
    anchos = [float(m) for m in re.findall(r'stroke-width="([\d.]+)"', seg)]
    assert anchos, "No se encontraron stroke-width en los renderers — ¿se movió el código?"
    assert all(a >= 2.5 for a in anchos), f"Hay stroke-width por debajo de 2.5px: {anchos}"


def test_tamano_minimo_de_etiqueta_en_diagramas():
    """Ninguna etiqueta de texto de un diagrama debe bajar de 16px."""
    html = (BACKEND_DIR / "frontend" / "presentacion-docente.html").read_text(encoding="utf-8")
    inicio = html.index("_SVG_MARKER_FLECHA")
    fin = html.index("const _DIAGRAMA_RENDERERS")
    seg = html[inicio:fin]
    tamanos = [
        float(m) for m in re.findall(r'font-size:?=?"?(\d+(?:\.\d+)?)(?:px)?"?', seg)
    ]
    assert tamanos, "No se encontraron font-size en los renderers — ¿se movió el código?"
    assert all(t >= 16 for t in tamanos), f"Hay font-size por debajo de 16px: {tamanos}"
