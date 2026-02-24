import os
import uuid
from typing import List

import aiofiles
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from sqlalchemy.orm import Session

from auth import get_current_docente
from config import settings
from database import get_db
from models import Archivo, Estudiante, Grupo, Nota
from schemas import (
    ArchivoOut, EstudianteCreate, EstudianteOut, EstudianteUpdate,
    GrupoCreate, GrupoOut, GrupoUpdate, NotaCreate, NotaOut,
)

router = APIRouter(prefix="/api", tags=["grupos"])


# ============================================================
# GRUPOS
# ============================================================

@router.get("/grupos", response_model=List[GrupoOut])
def list_grupos(
    docente=Depends(get_current_docente),
    db: Session = Depends(get_db),
):
    return db.query(Grupo).filter(Grupo.id_docente == docente.id_docente).all()


@router.get("/grupos/{grupo_id}", response_model=GrupoOut)
def get_grupo(
    grupo_id: str,
    docente=Depends(get_current_docente),
    db: Session = Depends(get_db),
):
    grupo = db.query(Grupo).filter(
        Grupo.id_grupo == grupo_id,
        Grupo.id_docente == docente.id_docente,
    ).first()
    if not grupo:
        raise HTTPException(status_code=404, detail="Grupo no encontrado")
    return grupo


@router.post("/grupos", response_model=GrupoOut, status_code=status.HTTP_201_CREATED)
def create_grupo(
    data: GrupoCreate,
    docente=Depends(get_current_docente),
    db: Session = Depends(get_db),
):
    # Verificar límite del plan free (1 grupo)
    if docente.suscripcion and docente.suscripcion.plan == "free":
        count = db.query(Grupo).filter(Grupo.id_docente == docente.id_docente).count()
        if count >= 1:
            raise HTTPException(
                status_code=403,
                detail="Plan Free: máximo 1 grupo. Actualiza a Pro para grupos ilimitados.",
            )

    grupo = Grupo(
        id_docente=docente.id_docente,
        **data.model_dump(),
    )
    db.add(grupo)
    db.commit()
    db.refresh(grupo)
    return grupo


@router.put("/grupos/{grupo_id}", response_model=GrupoOut)
def update_grupo(
    grupo_id: str,
    data: GrupoUpdate,
    docente=Depends(get_current_docente),
    db: Session = Depends(get_db),
):
    grupo = db.query(Grupo).filter(
        Grupo.id_grupo == grupo_id,
        Grupo.id_docente == docente.id_docente,
    ).first()
    if not grupo:
        raise HTTPException(status_code=404, detail="Grupo no encontrado")

    for field, value in data.model_dump(exclude_none=True).items():
        setattr(grupo, field, value)
    db.commit()
    db.refresh(grupo)
    return grupo


@router.delete("/grupos/{grupo_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_grupo(
    grupo_id: str,
    docente=Depends(get_current_docente),
    db: Session = Depends(get_db),
):
    grupo = db.query(Grupo).filter(
        Grupo.id_grupo == grupo_id,
        Grupo.id_docente == docente.id_docente,
    ).first()
    if not grupo:
        raise HTTPException(status_code=404, detail="Grupo no encontrado")
    db.delete(grupo)
    db.commit()


# ============================================================
# ESTUDIANTES
# ============================================================

def _get_grupo_or_404(grupo_id: str, docente_id: str, db: Session) -> Grupo:
    grupo = db.query(Grupo).filter(
        Grupo.id_grupo == grupo_id,
        Grupo.id_docente == docente_id,
    ).first()
    if not grupo:
        raise HTTPException(status_code=404, detail="Grupo no encontrado")
    return grupo


@router.get("/grupos/{grupo_id}/estudiantes", response_model=List[EstudianteOut])
def list_estudiantes(
    grupo_id: str,
    docente=Depends(get_current_docente),
    db: Session = Depends(get_db),
):
    _get_grupo_or_404(grupo_id, docente.id_docente, db)
    return db.query(Estudiante).filter(Estudiante.id_grupo == grupo_id).all()


@router.post("/grupos/{grupo_id}/estudiantes", response_model=EstudianteOut, status_code=201)
def create_estudiante(
    grupo_id: str,
    data: EstudianteCreate,
    docente=Depends(get_current_docente),
    db: Session = Depends(get_db),
):
    _get_grupo_or_404(grupo_id, docente.id_docente, db)
    estudiante = Estudiante(id_grupo=grupo_id, **data.model_dump())
    db.add(estudiante)
    db.commit()
    db.refresh(estudiante)
    return estudiante


@router.put("/grupos/{grupo_id}/estudiantes/{estudiante_id}", response_model=EstudianteOut)
def update_estudiante(
    grupo_id: str,
    estudiante_id: str,
    data: EstudianteUpdate,
    docente=Depends(get_current_docente),
    db: Session = Depends(get_db),
):
    _get_grupo_or_404(grupo_id, docente.id_docente, db)
    est = db.query(Estudiante).filter(
        Estudiante.id_estudiante == estudiante_id,
        Estudiante.id_grupo == grupo_id,
    ).first()
    if not est:
        raise HTTPException(status_code=404, detail="Estudiante no encontrado")

    for field, value in data.model_dump(exclude_none=True).items():
        setattr(est, field, value)
    db.commit()
    db.refresh(est)
    return est


@router.delete("/grupos/{grupo_id}/estudiantes/{estudiante_id}", status_code=204)
def delete_estudiante(
    grupo_id: str,
    estudiante_id: str,
    docente=Depends(get_current_docente),
    db: Session = Depends(get_db),
):
    _get_grupo_or_404(grupo_id, docente.id_docente, db)
    est = db.query(Estudiante).filter(
        Estudiante.id_estudiante == estudiante_id,
        Estudiante.id_grupo == grupo_id,
    ).first()
    if not est:
        raise HTTPException(status_code=404, detail="Estudiante no encontrado")
    db.delete(est)
    db.commit()


# ============================================================
# NOTAS
# ============================================================

@router.get("/grupos/{grupo_id}/notas", response_model=List[NotaOut])
def list_notas(
    grupo_id: str,
    docente=Depends(get_current_docente),
    db: Session = Depends(get_db),
):
    _get_grupo_or_404(grupo_id, docente.id_docente, db)
    return db.query(Nota).filter(Nota.id_grupo == grupo_id).all()


@router.post("/grupos/{grupo_id}/notas", response_model=NotaOut, status_code=201)
def create_nota(
    grupo_id: str,
    data: NotaCreate,
    docente=Depends(get_current_docente),
    db: Session = Depends(get_db),
):
    _get_grupo_or_404(grupo_id, docente.id_docente, db)
    nota = Nota(id_grupo=grupo_id, contenido=data.contenido)
    db.add(nota)
    db.commit()
    db.refresh(nota)
    return nota


@router.delete("/grupos/{grupo_id}/notas/{nota_id}", status_code=204)
def delete_nota(
    grupo_id: str,
    nota_id: str,
    docente=Depends(get_current_docente),
    db: Session = Depends(get_db),
):
    _get_grupo_or_404(grupo_id, docente.id_docente, db)
    nota = db.query(Nota).filter(Nota.id_nota == nota_id, Nota.id_grupo == grupo_id).first()
    if not nota:
        raise HTTPException(status_code=404, detail="Nota no encontrada")
    db.delete(nota)
    db.commit()


# ============================================================
# ARCHIVOS
# ============================================================

@router.get("/grupos/{grupo_id}/archivos", response_model=List[ArchivoOut])
def list_archivos(
    grupo_id: str,
    docente=Depends(get_current_docente),
    db: Session = Depends(get_db),
):
    _get_grupo_or_404(grupo_id, docente.id_docente, db)
    return db.query(Archivo).filter(Archivo.id_grupo == grupo_id).all()


@router.post("/grupos/{grupo_id}/archivos", response_model=ArchivoOut, status_code=201)
async def upload_archivo(
    grupo_id: str,
    file: UploadFile = File(...),
    docente=Depends(get_current_docente),
    db: Session = Depends(get_db),
):
    _get_grupo_or_404(grupo_id, docente.id_docente, db)

    # Validar tamaño
    max_bytes = settings.MAX_FILE_SIZE_MB * 1024 * 1024
    contents = await file.read()
    if len(contents) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"Archivo muy grande. Máximo {settings.MAX_FILE_SIZE_MB}MB",
        )

    # Guardar archivo
    upload_path = os.path.join(settings.UPLOAD_DIR, grupo_id)
    os.makedirs(upload_path, exist_ok=True)

    filename = f"{uuid.uuid4()}_{file.filename}"
    filepath = os.path.join(upload_path, filename)

    async with aiofiles.open(filepath, "wb") as f:
        await f.write(contents)

    archivo = Archivo(
        id_grupo=grupo_id,
        nombre_archivo=file.filename,
        ruta_archivo=filepath,
        tamanio=len(contents),
        tipo_mime=file.content_type,
    )
    db.add(archivo)
    db.commit()
    db.refresh(archivo)
    return archivo


@router.delete("/grupos/{grupo_id}/archivos/{archivo_id}", status_code=204)
def delete_archivo(
    grupo_id: str,
    archivo_id: str,
    docente=Depends(get_current_docente),
    db: Session = Depends(get_db),
):
    _get_grupo_or_404(grupo_id, docente.id_docente, db)
    archivo = db.query(Archivo).filter(
        Archivo.id_archivo == archivo_id,
        Archivo.id_grupo == grupo_id,
    ).first()
    if not archivo:
        raise HTTPException(status_code=404, detail="Archivo no encontrado")

    # Eliminar archivo físico
    if os.path.exists(archivo.ruta_archivo):
        os.remove(archivo.ruta_archivo)

    db.delete(archivo)
    db.commit()
