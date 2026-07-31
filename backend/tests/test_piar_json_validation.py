"""
Validación del JSON del LLM antes de rellenar el template (sprint
piar-fixed-format).

Contrato: si el LLM devuelve un JSON incompleto (le faltan claves de
CLAVES_JSON_PIAR), el sistema levanta ValueError con la lista concreta
de faltantes en vez de generar un PIAR malformado con `{key}` sin
sustituir en el DOCX.

Además: el helper de detección de schema (`_es_esquema_json_14_claves`)
distingue el schema NUEVO de los schemas ANTERIORES para que el router
de `_construir_piar_docx` elija bien qué path usar.
"""
from __future__ import annotations

import pytest


# ═══════════════════════════════════════════════════════════════
# _rellenar_template_markdown — validación de completitud
# ═══════════════════════════════════════════════════════════════

def _datos_estudiante_minimos() -> dict:
    return {
        "nombre": "EST-01", "grado": "5°",
        "docente": "M. L.", "diagnostico": "—",
        "fecha": "29/07/2026",
    }


def _json_completo() -> dict:
    return {
        "contexto_escolar_familiar": "x", "fortalezas_intereses": "x",
        "barreras_bap": "x", "dua_representacion": "x",
        "dua_expresion": "x", "dua_motivacion": "x",
        "evaluacion_flexible": "x", "apoyos_requeridos": "x",
        "metas_periodo": "x", "compromisos_institucion": "x",
        "compromisos_docente": "x", "compromisos_familia": "x",
        "fecha_revision": "x", "observaciones_seguimiento": "x",
    }


def test_json_completo_no_lanza_y_devuelve_markdown_con_10_secciones():
    from piar import _rellenar_template_markdown
    md = _rellenar_template_markdown(_json_completo(), _datos_estudiante_minimos())
    # El markdown resultante debe contener las 10 secciones ##
    for sec in [
        "Información del estudiante", "Contexto escolar y familiar",
        "Fortalezas e intereses",
        "Barreras para el aprendizaje y la participación (BAP)",
        "Ajustes razonables y estrategias DUA", "Evaluación flexible",
        "Apoyos requeridos", "Metas del período",
        "Acuerdos y compromisos", "Seguimiento",
    ]:
        assert f"## {sec}" in md, f"Sección faltante en template rellenado: {sec}"


def test_json_incompleto_lanza_value_error_con_lista_de_faltantes():
    from piar import _rellenar_template_markdown
    incompleto = {
        "contexto_escolar_familiar": "x",
        "fortalezas_intereses": "x",
        # ← faltan las 12 restantes
    }
    with pytest.raises(ValueError) as exc:
        _rellenar_template_markdown(incompleto, _datos_estudiante_minimos())
    msg = str(exc.value)
    # El mensaje incluye la lista de faltantes con nombres concretos
    for faltante in ("barreras_bap", "dua_representacion", "compromisos_familia"):
        assert faltante in msg, f"'{faltante}' debe aparecer en el error: {msg}"


def test_json_no_dict_lanza_value_error():
    from piar import _rellenar_template_markdown
    with pytest.raises(ValueError):
        _rellenar_template_markdown("no soy dict", _datos_estudiante_minimos())  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        _rellenar_template_markdown(None, _datos_estudiante_minimos())  # type: ignore[arg-type]


def test_valores_vacios_se_marcan_como_pendiente():
    """
    Si el LLM devuelve `""` para un campo (opcional cuando no cubrió el
    tema), el DOCX debe mostrar "[PENDIENTE — sin información]" en lugar
    de un espacio vacío que rompe el layout.
    """
    from piar import _rellenar_template_markdown
    json_con_vacios = _json_completo()
    json_con_vacios["apoyos_requeridos"] = ""
    json_con_vacios["compromisos_familia"] = "   "  # solo whitespace
    md = _rellenar_template_markdown(json_con_vacios, _datos_estudiante_minimos())
    assert md.count("[PENDIENTE — sin información]") >= 2


# ═══════════════════════════════════════════════════════════════
# _es_esquema_json_14_claves — detección de schema para el router
# ═══════════════════════════════════════════════════════════════

def test_es_esquema_json_14_claves_true_con_json_nuevo():
    from piar import _es_esquema_json_14_claves
    assert _es_esquema_json_14_claves(_json_completo()) is True


def test_es_esquema_json_14_claves_true_con_una_sola_key_nueva():
    from piar import _es_esquema_json_14_claves
    # Con al menos una key snake_case del nuevo schema y ninguna key
    # del schema de 10 secciones, se considera schema nuevo.
    assert _es_esquema_json_14_claves({"contexto_escolar_familiar": "x"}) is True


def test_es_esquema_json_14_claves_false_con_schema_10_secciones():
    from piar import _es_esquema_json_14_claves
    # Schema post-piar-legal-framework (10 secciones nombradas) — el
    # router debe caer al path retro-compat, no al nuevo.
    schema_10 = {
        "Información del estudiante": "x",
        "Fortalezas e intereses": "x",
    }
    assert _es_esquema_json_14_claves(schema_10) is False


def test_es_esquema_json_14_claves_false_con_super_legacy():
    from piar import _es_esquema_json_14_claves
    super_legacy = {
        "caracterizacion": "x", "barreras": "x",
        "ajustes_razonables": "x",
    }
    assert _es_esquema_json_14_claves(super_legacy) is False


def test_es_esquema_json_14_claves_false_con_dict_vacio_o_no_dict():
    from piar import _es_esquema_json_14_claves
    assert _es_esquema_json_14_claves({}) is False
    assert _es_esquema_json_14_claves(None) is False  # type: ignore[arg-type]
    assert _es_esquema_json_14_claves("no soy dict") is False  # type: ignore[arg-type]


# ═══════════════════════════════════════════════════════════════
# _sanitizar_json_14_claves — normalización silenciosa
# ═══════════════════════════════════════════════════════════════

def test_sanitizar_completa_keys_faltantes_con_string_vacio():
    from piar import _sanitizar_json_14_claves, CLAVES_JSON_PIAR
    out = _sanitizar_json_14_claves({"contexto_escolar_familiar": "x"})
    assert set(out.keys()) == set(CLAVES_JSON_PIAR)
    assert out["contexto_escolar_familiar"] == "x"
    assert out["barreras_bap"] == ""


def test_sanitizar_coerce_no_string_a_vacio():
    """Si el LLM devuelve un array o un número, se descarta a string vacío."""
    from piar import _sanitizar_json_14_claves
    out = _sanitizar_json_14_claves({
        "contexto_escolar_familiar": ["no debería ser lista"],
        "fortalezas_intereses": 42,
        "barreras_bap": None,
    })
    assert out["contexto_escolar_familiar"] == ""
    assert out["fortalezas_intereses"] == ""
    assert out["barreras_bap"] == ""
