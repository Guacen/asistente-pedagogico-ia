"""
SPRINT 5 (presentaciones — generación en dos fases) — reintento de la
FASE 1 (esqueleto) cuando el conteo de posiciones "contenido"/"pregunta"
no coincide con lo pedido. Reemplaza los tests equivalentes del sprint
2 (que probaban el reintento de la generación de una sola llamada,
ahora reemplazada por el esqueleto + relleno por diapositiva).

Deliberadamente en un archivo separado de test_presentaciones.py: ese
archivo tiene un fixture autouse que reemplaza _generar_esqueleto_ia
por completo (para que ningún otro test golpee al LLM real), lo cual
haría que estos tests nunca ejerciten la lógica real de reintento que
están probando. Acá se monkeypatchea sólo la pieza interna
(_un_intento_esqueleto_ia) y se llama a la función real.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _stub(tipo="contenido", titulo="T"):
    return {"tipo": tipo, "titulo": titulo}


def test_reintenta_una_vez_si_el_primer_intento_no_coincide(monkeypatch, seed_docente):
    """Primer intento con conteo incorrecto → debe reintentar UNA vez y
    devolver el segundo intento si ese sí coincide."""
    import presentaciones as presentaciones_module

    intento_incorrecto = [_stub(), _stub("pregunta")]  # pidió 2/2, esto es 1/1
    intento_correcto = [
        _stub(), _stub(), _stub("pregunta"), _stub("pregunta"),
    ]

    mock = AsyncMock(side_effect=[intento_incorrecto, intento_correcto])
    monkeypatch.setattr(presentaciones_module, "_un_intento_esqueleto_ia", mock)

    grupo = seed_docente["grupo"]
    resultado = asyncio.run(presentaciones_module._generar_esqueleto_ia(
        grupo, "Tema", n_slides_contenido=2, n_preguntas=2,
    ))
    assert mock.await_count == 2
    assert resultado == intento_correcto


def test_no_reintenta_si_el_primer_intento_ya_coincide(monkeypatch, seed_docente):
    import presentaciones as presentaciones_module

    correcto = [_stub(), _stub(), _stub("pregunta"), _stub("pregunta")]
    mock = AsyncMock(return_value=correcto)
    monkeypatch.setattr(presentaciones_module, "_un_intento_esqueleto_ia", mock)

    grupo = seed_docente["grupo"]
    resultado = asyncio.run(presentaciones_module._generar_esqueleto_ia(
        grupo, "Tema", n_slides_contenido=2, n_preguntas=2,
    ))
    assert mock.await_count == 1
    assert resultado == correcto


def test_falla_tras_dos_intentos_con_conteo_incorrecto(monkeypatch, seed_docente):
    """Si NINGUNO de los 2 intentos coincide con lo pedido, devuelve []
    — el orquestador lo trata como fallo total (estado='error') en vez
    de aceptar un esqueleto incompleto en silencio."""
    import presentaciones as presentaciones_module

    siempre_incorrecto = [_stub()]  # pidió 2/2, esto no tiene ni una pregunta
    mock = AsyncMock(return_value=siempre_incorrecto)
    monkeypatch.setattr(presentaciones_module, "_un_intento_esqueleto_ia", mock)

    grupo = seed_docente["grupo"]
    resultado = asyncio.run(presentaciones_module._generar_esqueleto_ia(
        grupo, "Tema", n_slides_contenido=2, n_preguntas=2,
    ))
    assert mock.await_count == 2
    assert resultado == []


def test_json_malformado_en_ambos_intentos_no_revienta_devuelve_vacio(monkeypatch, seed_docente):
    """Si el LLM devuelve basura no-JSON en ambos intentos, la función
    no levanta excepción — devuelve [] limpiamente."""
    import presentaciones as presentaciones_module
    import llm

    monkeypatch.setattr(
        llm, "respuesta_completa", AsyncMock(return_value="esto no es JSON ni un array {["),
    )
    grupo = seed_docente["grupo"]
    resultado = asyncio.run(presentaciones_module._generar_esqueleto_ia(
        grupo, "Tema", n_slides_contenido=4, n_preguntas=2,
    ))
    assert resultado == []


def test_conteo_esqueleto_coincide_true_cuando_cantidades_exactas():
    from presentaciones import _conteo_esqueleto_coincide
    esqueleto = [_stub(), _stub("pregunta"), _stub(), _stub("pregunta")]
    assert _conteo_esqueleto_coincide(esqueleto, n_slides_contenido=2, n_preguntas=2) is True


def test_conteo_esqueleto_coincide_false_cuando_faltan_preguntas():
    from presentaciones import _conteo_esqueleto_coincide
    esqueleto = [_stub(), _stub(), _stub("pregunta")]
    assert _conteo_esqueleto_coincide(esqueleto, n_slides_contenido=2, n_preguntas=2) is False


def test_conteo_esqueleto_coincide_false_con_lista_vacia():
    from presentaciones import _conteo_esqueleto_coincide
    assert _conteo_esqueleto_coincide([], n_slides_contenido=2, n_preguntas=2) is False


def test_validar_esqueleto_descarta_items_malformados():
    from presentaciones import _validar_esqueleto
    bruto = [
        {"t": "c", "ti": "Título válido"},
        {"t": "x", "ti": "Tipo inválido"},
        {"t": "p"},  # sin título
        "no es un dict",
        {"t": "p", "ti": "Pregunta válida"},
    ]
    limpio = _validar_esqueleto(bruto)
    assert limpio == [
        {"tipo": "contenido", "titulo": "Título válido"},
        {"tipo": "pregunta", "titulo": "Pregunta válida"},
    ]


def test_validar_esqueleto_nunca_revienta_con_bruto_malformado():
    from presentaciones import _validar_esqueleto
    for bruto in (None, "no es un array", 123, {}, [None, 123, []]):
        assert _validar_esqueleto(bruto) == []
