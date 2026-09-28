"""
Sprint primer-uso, Parte C — guarda de regresión estática: ningún
`HTTPException` en el backend debe interpolar el texto crudo de una
excepción (`detail=f"...{exc}"` / `detail=str(exc)`) directo al
cliente. Encontramos 9 así (documento.py x3, grupos.py, observaciones.py,
piar.py x2, suscripciones.py x2) y se reemplazaron por
errores.error_manejable(), que loguea el detalle real y sólo expone un
mensaje claro + correlation_id.

Este test evita que alguien vuelva a colar el patrón sin darse cuenta —
mismo nivel de garantía que test_migrate_tipos_postgres.py usa para los
tipos de columna inválidos en Postgres.
"""
from __future__ import annotations

import re
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent

# Patrones que interpolan la excepción CRUDA en el detail de una
# HTTPException — exactamente lo que se filtraba antes de este sprint.
_PATRONES_FUGA = (
    re.compile(r'detail\s*=\s*f["\'][^"\']*\{exc\b'),
    re.compile(r'detail\s*=\s*f["\'][^"\']*\{e\}'),
    re.compile(r'detail\s*=\s*str\(exc\)'),
    re.compile(r'detail\s*=\s*str\(e\)'),
)

# Archivos que están fuera de este chequeo a propósito: la suite de
# tests puede necesitar construir un mensaje así para simular datos, y
# errores.py documenta el patrón prohibido en su propio docstring (texto,
# no código real).
_EXCLUIR = {"errores.py"}


def _archivos_python_del_backend():
    for path in BACKEND_DIR.glob("*.py"):
        if path.name in _EXCLUIR:
            continue
        yield path


def test_ningun_endpoint_interpola_la_excepcion_cruda_en_detail():
    fallos = []
    for path in _archivos_python_del_backend():
        texto = path.read_text(encoding="utf-8")
        for i, linea in enumerate(texto.splitlines(), start=1):
            for patron in _PATRONES_FUGA:
                if patron.search(linea):
                    fallos.append(f"{path.name}:{i}: {linea.strip()!r}")
    assert not fallos, (
        "HTTPException interpolando la excepción cruda en detail — usa "
        "errores.error_manejable() en su lugar:\n" + "\n".join(fallos)
    )
