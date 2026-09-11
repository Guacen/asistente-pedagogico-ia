"""
SPRINT 8, Parte B — DEFENSA ESTRUCTURAL: esquema Pydantic de una
diapositiva ya rellenada, validado ANTES de guardarla. Dos veces ya un
desajuste de contrato se coló en silencio (el "cuerpo" como array crudo
en SPRINT 1, y ahora el contrato de pregunta) — este esquema es la
fuente de verdad única, para que un desajuste falle con mensaje claro
en la generación, no en silencio frente a un salón lleno.

VERIFICACIÓN OBLIGATORIA #2: el esquema rechaza una diapositiva sin
las claves correctas de pregunta.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


# ═══════════════════════════════════════════════════════════════
# El esquema en sí — casos válidos e inválidos
# ═══════════════════════════════════════════════════════════════

def test_esquema_multiple_acepta_una_diapositiva_bien_formada():
    from presentaciones import DiapositivaMultipleSchema
    DiapositivaMultipleSchema.model_validate({
        "tipo": "multiple", "pregunta": "¿Cuál es la capital de Colombia?",
        "opciones": ["Bogotá", "Medellín", "Cali", "Cartagena"],
        "correcta": 0, "tiempo_s": 20, "puntos": 100,
    })  # no debe lanzar


def test_esquema_verdadero_falso_acepta_una_diapositiva_bien_formada():
    from presentaciones import DiapositivaVerdaderoFalsoSchema
    DiapositivaVerdaderoFalsoSchema.model_validate({
        "tipo": "verdadero_falso", "pregunta": "¿La Tierra es plana?",
        "opciones": ["Verdadero", "Falso"], "correcta": 1, "tiempo_s": 15, "puntos": 100,
    })  # no debe lanzar


@pytest.mark.parametrize("bruto", [
    {},  # totalmente vacía
    {"tipo": "multiple"},  # sin pregunta, sin opciones
    {"tipo": "multiple", "pregunta": "¿Cuál?"},  # sin opciones
    {"tipo": "multiple", "opciones": ["A", "B"], "correcta": 0, "tiempo_s": 20, "puntos": 100},  # sin "pregunta"
    {"tipo": "multiple", "pregunta": "¿Cuál?", "opciones": ["A"], "correcta": 0, "tiempo_s": 20, "puntos": 100},  # 1 sola opción
    {"tipo": "multiple", "pregunta": "¿Cuál?", "opciones": ["A", "B"], "correcta": 5, "tiempo_s": 20, "puntos": 100},  # correcta fuera de rango
    {"tipo": "multiple", "pregunta": "¿Cuál?", "opciones": ["A", "B"], "correcta": 0, "tiempo_s": 0, "puntos": 100},  # tiempo_s inválido
])
def test_esquema_multiple_rechaza_diapositivas_sin_las_claves_correctas(bruto):
    from presentaciones import DiapositivaMultipleSchema
    with pytest.raises(ValidationError):
        DiapositivaMultipleSchema.model_validate(bruto)


@pytest.mark.parametrize("bruto", [
    {},
    {"tipo": "verdadero_falso"},  # sin pregunta
    {"tipo": "verdadero_falso", "pregunta": "¿?", "opciones": ["Verdadero", "Falso"], "correcta": 2, "tiempo_s": 15, "puntos": 100},  # correcta fuera de {0,1}
    {"tipo": "verdadero_falso", "pregunta": "¿?", "opciones": ["Verdadero"], "correcta": 0, "tiempo_s": 15, "puntos": 100},  # falta una opción
    {"tipo": "multiple", "pregunta": "¿?", "opciones": ["Verdadero", "Falso"], "correcta": 0, "tiempo_s": 15, "puntos": 100},  # tipo equivocado para este esquema
])
def test_esquema_verdadero_falso_rechaza_diapositivas_sin_las_claves_correctas(bruto):
    from presentaciones import DiapositivaVerdaderoFalsoSchema
    with pytest.raises(ValidationError):
        DiapositivaVerdaderoFalsoSchema.model_validate(bruto)


def test_esquema_contenido_rechaza_cuerpo_vacio():
    from presentaciones import DiapositivaContenidoSchema
    with pytest.raises(ValidationError):
        DiapositivaContenidoSchema.model_validate({
            "tipo": "contenido", "titulo": "T", "cuerpo": [], "notas_docente": "x",
        })


def test_esquema_contenido_acepta_cuerpo_como_string_o_lista():
    from presentaciones import DiapositivaContenidoSchema
    DiapositivaContenidoSchema.model_validate({"tipo": "contenido", "titulo": "T", "cuerpo": "Un párrafo."})
    DiapositivaContenidoSchema.model_validate({"tipo": "contenido", "titulo": "T", "cuerpo": ["Punto 1", "Punto 2"]})


def test_validar_esquema_pregunta_devuelve_none_si_no_matchea_ningun_tipo():
    from presentaciones import _validar_esquema_pregunta
    assert _validar_esquema_pregunta({"tipo": "poll", "pregunta": "x"}) is None


def test_validar_esquema_pregunta_devuelve_el_slide_si_es_valido():
    from presentaciones import _validar_esquema_pregunta
    slide = {
        "tipo": "multiple", "pregunta": "¿Cuál?", "opciones": ["A", "B"],
        "correcta": 0, "tiempo_s": 20, "puntos": 100,
    }
    assert _validar_esquema_pregunta(slide) == slide


def test_validar_esquema_pregunta_devuelve_none_si_falla_la_validacion():
    from presentaciones import _validar_esquema_pregunta
    slide_roto = {
        "tipo": "multiple", "pregunta": "¿Cuál?", "opciones": ["A"],  # sólo 1 opción — inválido
        "correcta": 0, "tiempo_s": 20, "puntos": 100,
    }
    assert _validar_esquema_pregunta(slide_roto) is None


# ═══════════════════════════════════════════════════════════════
# Integración: el esquema efectivamente bloquea una respuesta de la
# IA mal formada ANTES de que llegue a guardarse — dispara el mismo
# reintento único que ya existía, y si vuelve a fallar, la diapositiva
# queda en estado de error (nunca silenciosa).
# ═══════════════════════════════════════════════════════════════

def test_generar_relleno_pregunta_ia_rechaza_json_sin_opciones_multiple(monkeypatch, seed_docente):
    """La IA devuelve "multiple" sin "op" (opciones) — pasa el parseo
    JSON pero no puede pasar el esquema Pydantic (min 2 opciones)."""
    import llm
    import presentaciones as presentaciones_module

    monkeypatch.setattr(
        llm, "respuesta_completa",
        AsyncMock(return_value='{"ti": "multiple", "pr": "¿Cuál es la capital?", "co": 0}'),
    )
    grupo = seed_docente["grupo"]
    slide = asyncio.run(presentaciones_module._generar_relleno_pregunta_ia(
        grupo, "Colombia", "Capital", 1, 4, ["multiple"],
    ))
    assert slide is None


def test_generar_relleno_pregunta_ia_rechaza_correcta_fuera_de_rango(monkeypatch, seed_docente):
    """Pasa el parseo ad-hoc (que ya defiende contra esto con un
    fallback a 0), así que este caso en particular no debería llegar a
    rechazarse — pero confirma que cuando el ad-hoc SÍ deja pasar algo
    raro, el esquema es la red de seguridad final."""
    import llm
    import presentaciones as presentaciones_module

    monkeypatch.setattr(
        llm, "respuesta_completa",
        AsyncMock(return_value='{"ti": "multiple", "pr": "¿Cuál?", "op": ["A", "B"], "co": 99}'),
    )
    grupo = seed_docente["grupo"]
    slide = asyncio.run(presentaciones_module._generar_relleno_pregunta_ia(
        grupo, "Tema", "Título", 1, 4, ["multiple"],
    ))
    # El ad-hoc ya normaliza "co" fuera de rango a 0 antes de llegar al
    # esquema — así que esto SÍ debe pasar, con correcta=0.
    assert slide is not None
    assert slide["correcta"] == 0
