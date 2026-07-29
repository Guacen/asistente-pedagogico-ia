"""
Parser mínimo de Markdown por secciones (## heading).

Uso principal: el pipeline de generación de PIAR/documentos. Claude devuelve
Markdown con secciones fijas separadas por `## `, y el generador DOCX
necesita el contenido de cada sección por separado para inyectarlo con
estilos de marca.

NO es un parser Markdown completo. Solo cubre lo que la app usa:
- headings ## (nivel 2) como separadores de sección
- párrafos normales
- listas con `- `
- negrita con `**texto**`
- tablas Markdown `| a | b |`

Bloques de código, imágenes, links, headings de otro nivel: no se
interpretan, se pasan como texto plano al DOCX.

API pública:
    parse_markdown_sections(md: str, esperadas: list[str] | None) -> dict[str, str]
        Devuelve {nombre_sección: contenido_markdown_sin_el_heading}.
        Si `esperadas` se pasa, asegura que TODAS las keys esperadas
        estén presentes (rellenando con "" las que faltan).
"""
from __future__ import annotations

import re
from typing import Optional


_HEADING_RE = re.compile(r"^\s*##\s+(.+?)\s*$", re.MULTILINE)


def parse_markdown_sections(
    md: str,
    esperadas: Optional[list[str]] = None,
) -> dict[str, str]:
    """
    Divide `md` en secciones usando cada `## Título` como separador.

    Retorno: dict {título: contenido}. El contenido preserva el Markdown
    original (listas, negritas, tablas) — se re-parsea después en el
    generador DOCX. Espacios y saltos de línea extremos se limpian.

    Si `esperadas` se pasa, se garantiza que todas esas keys estén
    presentes en el resultado (rellenando con "" si Claude omitió
    alguna). El orden del dict resultante respeta `esperadas`.

    Texto que aparece ANTES del primer `##` se ignora (típicamente
    preámbulos del modelo tipo "Aquí está el documento:").
    """
    if not md:
        return {name: "" for name in (esperadas or [])}

    matches = list(_HEADING_RE.finditer(md))
    if not matches:
        # Sin headings: sin secciones parseables.
        return {name: "" for name in (esperadas or [])}

    out: dict[str, str] = {}
    for i, m in enumerate(matches):
        titulo = m.group(1).strip()
        inicio = m.end()
        fin = matches[i + 1].start() if i + 1 < len(matches) else len(md)
        contenido = md[inicio:fin].strip("\n").rstrip()
        # Si el título se repite (Claude devuelve dos ## iguales por error),
        # concatenamos con salto de línea — no perdemos información.
        if titulo in out:
            out[titulo] = out[titulo] + "\n\n" + contenido
        else:
            out[titulo] = contenido

    if esperadas:
        # Devolver diccionario ORDENADO por `esperadas`, con las missing en ""
        ordenado: dict[str, str] = {}
        for name in esperadas:
            ordenado[name] = out.get(name, "")
        # Si Claude agregó secciones extra (aunque el prompt diga que no),
        # se descartan del retorno — el DOCX solo renderiza las esperadas.
        return ordenado
    return out


# ═══════════════════════════════════════════════════════════════
# HELPERS PARA EL GENERADOR DOCX — parse línea por línea del cuerpo
# ═══════════════════════════════════════════════════════════════

_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_BULLET_RE = re.compile(r"^\s*[-*]\s+(.+)$")
_TABLE_ROW_RE = re.compile(r"^\s*\|(.+)\|\s*$")
_TABLE_SEPARATOR_RE = re.compile(r"^\s*\|?[\s:-]+\|[\s:|\-]*$")


def iter_inline_bold(texto: str):
    """
    Yieldea tuples (segmento, is_bold). Ejemplo:

        "El **BAP** es clave" → [("El ", False), ("BAP", True), (" es clave", False)]

    El generador DOCX usa esto para llamar `run.bold = True` en el
    fragmento correcto sin recompilar Markdown a HTML.
    """
    if not texto:
        return
    pos = 0
    for m in _BOLD_RE.finditer(texto):
        if m.start() > pos:
            yield texto[pos:m.start()], False
        yield m.group(1), True
        pos = m.end()
    if pos < len(texto):
        yield texto[pos:], False


def _es_separador_tabla(linea: str) -> bool:
    """
    Linea del tipo `| --- | --- |` que separa header de body en tablas
    Markdown. Se detecta y se ignora al parsear.
    """
    return bool(_TABLE_SEPARATOR_RE.match(linea))


def _parse_fila_tabla(linea: str) -> Optional[list[str]]:
    m = _TABLE_ROW_RE.match(linea)
    if not m:
        return None
    celdas = [c.strip() for c in m.group(1).split("|")]
    return celdas


def parse_section_blocks(contenido: str):
    """
    Recorre el contenido de una sección y emite bloques tipados para el
    generador DOCX. Cada yield es una tupla (tipo, payload):

        ("heading3", "Subsección")     — si aparece un ### en el cuerpo
        ("bullet", "Item 1")           — item de lista
        ("table", [headers, rows...])  — tabla completa (todas las filas)
        ("paragraph", "texto")         — párrafo normal

    Múltiples líneas de bullets consecutivas quedan como items separados
    (no como un bloque). El generador puede reagruparlos si quiere; para
    Word un ListBullet por línea es lo esperado.
    """
    if not contenido:
        return
    lineas = contenido.splitlines()
    i = 0
    n = len(lineas)
    parrafo_actual: list[str] = []

    def flush_parrafo():
        nonlocal parrafo_actual
        if parrafo_actual:
            texto = " ".join(l.strip() for l in parrafo_actual).strip()
            if texto:
                yield_val = ("paragraph", texto)
                parrafo_actual = []
                return yield_val
            parrafo_actual = []
        return None

    while i < n:
        linea = lineas[i]
        stripped = linea.strip()

        if not stripped:
            # línea vacía → cierra el párrafo actual
            p = flush_parrafo()
            if p:
                yield p
            i += 1
            continue

        # Sub-heading nivel 3 (para PIAR normalmente no ocurre, pero es
        # útil para robustez si el modelo lo agrega).
        if stripped.startswith("### "):
            p = flush_parrafo()
            if p:
                yield p
            yield ("heading3", stripped[4:].strip())
            i += 1
            continue

        # Tabla — la línea empieza con `|` y la siguiente es separador
        if _TABLE_ROW_RE.match(stripped) and i + 1 < n and _es_separador_tabla(lineas[i + 1]):
            p = flush_parrafo()
            if p:
                yield p
            filas: list[list[str]] = []
            header = _parse_fila_tabla(stripped)
            if header:
                filas.append(header)
            i += 2  # saltar header + separador
            while i < n and _TABLE_ROW_RE.match(lineas[i].strip()):
                fila = _parse_fila_tabla(lineas[i].strip())
                if fila:
                    filas.append(fila)
                i += 1
            if filas:
                yield ("table", filas)
            continue

        # Bullet
        m_bullet = _BULLET_RE.match(linea)
        if m_bullet:
            p = flush_parrafo()
            if p:
                yield p
            yield ("bullet", m_bullet.group(1).strip())
            i += 1
            continue

        # Párrafo — acumular
        parrafo_actual.append(stripped)
        i += 1

    p = flush_parrafo()
    if p:
        yield p


# ═══════════════════════════════════════════════════════════════
# SELF-TEST (correr como `python markdown_parser.py`)
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # Caso 1: secciones completas
    md = """
Preámbulo que Claude a veces incluye — debería ignorarse.

## Datos del estudiante
Código: EST-01, grado 5°.

## Barreras
- Metodología uniforme
- Evaluación no diversificada

## Ajustes razonables
Ver tabla:

| Área | Ajuste |
| --- | --- |
| Evaluación | Tiempo extra 50% |
| Acceso | Fuente ampliada |

Contexto adicional al pie.
"""
    esperadas = ["Datos del estudiante", "Barreras", "Ajustes razonables",
                 "Seguimiento"]  # última NO está → debe quedar ""
    result = parse_markdown_sections(md, esperadas)
    assert list(result.keys()) == esperadas, f"orden roto: {list(result.keys())}"
    assert result["Datos del estudiante"].startswith("Código: EST-01")
    assert "Metodología uniforme" in result["Barreras"]
    assert "Tiempo extra" in result["Ajustes razonables"]
    assert result["Seguimiento"] == ""
    print("✅ parse_markdown_sections: secciones completas + faltantes")

    # Caso 2: sin headings
    r2 = parse_markdown_sections("solo texto plano sin headings", ["A", "B"])
    assert r2 == {"A": "", "B": ""}
    print("✅ parse_markdown_sections: sin headings → esperadas vacías")

    # Caso 3: heading duplicado
    r3 = parse_markdown_sections(
        "## X\nparte 1\n## X\nparte 2",
        ["X"],
    )
    assert "parte 1" in r3["X"] and "parte 2" in r3["X"]
    print("✅ parse_markdown_sections: heading duplicado se concatena")

    # Caso 4: iter_inline_bold
    fragmentos = list(iter_inline_bold("El **BAP** y el **ajuste razonable** son clave."))
    assert fragmentos == [
        ("El ", False), ("BAP", True), (" y el ", False),
        ("ajuste razonable", True), (" son clave.", False),
    ], f"unexpected: {fragmentos}"
    print("✅ iter_inline_bold")

    # Caso 5: parse_section_blocks — bullets + tabla + párrafo
    contenido = """Contexto inicial del estudiante.

- Punto uno
- Punto dos

| Área | Ajuste |
| --- | --- |
| Eval | Tiempo extra |
| Acceso | Braille |

Cierre del texto."""
    bloques = list(parse_section_blocks(contenido))
    tipos = [t for t, _ in bloques]
    assert tipos == ["paragraph", "bullet", "bullet", "table", "paragraph"], f"got {tipos}"
    tabla_data = bloques[3][1]
    assert tabla_data[0] == ["Área", "Ajuste"]
    assert tabla_data[2] == ["Acceso", "Braille"]
    print("✅ parse_section_blocks: párrafo + bullets + tabla + párrafo")

    print("\n🎉 Todos los self-tests pasan.")
