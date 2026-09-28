"""
reportes.py — Sprint primer-uso, Parte D: "Reportar un problema".

Objetivo explícito: cuando un docente de la beta diga "no me funcionó la
planeación", que se pueda investigar qué pasó exactamente. Por eso el
correlation_id que manda el docente (capturado automáticamente por el
frontend del último error que vio, si hubo alguno) es EXACTAMENTE el
mismo que genera `errores.nuevo_correlation_id()` — sin esa cadena, un
reporte no sirve para investigar nada.

Minimización de datos a propósito: el docente sólo escribe la
descripción. Todo lo demás (pantalla, hora, correlation_id, navegador/
es_movil) lo captura el frontend solo. Nunca se guardan capturas de
pantalla, contenido de otros campos que el docente estuviera llenando,
ni datos de estudiantes.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from admin import _requerir_admin
from auth import get_current_docente
from database import get_db
from email_service import enviar_correo_reporte_problema
from models import Docente, ReporteProblema
from security_utils import sanitizar_texto

router = APIRouter(prefix="/api/reportes", tags=["reportes"])


# ═══════════════════════════════════════════════════════════════
# SCHEMAS
# ═══════════════════════════════════════════════════════════════

class ReporteProblemaCreate(BaseModel):
    descripcion: str = Field(min_length=1, max_length=2000)
    pantalla: Optional[str] = Field(default=None, max_length=300)
    correlation_id: Optional[str] = Field(default=None, max_length=16)
    navegador: Optional[str] = Field(default=None, max_length=50)
    es_movil: Optional[bool] = None

    @field_validator("descripcion")
    @classmethod
    def _sanitizar_descripcion(cls, v: str) -> str:
        # Nunca colapsa a None — el campo es obligatorio (str, no
        # Optional[str]); si sanitizar_texto la deja vacía (sólo traía
        # HTML/scripts), el endpoint la rechaza explícito con un 400
        # claro en vez de que esto se convierta en un None inesperado.
        return sanitizar_texto(v, 2000) or ""

    @field_validator("pantalla", "navegador")
    @classmethod
    def _sanitizar_opcional(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        limpio = sanitizar_texto(v, 2000)
        return limpio or None


class ReporteProblemaOut(BaseModel):
    id_reporte: str
    docente_nombre: str
    docente_email: str
    descripcion: str
    pantalla: Optional[str]
    correlation_id: Optional[str]
    navegador: Optional[str]
    es_movil: Optional[bool]
    creado_en: datetime


# ═══════════════════════════════════════════════════════════════
# ENDPOINTS
# ═══════════════════════════════════════════════════════════════

@router.post("", status_code=201)
def crear_reporte(
    data: ReporteProblemaCreate,
    docente: Docente = Depends(get_current_docente),
    db: Session = Depends(get_db),
):
    """
    Deliberadamente cuelga sólo de get_current_docente — ni de
    get_current_docente_verificado ni de verify_trial_active. Un docente
    con el trial vencido, o que ni siquiera verificó su correo todavía,
    debe poder reportar igual ("no puedo verificar mi correo", "el trial
    se venció y no debería"): el propósito de este endpoint es
    diagnosticar problemas, no debería estar bloqueado por otros.
    """
    if not data.descripcion.strip():
        # sanitizar_texto pudo dejar la descripción vacía si sólo traía
        # HTML/scripts — no tiene sentido guardar un reporte sin texto.
        raise HTTPException(status_code=400, detail="Describe qué pasó antes de enviar el reporte.")

    reporte = ReporteProblema(
        id_docente=docente.id_docente,
        descripcion=data.descripcion,
        pantalla=data.pantalla,
        correlation_id=data.correlation_id,
        navegador=data.navegador,
        es_movil=data.es_movil,
    )
    db.add(reporte)
    db.commit()
    db.refresh(reporte)

    # Best-effort: si el correo falla, el reporte YA está guardado — nunca
    # se pierde un reporte por un problema de envío de correo. No se
    # propaga la excepción ni se cambia la respuesta al docente.
    try:
        enviar_correo_reporte_problema(
            descripcion=reporte.descripcion,
            docente_nombre=docente.nombre_completo,
            docente_email=docente.email,
            pantalla=reporte.pantalla,
            correlation_id=reporte.correlation_id,
            navegador=reporte.navegador,
            es_movil=reporte.es_movil,
            creado_en=reporte.creado_en,
        )
    except Exception:
        logging.getLogger("errores").exception(
            "No se pudo enviar el correo de aviso para el reporte %s", reporte.id_reporte,
        )

    return {"mensaje": "Gracias, recibimos tu reporte."}


@router.get("", response_model=List[ReporteProblemaOut])
def listar_reportes(
    _admin: Docente = Depends(_requerir_admin),
    db: Session = Depends(get_db),
):
    """Sólo es_admin=true — un docente normal no ve reportes, ni los
    suyos ni los de nadie (no hay ningún endpoint que se los muestre)."""
    reportes = (
        db.query(ReporteProblema)
        .order_by(ReporteProblema.creado_en.desc())
        .limit(200)
        .all()
    )
    return [
        ReporteProblemaOut(
            id_reporte=r.id_reporte,
            docente_nombre=r.docente.nombre_completo if r.docente else "(cuenta eliminada)",
            docente_email=r.docente.email if r.docente else "",
            descripcion=r.descripcion,
            pantalla=r.pantalla,
            correlation_id=r.correlation_id,
            navegador=r.navegador,
            es_movil=r.es_movil,
            creado_en=r.creado_en,
        )
        for r in reportes
    ]
