"""
SPRINT 2 (presentaciones) — reintento de generación cuando el conteo de
diapositivas de contenido/preguntas no coincide con lo pedido.

Deliberadamente en un archivo separado de test_presentaciones.py: ese
archivo tiene un fixture autouse que reemplaza _generar_diapositivas_ia
por completo (para que ningún otro test golpee al LLM real), lo cual
haría que estos tests nunca ejerciten la lógica real de reintento que
están probando. Acá se monkeypatchea sólo la pieza interna
(_un_intento_generacion_ia) y se llama a la función real.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _slide_contenido(titulo="T"):
    return {"tipo": "contenido", "titulo": titulo, "cuerpo": "x", "notas_docente": "x"}


def _slide_pregunta(tipo="multiple"):
    if tipo == "verdadero_falso":
        return {
            "tipo": "verdadero_falso", "pregunta": "¿Es correcto?",
            "opciones": ["Verdadero", "Falso"], "correcta": 0,
        }
    return {"tipo": "multiple", "pregunta": "¿Cuál?", "opciones": ["A", "B"], "correcta": 0}


def test_reintenta_una_vez_si_el_primer_intento_no_coincide(monkeypatch, seed_docente):
    """Primer intento con conteo incorrecto → debe reintentar UNA vez y
    devolver el segundo intento si ese sí coincide."""
    import presentaciones as presentaciones_module

    intento_incorrecto = [_slide_contenido(), _slide_pregunta()]  # pidió 2/2, esto es 1/1
    intento_correcto = [
        _slide_contenido(), _slide_contenido(),
        _slide_pregunta(), _slide_pregunta("verdadero_falso"),
    ]

    mock = AsyncMock(side_effect=[intento_incorrecto, intento_correcto])
    monkeypatch.setattr(presentaciones_module, "_un_intento_generacion_ia", mock)

    grupo = seed_docente["grupo"]
    resultado = asyncio.run(presentaciones_module._generar_diapositivas_ia(
        grupo, "Tema", n_slides_contenido=2, n_preguntas=2,
        tipos_pregunta=["multiple", "verdadero_falso"],
    ))
    assert mock.await_count == 2
    assert resultado == intento_correcto


def test_no_reintenta_si_el_primer_intento_ya_coincide(monkeypatch, seed_docente):
    import presentaciones as presentaciones_module

    correcto = [_slide_contenido(), _slide_contenido(), _slide_pregunta(), _slide_pregunta()]
    mock = AsyncMock(return_value=correcto)
    monkeypatch.setattr(presentaciones_module, "_un_intento_generacion_ia", mock)

    grupo = seed_docente["grupo"]
    resultado = asyncio.run(presentaciones_module._generar_diapositivas_ia(
        grupo, "Tema", n_slides_contenido=2, n_preguntas=2, tipos_pregunta=["multiple"],
    ))
    assert mock.await_count == 1
    assert resultado == correcto


def test_falla_tras_dos_intentos_con_conteo_incorrecto(monkeypatch, seed_docente):
    """Si NINGUNO de los 2 intentos coincide con lo pedido, devuelve []
    — el endpoint lo trata como fallo (502) en vez de aceptar una
    presentación incompleta en silencio."""
    import presentaciones as presentaciones_module

    siempre_incorrecto = [_slide_contenido()]  # pidió 2/2, esto no tiene ni una pregunta
    mock = AsyncMock(return_value=siempre_incorrecto)
    monkeypatch.setattr(presentaciones_module, "_un_intento_generacion_ia", mock)

    grupo = seed_docente["grupo"]
    resultado = asyncio.run(presentaciones_module._generar_diapositivas_ia(
        grupo, "Tema", n_slides_contenido=2, n_preguntas=2, tipos_pregunta=["multiple"],
    ))
    assert mock.await_count == 2
    assert resultado == []


def test_json_malformado_en_ambos_intentos_no_revienta_devuelve_vacio(monkeypatch, seed_docente):
    """VERIFICACIÓN OBLIGATORIA #3, a nivel de llamada real a la IA: si
    el LLM devuelve basura no-JSON en ambos intentos, la función no
    levanta excepción — devuelve [] limpiamente para que el endpoint
    responda 502 en vez de tronar con un 500."""
    import presentaciones as presentaciones_module
    import llm

    monkeypatch.setattr(
        llm, "respuesta_completa", AsyncMock(return_value="esto no es JSON ni un array {["),
    )
    grupo = seed_docente["grupo"]
    resultado = asyncio.run(presentaciones_module._generar_diapositivas_ia(
        grupo, "Tema", n_slides_contenido=4, n_preguntas=2, tipos_pregunta=["multiple"],
    ))
    assert resultado == []
