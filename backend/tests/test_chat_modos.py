"""
Tests unitarios de la infra multi-modo del chat (Fase B).

Cubre:
- Cada modo recibe su system prompt específico
- Contexto de estudiante mencionado se inyecta en socioemocional
- Contexto de columnas del libro se inyecta en calificacion
- Modo inválido cae a planeacion (retro-compat)
- Detección de códigos: word-boundary, case-insensitive, sin duplicados

Estos tests NO llaman a Claude — ejercitan sólo la construcción del prompt.
"""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


# ─── Doubles simples (no ORM) ───────────────────────────────────

class _Grupo:
    def __init__(self, asignatura="matematicas", grado="8", anio=2026,
                 periodo=1, cantidad=20, recursos=None):
        self.asignatura = asignatura
        self.grado = grado
        self.anio_lectivo = anio
        self.periodo_actual = periodo
        self.cantidad_estudiantes = cantidad
        self.recursos_disponibles = recursos


class _Est:
    def __init__(self, codigo, piar=False, diag=None, ajustes=None, id_est=None, genero=None):
        self.codigo_estudiante = codigo
        self.tiene_piar = piar
        self.diagnostico = diag
        self.ajustes = ajustes
        self.id_estudiante = id_est or f"id-{codigo}"
        self.genero = genero


class _Col:
    def __init__(self, nombre, tipo="quiz", porcentaje=40, periodo=1, orden=0):
        self.nombre = nombre
        self.tipo = tipo
        self.porcentaje = porcentaje
        self.periodo = periodo
        self.orden = orden
        self.id_columna = f"col-{nombre}"


# ─── Selección de prompt por modo ────────────────────────────────

def test_cada_modo_incluye_su_marcador_de_system_prompt():
    from ia import construir_system_prompt
    grupo = _Grupo()
    ests = []

    p_plan = construir_system_prompt(grupo, ests, modo="planeacion")
    p_socio = construir_system_prompt(grupo, ests, modo="socioemocional")
    p_cal = construir_system_prompt(grupo, ests, modo="calificacion")

    # Cada prompt tiene un marcador único de su modo
    assert "Planeación de clase" in p_plan
    assert "Evaluación socioemocional" in p_socio
    assert "Orientación de calificación" in p_cal
    # No hay cross-contamination
    assert "Evaluación socioemocional" not in p_plan
    assert "Planeación de clase" not in p_socio


def test_modo_invalido_cae_a_planeacion():
    """Retro-compat: strings desconocidos, None, vacíos → planeacion."""
    from ia import construir_system_prompt
    grupo = _Grupo()

    p_none = construir_system_prompt(grupo, [], modo=None)
    p_vacio = construir_system_prompt(grupo, [], modo="")
    p_basura = construir_system_prompt(grupo, [], modo="modo-que-no-existe")

    # Todos deben ser equivalentes al modo planeacion
    p_plan = construir_system_prompt(grupo, [], modo="planeacion")
    assert p_none == p_plan
    assert p_vacio == p_plan
    assert p_basura == p_plan
    assert "Planeación de clase" in p_none


# ─── Contexto socioemocional ─────────────────────────────────────

def test_socio_con_mencion_inyecta_datos_del_estudiante():
    from ia import construir_system_prompt
    grupo = _Grupo()
    ests = [
        _Est("E001", piar=True, diag="MARCADOR_DIAGNOSTICO_UNICO",
             ajustes="Instrucciones cortas", id_est="e1"),
        _Est("E002", id_est="e2"),
    ]
    notas = {"e1": [4.5, 3.8, 4.0], "e2": [3.0]}

    p = construir_system_prompt(
        grupo, ests, modo="socioemocional",
        mensaje_texto="El estudiante E001 se está aislando en clase.",
        notas_por_estudiante=notas,
    )

    assert "ESTUDIANTES MENCIONADOS" in p
    assert "E001" in p
    # Sprint F, Parte B1: diagnóstico/ajustes son dato de salud — NO viajan
    # al prompt fuera de modo PIAR, ni siquiera cuando el estudiante es
    # mencionado explícitamente por el docente. (Nota: el valor de prueba
    # NO puede ser "TDA-H" — el prompt base de socioemocional lo menciona
    # como ejemplo genérico de señal observable, y eso daría un falso
    # positivo si buscáramos ese string literal en el resultado.)
    assert "MARCADOR_DIAGNOSTICO_UNICO" not in p
    assert "Instrucciones cortas" not in p
    # Estadística de notas del mencionado (avg 4.1, min 3.8, max 4.5)
    assert "promedio 4.1" in p
    # E002 NO fue mencionado → no debe aparecer en la sección de mencionados
    # (aparece en el bloque general de grupo si tiene PIAR, pero E002 no lo tiene)
    assert "E002" not in p


def test_socio_sin_mencion_muestra_estadisticas_del_grupo():
    from ia import construir_system_prompt
    grupo = _Grupo()
    ests = [_Est(f"E00{i}", id_est=f"e{i}") for i in range(1, 6)]
    ests[0].tiene_piar = True

    notas = {
        "e1": [4.5], "e2": [3.2], "e3": [2.5], "e4": [3.7], "e5": [1.8],
    }
    p = construir_system_prompt(
        grupo, ests, modo="socioemocional",
        mensaje_texto="Hablemos del grupo en general.",
        notas_por_estudiante=notas,
    )

    assert "CONTEXTO SOCIOEMOCIONAL DEL GRUPO" in p
    assert "Con PIAR: 1" in p
    # Distribución esperada: e1=4.5 aprobado, e2=3.2 riesgo, e3=2.5 reprobado,
    # e4=3.7 aprobado, e5=1.8 reprobado → 2 aprobados / 1 riesgo / 2 reprobados
    assert "Aprobados (≥3.5): 2" in p
    assert "En riesgo (3.0–3.4): 1" in p
    assert "Reprobados (<3.0): 2" in p


# ─── Contexto de calificación ────────────────────────────────────

def test_calificacion_inyecta_columnas_del_periodo_y_escala():
    from ia import construir_system_prompt
    grupo = _Grupo(periodo=2)
    ests = [_Est("E001", piar=True, ajustes="Tiempo extra en pruebas")]
    cols = [
        _Col("Quiz 1", tipo="quiz", porcentaje=40),
        _Col("Parcial", tipo="parcial", porcentaje=60),
    ]
    p = construir_system_prompt(
        grupo, ests, modo="calificacion",
        columnas_periodo_actual=cols,
    )
    assert "CONTEXTO DE EVALUACIÓN" in p
    assert "Periodo actual: 2" in p
    assert "Decreto 1290" in p
    assert "Quiz 1" in p
    assert "Parcial" in p
    assert "40%" in p and "60%" in p
    assert "peso total 100%" in p
    # PIAR marcado explícitamente
    assert "Estudiantes con PIAR" in p
    # Sprint F, Parte B1: `ajustes` es dato de salud — no viaja al prompt
    # en modo calificación, ni siquiera para estudiantes con PIAR.
    assert "Tiempo extra en pruebas" not in p


def test_calificacion_advierte_cuando_no_hay_columnas():
    from ia import construir_system_prompt
    grupo = _Grupo()
    p = construir_system_prompt(
        grupo, [], modo="calificacion",
        columnas_periodo_actual=[],
    )
    assert "Aún no hay evaluaciones registradas" in p


# ─── Detección de códigos ────────────────────────────────────────

def test_deteccion_codigos_word_boundary_case_insensitive():
    from ia import _detectar_codigos_mencionados
    codigos = ["E001", "E002", "E100"]

    # Match básico
    assert _detectar_codigos_mencionados("el estudiante E001", codigos) == ["E001"]
    # Case-insensitive
    assert _detectar_codigos_mencionados("e001 anduvo mal", codigos) == ["E001"]
    # No confundir E00 con E001 — word boundary
    assert _detectar_codigos_mencionados("lo llamé el", codigos) == []
    # Múltiples menciones en orden de aparición sin duplicados
    result = _detectar_codigos_mencionados(
        "E001 y luego E100 y de nuevo E001", codigos,
    )
    assert result == ["E001", "E100"]
    # Vacío / no codigos
    assert _detectar_codigos_mencionados("", codigos) == []
    assert _detectar_codigos_mencionados("bla bla", []) == []


# ─── API key detection ───────────────────────────────────────────

def test_api_key_placeholder_se_detecta_como_no_configurada(monkeypatch):
    """
    _api_key_configurada() debe devolver False para el placeholder
    'sk-ant-XXXXXXXXXX' o strings vacíos — así el frontend puede
    deshabilitar el botón antes de fallar silenciosamente.
    """
    from config import settings
    import ia

    monkeypatch.setattr(settings, "CLAUDE_API_KEY", "sk-ant-XXXXXXXXXX")
    assert ia._api_key_configurada() is False


# ─── Sprint F, Parte B1 — datos clínicos fuera del prompt ────────
#
# Test permanente: diagnostico/ajustes son dato de salud (Ley 1581) y
# NUNCA deben viajar al prompt de Claude salvo en modo PIAR ("Ajustes
# de aula"), que es el único modo para el que el docente los puso ahí.
# Antes de esta corrección viajaban en CUALQUIER modo (ia.py, hallazgo
# de la auditoría Sprint F Parte A). Este test protege contra que un
# sprint futuro los reintroduzca en un modo nuevo o en uno existente.

def test_diagnostico_ajustes_nunca_viajan_fuera_de_modo_piar():
    from ia import construir_system_prompt
    from prompts import MODOS_ACTIVOS, MODO_PIAR

    grupo = _Grupo()
    ests = [
        _Est("E001", piar=True, diag="MARCADOR_DIAGNOSTICO_UNICO",
             ajustes="MARCADOR_AJUSTES_UNICO", id_est="e1"),
    ]

    for modo in MODOS_ACTIVOS:
        if modo == MODO_PIAR:
            continue
        p = construir_system_prompt(
            grupo, ests, modo=modo,
            mensaje_texto="E001 necesita apoyo.",
        )
        assert "MARCADOR_DIAGNOSTICO_UNICO" not in p, (
            f"modo={modo!r} filtró el diagnóstico al prompt — sólo PIAR puede."
        )
        assert "MARCADOR_AJUSTES_UNICO" not in p, (
            f"modo={modo!r} filtró los ajustes al prompt — sólo PIAR puede."
        )


def test_diagnostico_ajustes_si_viajan_en_modo_piar():
    """Contraparte del test anterior: modo PIAR SÍ debe recibirlos — si
    no, el docente tendría que retipearlos cada vez que genera el PIAR."""
    from ia import construir_system_prompt

    grupo = _Grupo()
    est = _Est("E001", piar=True, diag="MARCADOR_DIAGNOSTICO_UNICO",
               ajustes="MARCADOR_AJUSTES_UNICO", id_est="e1")

    p = construir_system_prompt(
        grupo, [est], modo="piar", estudiante_piar=est,
    )
    assert "MARCADOR_DIAGNOSTICO_UNICO" in p
    assert "MARCADOR_AJUSTES_UNICO" in p


def test_observaciones_no_incluye_diagnostico_ni_ajustes():
    """Mismo test que el de arriba, para el flujo separado de
    observaciones.py (no pasa por construir_system_prompt)."""
    from observaciones import _contexto_estudiante

    est = _Est("E001", piar=True, diag="MARCADOR_DIAGNOSTICO_UNICO",
               ajustes="MARCADOR_AJUSTES_UNICO", id_est="e1")

    ctx = _contexto_estudiante(est)
    assert "MARCADOR_DIAGNOSTICO_UNICO" not in ctx
    assert "MARCADOR_AJUSTES_UNICO" not in ctx
    assert "Tiene PIAR activo" in ctx
