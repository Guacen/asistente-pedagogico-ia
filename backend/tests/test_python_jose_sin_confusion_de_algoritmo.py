"""
Ancla la supresión de PYSEC-2026-4298 / CVE-2026-85394 / GHSA-3qf3-8w2g-rqmx
en .github/workflows/tests.yml (pip-audit --ignore-vuln).

La vulnerabilidad: python-jose <= 3.5.0 acepta una clave pública
asimétrica DER (sin armadura PEM/SSH) como si fuera un secreto HMAC —
si el código no fija el algoritmo al decodificar, alguien con la clave
pública del servicio puede forjar tokens HS256 válidos. Sin versión
corregida publicada (confirmado 2026-10-15 vía GitHub Advisory
Database: first_patched_version=null para todo el rango <= 3.5.0; el
proyecto lleva desde abril de 2026 sin push y el issue mpdavis/
python-jose#414 sin respuesta desde julio).

La supresión se justifica en que ESTE proyecto no es explotable: (a)
cada jwt.decode()/jwt.encode() fija el algoritmo explícitamente, nunca
"cualquiera", y (b) no existe NINGÚN material de clave asimétrica
(RSA/EC) para JWT en el repo — settings.SECRET_KEY es siempre un
secreto simétrico real.

Una supresión es una afirmación sobre cómo el código usa la librería.
Si el código cambia — alguien agrega un jwt.decode() sin `algorithms=`,
o introduce RS256/ES256 en cualquier parte — esa afirmación queda
falsa en silencio y nadie se entera, exactamente como
test_sin_fugas_de_excepcion.py ancla su propia suposición. Este test
hace lo mismo acá: si falla, la supresión en tests.yml ya no es válida
y hay que revisarla de nuevo (no basta con borrar la línea
--ignore-vuln).
"""
from __future__ import annotations

import ast
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
ESTE_ARCHIVO = Path(__file__).resolve()

# Algoritmos asimétricos que jose soporta — si cualquiera de estos
# strings aparece en el código de la app, la premisa "no hay material
# de clave asimétrica" ya no es cierta.
_ALGORITMOS_ASIMETRICOS = (
    "RS256", "RS384", "RS512",
    "ES256", "ES384", "ES512",
    "PS256", "PS384", "PS512",
)


def _archivos_py_de_la_app() -> list[Path]:
    """Todo backend/*.py recursivo, EXCLUYENDO tests/ (y este archivo,
    que necesariamente menciona los nombres de algoritmo asimétrico en
    su propio texto) — el código de producción es lo que importa."""
    archivos = []
    for ruta in BACKEND_DIR.rglob("*.py"):
        if ruta == ESTE_ARCHIVO:
            continue
        if "tests" in ruta.relative_to(BACKEND_DIR).parts:
            continue
        archivos.append(ruta)
    return archivos


def _llamadas_jwt(arbol: ast.AST, atributo: str):
    """Genera cada ast.Call de la forma jwt.<atributo>(...) en el árbol."""
    for nodo in ast.walk(arbol):
        if not isinstance(nodo, ast.Call):
            continue
        func = nodo.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr == atributo
            and isinstance(func.value, ast.Name)
            and func.value.id == "jwt"
        ):
            yield nodo


def test_ningun_algoritmo_asimetrico_en_el_codigo_de_la_app():
    """
    Si esto falla, alguien introdujo RS256/ES256/etc. en algún lugar —
    la premisa de la supresión ("no hay material de clave asimétrica
    para JWT") ya no es cierta, sin importar si jwt.decode() sigue
    fijando algorithms= correctamente.
    """
    ofensores = []
    for archivo in _archivos_py_de_la_app():
        texto = archivo.read_text(encoding="utf-8")
        for algoritmo in _ALGORITMOS_ASIMETRICOS:
            if algoritmo in texto:
                ofensores.append(f"{archivo.relative_to(BACKEND_DIR)}: {algoritmo}")
    assert ofensores == [], (
        "Aparecieron algoritmos asimétricos en el código de la app — "
        "esto invalida la supresión de PYSEC-2026-4298 en "
        ".github/workflows/tests.yml, hay que revisarla:\n" + "\n".join(ofensores)
    )


def test_todo_jwt_decode_fija_algorithms_explicitamente():
    """
    Cada jwt.decode(...) en el código de la app debe traer el keyword
    `algorithms=` — sin esto, python-jose acepta CUALQUIER algoritmo
    que el token diga que usa, que es exactamente el escenario que
    PYSEC-2026-4298 explota.
    """
    total_llamadas = 0
    ofensores = []
    for archivo in _archivos_py_de_la_app():
        arbol = ast.parse(archivo.read_text(encoding="utf-8"), filename=str(archivo))
        for llamada in _llamadas_jwt(arbol, "decode"):
            total_llamadas += 1
            nombres_kw = {kw.arg for kw in llamada.keywords}
            if "algorithms" not in nombres_kw:
                ofensores.append(
                    f"{archivo.relative_to(BACKEND_DIR)}:{llamada.lineno} "
                    f"jwt.decode(...) sin algorithms="
                )

    assert total_llamadas > 0, (
        "No se encontró ningún jwt.decode() en el código de la app — "
        "¿se movió a otro módulo? Si ya no se usa python-jose para "
        "decodificar, la supresión entera puede ser innecesaria."
    )
    assert ofensores == [], (
        "jwt.decode() sin algorithms= explícito — esto es EXACTAMENTE "
        "lo que PYSEC-2026-4298 explota (acepta cualquier algoritmo "
        "que el token diga tener):\n" + "\n".join(ofensores)
    )


def test_todo_jwt_encode_fija_algorithm_explicitamente():
    """Misma idea que el test de arriba, para el lado de la firma."""
    total_llamadas = 0
    ofensores = []
    for archivo in _archivos_py_de_la_app():
        arbol = ast.parse(archivo.read_text(encoding="utf-8"), filename=str(archivo))
        for llamada in _llamadas_jwt(arbol, "encode"):
            total_llamadas += 1
            nombres_kw = {kw.arg for kw in llamada.keywords}
            if "algorithm" not in nombres_kw:
                ofensores.append(
                    f"{archivo.relative_to(BACKEND_DIR)}:{llamada.lineno} "
                    f"jwt.encode(...) sin algorithm="
                )

    assert total_llamadas > 0, "No se encontró ningún jwt.encode() en el código de la app."
    assert ofensores == [], (
        "jwt.encode() sin algorithm= explícito:\n" + "\n".join(ofensores)
    )


def test_secret_key_no_parece_una_clave_asimetrica():
    """
    Chequeo de cordura sobre el propio valor default de
    config.Settings.SECRET_KEY — si algún día alguien lo reemplaza por
    una clave PEM/SSH (el vector exacto de PYSEC-2026-4298), esto lo
    atrapa sin depender de que el valor real de producción sea visible
    acá (nunca lo es: viene de la env var en Railway).
    """
    from config import Settings

    default = Settings.model_fields["SECRET_KEY"].default
    assert "BEGIN" not in default and "ssh-" not in default, (
        "El default de SECRET_KEY parece un material de clave PEM/SSH, "
        "no un secreto simétrico plano — revisar la supresión de "
        "PYSEC-2026-4298."
    )
