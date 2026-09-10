"""
SPRINT 3 — join.html a prueba de balas.

Bug real verificado en producción con 4 navegadores móviles: el botón
"Unirme" era INVISIBLE en Firefox Focus, Safari iOS y Chrome Android
porque `style="background: var(--brand-primary)"` + `class="text-white"`
resolvía a fondo transparente (texto blanco sobre tarjeta blanca) cuando
css/brand.css no cargaba — 20 usos de var(--brand-*) sin fallback en esa
página.

Estos tests son análisis estático de texto (no requieren un navegador ni
un runner JS — corren en CI vía pytest normal): confirman que NINGÚN
var(--...) en atributos `style=""` de join.html/presentacion-docente.html
quedó sin valor de respaldo, y que el fallback del botón principal de
join.html produce contraste suficiente incluso si brand.css nunca carga.
"""
from __future__ import annotations

import re
from pathlib import Path

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

# var(--algo) SIN coma antes del paréntesis de cierre = sin fallback.
_VAR_SIN_FALLBACK = re.compile(r"var\(--[a-zA-Z0-9-]+\)")
_STYLE_ATTR = re.compile(r'style="([^"]*)"')


def _leer(nombre: str) -> str:
    ruta = FRONTEND_DIR / nombre
    assert ruta.exists(), f"{nombre} no existe en {FRONTEND_DIR}"
    return ruta.read_text(encoding="utf-8")


def _var_sin_fallback_en_atributos_style(html: str) -> list[str]:
    """Devuelve cada var(--...) sin fallback encontrado dentro de
    atributos style="..." — el alcance exacto pedido en la verificación
    obligatoria del sprint."""
    ofensores = []
    for match in _STYLE_ATTR.finditer(html):
        valor = match.group(1)
        ofensores.extend(_VAR_SIN_FALLBACK.findall(valor))
    return ofensores


def _var_sin_fallback_en_todo_el_archivo(html: str) -> list[str]:
    """Barrido más amplio (incluye el bloque <style> y cualquier otro
    lugar) — no es lo mínimo pedido, pero confirma la regla completa de
    CLAUDE.md ("cualquier var() en atributo style inline O asignado
    desde JS")."""
    return _VAR_SIN_FALLBACK.findall(html)


def test_join_html_sin_var_sin_fallback_en_atributos_style():
    html = _leer("join.html")
    ofensores = _var_sin_fallback_en_atributos_style(html)
    assert ofensores == [], f"var() sin fallback en atributos style de join.html: {ofensores}"


def test_presentacion_docente_sin_var_sin_fallback_en_atributos_style():
    html = _leer("presentacion-docente.html")
    ofensores = _var_sin_fallback_en_atributos_style(html)
    assert ofensores == [], (
        f"var() sin fallback en atributos style de presentacion-docente.html: {ofensores}"
    )


def test_join_html_sin_var_sin_fallback_en_todo_el_archivo():
    """Barrido completo — join.html es autosuficiente (SPRINT 3 Parte B)
    y define sus propias variables en :root, pero igual debe llevar
    fallback en cada var() por la regla de defensa en profundidad."""
    html = _leer("join.html")
    ofensores = _var_sin_fallback_en_todo_el_archivo(html)
    assert ofensores == [], f"var() sin fallback en join.html: {ofensores}"


def test_presentacion_docente_sin_var_sin_fallback_en_todo_el_archivo():
    html = _leer("presentacion-docente.html")
    ofensores = _var_sin_fallback_en_todo_el_archivo(html)
    assert ofensores == [], f"var() sin fallback en presentacion-docente.html: {ofensores}"


# ═══════════════════════════════════════════════════════════════
# Contraste del botón "Unirme" si css/brand.css NUNCA carga — el
# fallback de var() es EXACTAMENTE lo que el navegador usa en ese
# escenario, así que probar el fallback es probar el escenario real.
# ═══════════════════════════════════════════════════════════════

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
    """Ratio de contraste WCAG entre dos colores — 1:1 (sin contraste)
    hasta 21:1 (negro sobre blanco)."""
    l1 = _luminancia_relativa(_hex_a_rgb(hex1))
    l2 = _luminancia_relativa(_hex_a_rgb(hex2))
    claro, oscuro = max(l1, l2), min(l1, l2)
    return (claro + 0.05) / (oscuro + 0.05)


def test_fallback_de_brand_primary_no_es_transparente_ni_vacio():
    html = _leer("join.html")
    match = re.search(r"--brand-primary:\s*([^;]+);", html)
    assert match, "join.html debe definir --brand-primary en su :root local"
    valor = match.group(1).strip()
    assert valor not in ("", "transparent", "none", "inherit")
    assert valor.startswith("#"), f"se esperaba un color hex, se obtuvo: {valor!r}"


def test_boton_unirme_tiene_contraste_suficiente_si_brand_css_no_carga():
    """
    Simula el escenario exacto del bug: si css/brand.css no carga, TODO
    var(--brand-primary, X) resuelve a su fallback X. Confirma que ese
    fallback, combinado con el color de texto del botón, da contraste
    WCAG AA para texto grande (>= 3:1 — el texto del botón es bold
    1.125rem/18px, que califica como "large text" bajo WCAG 2.x, no el
    umbral de 4.5:1 de texto normal) — no sólo "no transparente".
    """
    html = _leer("join.html")

    regla = re.search(r"\.btn-primario\s*\{([^}]*)\}", html)
    assert regla, "no se encontró la regla .btn-primario en el <style> de join.html"
    cuerpo = regla.group(1)

    fallback_bg = re.search(r"background:\s*var\(--brand-primary,\s*(#[0-9A-Fa-f]{6})\)", cuerpo)
    assert fallback_bg, ".btn-primario debe fijar background a var(--brand-primary, #HEX)"
    color_texto = re.search(r"(?<!background-)color:\s*(#[0-9A-Fa-f]{6})", cuerpo)
    assert color_texto, ".btn-primario debe fijar un color de texto en hex"

    ratio = _contraste(fallback_bg.group(1), color_texto.group(1))
    assert ratio >= 3.0, (
        f"contraste insuficiente entre texto {color_texto.group(1)} y fondo de "
        f"respaldo {fallback_bg.group(1)}: {ratio:.2f}:1 (mínimo WCAG AA texto grande: 3:1)"
    )


def test_boton_unirme_no_depende_de_class_text_white_sin_fondo_propio():
    """
    Causa concreta del bug original: `style="background: var(--brand-primary)"`
    (sin fallback) + `class="text-white"` (una clase de Tailwind, ausente
    si Tailwind no carga) — ninguna de las dos partes garantizaba un
    fondo real. Confirma que el botón ahora tiene su color de fondo
    definido en una regla CSS propia (.btn-primario), no sólo en una
    clase de utilidad de un framework externo.
    """
    html = _leer("join.html")
    assert "cdn.tailwindcss.com" not in html, "join.html no debe depender de Tailwind CDN (SPRINT 3 Parte B)"
    assert "font-awesome" not in html.lower(), "join.html no debe depender de Font Awesome CDN (SPRINT 3 Parte B)"
    assert 'href="css/brand.css' not in html, "join.html no debe depender de brand.css externo (SPRINT 3 Parte B)"
    assert 'href="css/main.css' not in html, "join.html no debe depender de main.css externo (SPRINT 3 Parte B)"
    assert re.search(r"\.btn-primario\s*\{[^}]*background:", html), (
        ".btn-primario debe definir su propio background en el <style> inline"
    )


def test_join_html_pesa_menos_de_50kb():
    ruta = FRONTEND_DIR / "join.html"
    tamano = ruta.stat().st_size
    assert tamano < 50 * 1024, f"join.html pesa {tamano} bytes — debe quedar por debajo de 50KB"


def test_join_html_desregistra_service_worker_viejo():
    html = _leer("join.html")
    assert "serviceWorker" in html and "unregister" in html, (
        "join.html debe desregistrar cualquier service worker existente al cargar (SPRINT 3 Parte C)"
    )


def test_presentacion_docente_desregistra_service_worker_viejo():
    html = _leer("presentacion-docente.html")
    assert "serviceWorker" in html and "unregister" in html, (
        "presentacion-docente.html debe desregistrar cualquier service worker existente al cargar (SPRINT 3 Parte C)"
    )


def test_service_worker_borra_todas_las_cachés_viejas_al_activar():
    ruta = FRONTEND_DIR / "service-worker.js"
    contenido = ruta.read_text(encoding="utf-8")
    assert "caches.keys()" in contenido and "caches.delete(" in contenido, (
        "el activate() del service worker debe borrar todas las cachés existentes (SPRINT 3 Parte C)"
    )
