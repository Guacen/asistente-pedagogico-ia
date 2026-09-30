"""
Sprint F, Parte G1 — la puerta lateral de Socket.io que el flag NO
cerraba. Confirmado en producción con FEATURE_PRESENTACIONES apagado:

    POST /api/presentaciones/generar          -> 404
    socket.emit('presentacion:unirse', {...}) -> "Código de sesión no
                                                   encontrado." (el
                                                   handler SÍ corría y
                                                   consultaba la DB)

Causa: `main.py` hacía `import presentacion_events` sin condición — el
decorador `@sio.on(...)` registra el handler en el MOMENTO del import,
no en cada conexión, así que los 6 eventos "presentacion:*" quedaban
registrados en el `sio` compartido pasara lo que pasara con el flag. El
router HTTP sí se gatea correctamente (_verificar_feature_habilitada,
una dependency que se re-evalúa en cada request) — Socket.io necesita
el gate en el import, no en cada evento, porque para cuando un evento
llega el registro ya pasó.

Por qué este test corre en un SUBPROCESO limpio, no importando
`socket_events`/`main` directo en el proceso de pytest: otros archivos
de este mismo suite (test_presentacion_events.py,
test_presentacion_events_puntaje.py) hacen
`import presentacion_events` directo a nivel de módulo para poder
testear esos handlers — pytest los colecciona a todos ANTES de correr
ningún test, así que para cuando cualquier test corre, esos handlers
ya están registrados en el `sio` singleton compartido de ese proceso,
sin importar el flag. Un test que revisara `sio.handlers` en el mismo
proceso de pytest daría falso negativo (o falso positivo) dependiendo
del orden de colección — no prueba nada real sobre `main.py`. Un
subproceso nuevo, en cambio, reproduce EXACTAMENTE lo que pasa cuando
Railway arranca el proceso real.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent

_SCRIPT = """
import main
from socket_events import sio
eventos = {
    "presentacion:unirse", "presentacion:sincronizar", "presentacion:responder",
    "presentacion:iniciar_slide", "presentacion:cerrar_slide", "presentacion:finalizar",
}
registrados = set(sio.handlers.get("/", {}).keys())
print("REGISTRADOS=" + ",".join(sorted(registrados & eventos)))
"""


def _eventos_registrados_en_proceso_limpio(feature_presentaciones: bool) -> set[str]:
    env = dict(os.environ)
    env["DATABASE_URL"] = "sqlite://"
    env["FEATURE_PRESENTACIONES"] = "true" if feature_presentaciones else "false"

    resultado = subprocess.run(
        [sys.executable, "-c", _SCRIPT],
        cwd=str(BACKEND_DIR),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert resultado.returncode == 0, (
        f"el subproceso falló al importar main.py:\n{resultado.stderr}"
    )
    for linea in resultado.stdout.splitlines():
        if linea.startswith("REGISTRADOS="):
            valor = linea[len("REGISTRADOS="):]
            return set(valor.split(",")) if valor else set()
    raise AssertionError(f"el subproceso no imprimió la línea esperada:\n{resultado.stdout}")


_EVENTOS_PRESENTACIONES = {
    "presentacion:unirse", "presentacion:sincronizar", "presentacion:responder",
    "presentacion:iniciar_slide", "presentacion:cerrar_slide", "presentacion:finalizar",
}


def test_eventos_presentaciones_no_se_registran_con_flag_apagado():
    """
    El test que atrapa exactamente el hallazgo de G1: con
    FEATURE_PRESENTACIONES apagado (el default en producción hoy), NI
    UNO de los 6 eventos "presentacion:*" debe existir en el registro
    de Socket.io — no basta con que respondan error, no deben estar.
    """
    registrados = _eventos_registrados_en_proceso_limpio(feature_presentaciones=False)
    assert registrados == set(), (
        f"Estos eventos de Socket.io de Presentaciones quedaron registrados "
        f"con el flag apagado (deberían no existir): {registrados}"
    )


def test_eventos_presentaciones_si_se_registran_con_flag_prendido():
    """Contraparte: con el flag prendido, los 6 eventos SÍ deben quedar
    registrados — si este test fallara, Presentaciones estaría rota
    incluso cuando se activa a propósito."""
    registrados = _eventos_registrados_en_proceso_limpio(feature_presentaciones=True)
    assert registrados == _EVENTOS_PRESENTACIONES, (
        f"Con el flag prendido faltan eventos por registrar: "
        f"{_EVENTOS_PRESENTACIONES - registrados}"
    )
