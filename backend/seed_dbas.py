"""
seed_dbas.py — Siembra/actualiza el catálogo de Derechos Básicos de
Aprendizaje (DBA) del MEN desde backend/data/dba_seed_data.json.
Sprint malla-curricular; upsert agregado en sprint dba-lenguaje-reextraido.

Upsert por (asignatura, grado, numero): si la fila no existe, se crea;
si existe pero enunciado/evidencias difieren del JSON, se actualiza.
Nunca borra filas que ya no estén en el JSON (evita perder datos si el
JSON de un sprint aún no cubre todas las asignaturas). Se llama desde
migrate.py en el startup, mismo patrón que seed_pro_user().

Por qué el upsert (y no sólo insert-si-falta, como antes): la primera
versión de este catálogo (sprint malla-curricular) tenía evidencias
truncadas y, en Lenguaje, contenido desalineado un grado completo
frente al PDF oficial del MEN. Con sólo insert-si-falta, corregir el
JSON en el repo no se reflejaba en una DB que ya tenía esas filas
sembradas — cada corrección futura habría necesitado un DELETE manual
antes de cada deploy. Con upsert, un redeploy normal alcanza.
"""
from pathlib import Path
import json

from database import SessionLocal
from models import DBA

_SEED_PATH = Path(__file__).resolve().parent / "data" / "dba_seed_data.json"


def seed_dbas():
    if not _SEED_PATH.exists():
        print(f"⚠️  seed_dbas: no se encontró {_SEED_PATH} — se omite la siembra")
        return

    with open(_SEED_PATH, encoding="utf-8") as f:
        data = json.load(f)

    db = SessionLocal()
    try:
        nuevos = 0
        actualizados = 0
        for asignatura, grados in data["asignaturas"].items():
            for grado, dbas in grados.items():
                for dba in dbas:
                    evidencias = dba.get("evidencias", [])
                    existente = db.query(DBA).filter_by(
                        asignatura=asignatura, grado=grado, numero=dba["numero"],
                    ).first()
                    if existente:
                        if existente.enunciado != dba["enunciado"] or existente.evidencias != evidencias:
                            existente.enunciado = dba["enunciado"]
                            existente.evidencias = evidencias
                            actualizados += 1
                        continue
                    db.add(DBA(
                        asignatura=asignatura,
                        grado=grado,
                        numero=dba["numero"],
                        enunciado=dba["enunciado"],
                        evidencias=evidencias,
                    ))
                    nuevos += 1
        db.commit()
        if nuevos or actualizados:
            partes = []
            if nuevos:
                partes.append(f"{nuevos} nuevo(s)")
            if actualizados:
                partes.append(f"{actualizados} actualizado(s)")
            print(f"✅ Seed DBA: {' + '.join(partes)} desde dba_seed_data.json")
        else:
            print("ℹ️  Seed DBA: catálogo ya estaba completo y al día, nada que sembrar")
    finally:
        db.close()


if __name__ == "__main__":
    seed_dbas()
