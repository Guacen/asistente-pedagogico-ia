"""
seed_dbas.py — Siembra el catálogo de Derechos Básicos de Aprendizaje (DBA)
del MEN desde backend/data/dba_seed_data.json. Sprint malla-curricular.

Idempotente: usa (asignatura, grado, numero) como clave — correrlo de nuevo
no duplica filas. Se llama desde migrate.py en el startup, mismo patrón que
seed_pro_user().
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
        count = 0
        for asignatura, grados in data["asignaturas"].items():
            for grado, dbas in grados.items():
                for dba in dbas:
                    existente = db.query(DBA).filter_by(
                        asignatura=asignatura, grado=grado, numero=dba["numero"],
                    ).first()
                    if existente:
                        continue
                    db.add(DBA(
                        asignatura=asignatura,
                        grado=grado,
                        numero=dba["numero"],
                        enunciado=dba["enunciado"],
                        evidencias=dba.get("evidencias", []),
                    ))
                    count += 1
        db.commit()
        if count:
            print(f"✅ Seed: {count} DBA(s) nuevos sembrados desde dba_seed_data.json")
        else:
            print("ℹ️  Seed DBA: catálogo ya estaba completo, nada que sembrar")
    finally:
        db.close()


if __name__ == "__main__":
    seed_dbas()
