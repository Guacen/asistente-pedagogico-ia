"""
SPRINT 6 — puntaje configurable (competencia/inclusivo) + ajuste PIAR de
tiempo extendido + persistencia del puntaje acumulado (PuntajeEstudiante).

Cubre las verificaciones obligatorias del sprint:
1. Fórmula de puntaje en ambos modos, incluyendo los bordes: respuesta
   instantánea, respuesta en el último segundo, sin responder.
2. Un estudiante PIAR (1.5x) que responde al 50% de SU tiempo obtiene
   EXACTAMENTE los mismos puntos que uno sin PIAR al 50% del suyo.
4. Reconexión: el estudiante recupera su puntaje (no se resetea ni se
   duplica al volver a unirse / responder más preguntas con el mismo
   nombre).
"""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _crear_presentacion(db_session, docente, grupo, diapositivas, **kwargs):
    from models import Presentacion
    p = Presentacion(
        id_docente=docente.id_docente,
        id_grupo=grupo.id_grupo,
        titulo="T", tema="T",
        diapositivas=diapositivas,
        **kwargs,
    )
    db_session.add(p)
    db_session.commit()
    db_session.refresh(p)
    return p


def _crear_sesion(db_session, presentacion, codigo="ABC234"):
    from models import SesionPresentacion
    s = SesionPresentacion(id_presentacion=presentacion.id_presentacion, codigo=codigo)
    db_session.add(s)
    db_session.commit()
    db_session.refresh(s)
    return s


def _slide_multiple(tiempo_s=20):
    return {
        "tipo": "multiple", "pregunta": "¿Cuál?", "opciones": ["A", "B"],
        "correcta": 0, "tiempo_s": tiempo_s, "puntos": 100,
    }


# ═══════════════════════════════════════════════════════════════
# 1. Fórmula de puntaje — ambos modos, casos borde
# ═══════════════════════════════════════════════════════════════

def test_competencia_respuesta_instantanea_da_1000():
    from presentaciones import _calcular_puntos
    assert _calcular_puntos("competencia", True, 0, tiempo_limite_ms=20000) == 1000


def test_competencia_respuesta_en_el_ultimo_instante_da_500():
    """Justo al agotar el límite → mínimo garantizado (nunca menos de
    500 si la respuesta es correcta)."""
    from presentaciones import _calcular_puntos
    assert _calcular_puntos("competencia", True, 20000, tiempo_limite_ms=20000) == 500


def test_competencia_respuesta_tardia_por_latencia_no_baja_de_500():
    """tiempo_respuesta_ms > tiempo_limite_ms (llegó tarde por latencia
    de red) — se clampa, nunca queda por debajo del piso de 500 ni se
    vuelve negativo."""
    from presentaciones import _calcular_puntos
    assert _calcular_puntos("competencia", True, 25000, tiempo_limite_ms=20000) == 500


def test_competencia_a_mitad_de_tiempo_da_750():
    from presentaciones import _calcular_puntos
    assert _calcular_puntos("competencia", True, 10000, tiempo_limite_ms=20000) == 750


def test_competencia_incorrecta_da_0_sin_importar_el_tiempo():
    from presentaciones import _calcular_puntos
    assert _calcular_puntos("competencia", False, 0, tiempo_limite_ms=20000) == 0
    assert _calcular_puntos("competencia", False, 20000, tiempo_limite_ms=20000) == 0


def test_sin_responder_da_0_puntos():
    """"Sin responder" nunca llega a _calcular_puntos con es_correcta —
    se modela como es_correcta=None (poll/nube o directamente ninguna
    respuesta registrada), que en ambos modos debe dar 0."""
    from presentaciones import _calcular_puntos
    assert _calcular_puntos("competencia", None, None, tiempo_limite_ms=20000) == 0
    assert _calcular_puntos("inclusivo", None, None, tiempo_limite_ms=20000) == 0


def test_inclusivo_correcta_da_1000_sin_importar_el_tiempo():
    from presentaciones import _calcular_puntos
    assert _calcular_puntos("inclusivo", True, 0, tiempo_limite_ms=20000) == 1000
    assert _calcular_puntos("inclusivo", True, 20000, tiempo_limite_ms=20000) == 1000
    assert _calcular_puntos("inclusivo", True, 999999, tiempo_limite_ms=20000) == 1000


def test_inclusivo_incorrecta_da_0():
    from presentaciones import _calcular_puntos
    assert _calcular_puntos("inclusivo", False, 0, tiempo_limite_ms=20000) == 0


# ═══════════════════════════════════════════════════════════════
# 2. Ajuste PIAR — equivalencia de puntaje a igual fracción de tiempo
# ═══════════════════════════════════════════════════════════════

def test_tiempo_limite_ms_aplica_el_factor_solo_si_tiene_piar():
    from presentaciones import _tiempo_limite_ms
    from models import Presentacion
    p = Presentacion(
        id_docente="d", id_grupo="g", titulo="T", tema="T", diapositivas=[],
        tiempo_pregunta_s=20, factor_tiempo_piar=1.5,
    )
    assert _tiempo_limite_ms(p, tiene_piar=False) == 20000
    assert _tiempo_limite_ms(p, tiene_piar=True) == 30000


def test_estudiante_piar_al_50_por_ciento_de_su_tiempo_iguala_a_uno_sin_piar(db_session, seed_docente):
    """VERIFICACIÓN OBLIGATORIA #2: un estudiante con PIAR (1.5x) que usa
    el 50% de SU propio límite (30s → responde a los 15s) debe obtener
    EXACTAMENTE los mismos puntos que un estudiante sin PIAR que usa el
    50% del suyo (20s → responde a los 10s) — el ajuste no le cuesta
    puntos ni se los regala, sólo lo pone en igualdad de condiciones."""
    from presentaciones import iniciar_slide, registrar_respuesta
    from models import Estudiante

    docente = seed_docente["docente"]
    grupo = seed_docente["grupo"]

    db_session.add(Estudiante(id_grupo=grupo.id_grupo, codigo_estudiante="Con Piar", tiene_piar=True))
    db_session.add(Estudiante(id_grupo=grupo.id_grupo, codigo_estudiante="Sin Piar", tiene_piar=False))
    db_session.commit()

    presentacion = _crear_presentacion(
        db_session, docente, grupo, [_slide_multiple()],
        modo_puntaje="competencia", tiempo_pregunta_s=20, factor_tiempo_piar=1.5,
    )
    sesion = _crear_sesion(db_session, presentacion)
    iniciar_slide(db_session, sesion, 0)

    # Sin PIAR: límite 20s, responde al 50% → 10000ms.
    r_sin_piar = registrar_respuesta(db_session, sesion, presentacion, 0, "Sin Piar", "0", 10000)
    # Con PIAR: límite 20s * 1.5 = 30s, responde al 50% → 15000ms.
    r_con_piar = registrar_respuesta(db_session, sesion, presentacion, 0, "Con Piar", "0", 15000)

    assert r_sin_piar.tiempo_limite_ms == 20000
    assert r_con_piar.tiempo_limite_ms == 30000
    assert r_sin_piar.puntos_obtenidos == r_con_piar.puntos_obtenidos == 750


def test_estudiante_piar_que_no_matchea_roster_no_recibe_tiempo_extendido(db_session, seed_docente):
    """Un nombre que no matchea ningún estudiante del grupo (típico: el
    roster no tiene a todos, o el estudiante escribió su nombre distinto)
    se trata como sin PIAR — nunca "por si acaso" le da tiempo extra."""
    from presentaciones import iniciar_slide, registrar_respuesta

    docente = seed_docente["docente"]
    grupo = seed_docente["grupo"]
    presentacion = _crear_presentacion(
        db_session, docente, grupo, [_slide_multiple()],
        tiempo_pregunta_s=20, factor_tiempo_piar=1.5,
    )
    sesion = _crear_sesion(db_session, presentacion)
    iniciar_slide(db_session, sesion, 0)

    r = registrar_respuesta(db_session, sesion, presentacion, 0, "Nadie En El Roster", "0", 10000)
    assert r.tiempo_limite_ms == 20000


def test_match_piar_es_insensible_a_mayusculas_y_espacios(db_session, seed_docente):
    from presentaciones import _estudiante_tiene_piar
    from models import Estudiante

    grupo = seed_docente["grupo"]
    db_session.add(Estudiante(id_grupo=grupo.id_grupo, codigo_estudiante="María José", tiene_piar=True))
    db_session.commit()

    assert _estudiante_tiene_piar(db_session, grupo.id_grupo, "  MARÍA JOSÉ  ") is True
    assert _estudiante_tiene_piar(db_session, grupo.id_grupo, "maria jose") is False  # sin tilde, no matchea
    assert _estudiante_tiene_piar(db_session, grupo.id_grupo, "Otra Persona") is False


# ═══════════════════════════════════════════════════════════════
# 4. Reconexión — el estudiante recupera/acumula su puntaje
# ═══════════════════════════════════════════════════════════════

def test_puntaje_se_acumula_entre_preguntas_para_el_mismo_nombre(db_session, seed_docente):
    """Simula lo que pasa si el estudiante se desconecta y vuelve a
    entrar con el mismo nombre entre una pregunta y la siguiente: como
    la clave de PuntajeEstudiante es (sesión, nombre) — no un sid de
    socket — su puntaje sigue acumulando sobre la MISMA fila, nunca se
    resetea ni se duplica."""
    from presentaciones import iniciar_slide, registrar_respuesta
    from models import PuntajeEstudiante

    docente = seed_docente["docente"]
    grupo = seed_docente["grupo"]
    presentacion = _crear_presentacion(
        db_session, docente, grupo, [_slide_multiple(), _slide_multiple()],
        modo_puntaje="inclusivo",
    )
    sesion = _crear_sesion(db_session, presentacion)

    iniciar_slide(db_session, sesion, 0)
    registrar_respuesta(db_session, sesion, presentacion, 0, "Ana", "0", 1000)  # correcta → 1000

    # "Se desconecta y vuelve a entrar" — a nivel de DB esto es
    # simplemente responder de nuevo con el mismo nombre en la
    # siguiente pregunta; no hay estado de sid involucrado.
    iniciar_slide(db_session, sesion, 1)
    registrar_respuesta(db_session, sesion, presentacion, 1, "Ana", "1", 500)  # incorrecta → 0

    filas = db_session.query(PuntajeEstudiante).filter(
        PuntajeEstudiante.id_sesion == sesion.id_sesion,
        PuntajeEstudiante.nombre_estudiante == "Ana",
    ).all()
    assert len(filas) == 1, "no debe crear una segunda fila — el puntaje se pierde/duplica si esto falla"
    assert filas[0].puntaje_acumulado == 1000
    assert filas[0].aciertos == 1
    assert filas[0].respuestas_totales == 2


def test_respuesta_duplicada_no_duplica_el_puntaje(db_session, seed_docente):
    """El mismo estudiante respondiendo dos veces la MISMA pregunta
    (doble clic, reintento de red) es idempotente a nivel de respuesta
    (comportamiento ya existente) — y por lo tanto también a nivel de
    puntaje acumulado, que sólo se toca al crear una respuesta nueva."""
    from presentaciones import iniciar_slide, registrar_respuesta
    from models import PuntajeEstudiante

    docente = seed_docente["docente"]
    grupo = seed_docente["grupo"]
    presentacion = _crear_presentacion(
        db_session, docente, grupo, [_slide_multiple()], modo_puntaje="inclusivo",
    )
    sesion = _crear_sesion(db_session, presentacion)
    iniciar_slide(db_session, sesion, 0)

    registrar_respuesta(db_session, sesion, presentacion, 0, "Ana", "0", 1000)
    registrar_respuesta(db_session, sesion, presentacion, 0, "Ana", "0", 1000)  # duplicado idempotente

    puntaje = db_session.query(PuntajeEstudiante).filter(
        PuntajeEstudiante.id_sesion == sesion.id_sesion,
        PuntajeEstudiante.nombre_estudiante == "Ana",
    ).first()
    assert puntaje.puntaje_acumulado == 1000
    assert puntaje.respuestas_totales == 1


def test_calcular_podio_recupera_al_estudiante_reconectado(db_session, seed_docente):
    """El podio (lo que vería el docente) refleja el puntaje acumulado
    sin importar cuántas veces el estudiante se desconectó — se lee de
    PuntajeEstudiante/RespuestaPresentacion por nombre, no por sid."""
    from presentaciones import iniciar_slide, registrar_respuesta, calcular_podio

    docente = seed_docente["docente"]
    grupo = seed_docente["grupo"]
    presentacion = _crear_presentacion(
        db_session, docente, grupo, [_slide_multiple(), _slide_multiple()],
        modo_puntaje="inclusivo",
    )
    sesion = _crear_sesion(db_session, presentacion)

    iniciar_slide(db_session, sesion, 0)
    registrar_respuesta(db_session, sesion, presentacion, 0, "Ana", "0", 1000)
    iniciar_slide(db_session, sesion, 1)
    registrar_respuesta(db_session, sesion, presentacion, 1, "Ana", "0", 1000)

    podio = calcular_podio(db_session, sesion, presentacion)
    ranking = {r["nombre"]: r["puntaje_acumulado"] for r in podio["ranking"]}
    assert ranking["Ana"] == 2000
