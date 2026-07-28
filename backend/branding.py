"""
Constantes de marca Maestr.ia para los generadores DOCX.

Los mismos hex viven en frontend/css/brand.css como variables CSS.
Si cambia la paleta acá, tocar también allá.

Uso:
    from branding import HEX_PRIMARY, HEX_DARK, FOOTER_TEXT, TAGLINE
    from docx.shared import RGBColor
    color = RGBColor.from_string(HEX_PRIMARY[1:])  # sin el '#'
"""

# Paleta (sin '#' facilita el uso con RGBColor.from_string)
HEX_PRIMARY = "#1D9E75"   # verde principal — títulos, líneas
HEX_DARK    = "#0B3D2E"   # verde oscuro  — títulos principales
HEX_AMBER   = "#F5B731"   # ámbar         — destacados
HEX_BOOK    = "#2ECC71"   # verde libro   — accents secundarios
HEX_LIGHT   = "#FFFFFF"   # fondo

# Copy oficial de marca
TAGLINE = "Tu colega que conoce la ley"
FOOTER_TEXT = "Maestr.ia · Tu colega que conoce la ley · Generado con IA"


def hex_to_rgb(hex_str: str) -> tuple[int, int, int]:
    """
    Convierte '#RRGGBB' o 'RRGGBB' a la tupla que espera docx.shared.RGBColor.
    Usar como:  RGBColor(*hex_to_rgb(HEX_PRIMARY))
    """
    h = hex_str.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
