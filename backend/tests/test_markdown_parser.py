"""
Tests del parser Markdown de secciones (backend/markdown_parser.py).

Cubre los casos que el pipeline PIAR realmente ejerce:
- Secciones completas, secciones faltantes.
- Preámbulo antes del primer `##` (el modelo a veces lo agrega).
- Heading duplicado (el modelo se equivoca) — se concatena, no se pierde.
- Bullets `- `, negrita `**...**`, tablas Markdown.
- Listas anidadas: el parser NO las trata como jerárquicas (limitación
  documentada). Se aceptan como bullets planos.
"""
from __future__ import annotations

import pytest


# ═══════════════════════════════════════════════════════════════
# parse_markdown_sections
# ═══════════════════════════════════════════════════════════════

def test_secciones_completas_orden_conservado():
    from markdown_parser import parse_markdown_sections
    md = "## A\ntexto A\n\n## B\ntexto B\n\n## C\ntexto C"
    r = parse_markdown_sections(md, esperadas=["A", "B", "C"])
    assert list(r.keys()) == ["A", "B", "C"]
    assert r["A"] == "texto A"
    assert r["C"] == "texto C"


def test_seccion_faltante_devuelve_string_vacio():
    from markdown_parser import parse_markdown_sections
    md = "## A\nhola\n\n## B\nchau"
    r = parse_markdown_sections(md, esperadas=["A", "B", "Faltante"])
    assert r["Faltante"] == ""
    assert r["A"] == "hola"


def test_preambulo_antes_del_primer_heading_se_ignora():
    from markdown_parser import parse_markdown_sections
    md = "Aquí está el documento solicitado:\n\n## A\ncuerpo"
    r = parse_markdown_sections(md, esperadas=["A"])
    assert r == {"A": "cuerpo"}


def test_heading_duplicado_se_concatena():
    from markdown_parser import parse_markdown_sections
    md = "## X\nparte 1\n\n## X\nparte 2"
    r = parse_markdown_sections(md, esperadas=["X"])
    assert "parte 1" in r["X"] and "parte 2" in r["X"]


def test_sin_headings_esperadas_quedan_vacias():
    from markdown_parser import parse_markdown_sections
    r = parse_markdown_sections("solo texto plano", esperadas=["A", "B"])
    assert r == {"A": "", "B": ""}


def test_secciones_extra_se_descartan_si_hay_esperadas():
    from markdown_parser import parse_markdown_sections
    md = "## A\nx\n\n## Extra\ny\n\n## B\nz"
    r = parse_markdown_sections(md, esperadas=["A", "B"])
    assert list(r.keys()) == ["A", "B"]
    assert "Extra" not in r


def test_input_vacio_o_none_no_crashea():
    from markdown_parser import parse_markdown_sections
    assert parse_markdown_sections("", esperadas=["A"]) == {"A": ""}
    assert parse_markdown_sections(None, esperadas=["A"]) == {"A": ""}   # type: ignore[arg-type]


# ═══════════════════════════════════════════════════════════════
# iter_inline_bold
# ═══════════════════════════════════════════════════════════════

def test_iter_inline_bold_bold_al_medio():
    from markdown_parser import iter_inline_bold
    frags = list(iter_inline_bold("El **BAP** es del contexto"))
    assert frags == [("El ", False), ("BAP", True), (" es del contexto", False)]


def test_iter_inline_bold_multiple():
    from markdown_parser import iter_inline_bold
    frags = list(iter_inline_bold("**A**b**C**"))
    tipos = [t for _, t in frags]
    assert tipos == [True, False, True]


def test_iter_inline_bold_sin_negrita_devuelve_uno_solo():
    from markdown_parser import iter_inline_bold
    assert list(iter_inline_bold("plain text")) == [("plain text", False)]


# ═══════════════════════════════════════════════════════════════
# parse_section_blocks — párrafos, bullets, tablas
# ═══════════════════════════════════════════════════════════════

def test_bloques_parrafo_y_bullet():
    from markdown_parser import parse_section_blocks
    contenido = "Introducción.\n\n- primero\n- segundo\n\nCierre."
    tipos = [t for t, _ in parse_section_blocks(contenido)]
    assert tipos == ["paragraph", "bullet", "bullet", "paragraph"]


def test_bloque_tabla_completa():
    from markdown_parser import parse_section_blocks
    contenido = (
        "| A | B |\n"
        "| --- | --- |\n"
        "| a1 | b1 |\n"
        "| a2 | b2 |\n"
    )
    bloques = list(parse_section_blocks(contenido))
    assert len(bloques) == 1
    tipo, filas = bloques[0]
    assert tipo == "table"
    assert filas[0] == ["A", "B"]
    assert filas[1] == ["a1", "b1"]
    assert filas[2] == ["a2", "b2"]


def test_bloque_heading3_se_reconoce_dentro_de_seccion():
    from markdown_parser import parse_section_blocks
    contenido = "### Sub\ncuerpo"
    bloques = list(parse_section_blocks(contenido))
    assert bloques[0] == ("heading3", "Sub")
    assert bloques[1] == ("paragraph", "cuerpo")


def test_bullets_con_negrita_inline_preservan_markdown():
    """
    El parser de sección no procesa negrita — la deja al generador DOCX.
    El bullet contiene `**texto**` textual; el generador después llama
    iter_inline_bold para dividirlo en runs.
    """
    from markdown_parser import parse_section_blocks
    bloques = list(parse_section_blocks("- Item con **énfasis** al medio"))
    assert bloques[0] == ("bullet", "Item con **énfasis** al medio")


def test_listas_anidadas_se_aplanan():
    """
    LIMITACIÓN documentada: no soportamos jerarquía de listas. Los items
    anidados (con más indentación) se aceptan como bullets adicionales.
    """
    from markdown_parser import parse_section_blocks
    contenido = "- padre\n  - hijo\n- otro padre"
    tipos = [t for t, _ in parse_section_blocks(contenido)]
    # Los 3 items quedan planos
    assert tipos == ["bullet", "bullet", "bullet"]
