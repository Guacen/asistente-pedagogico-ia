"""
security_utils.py — utilidades compartidas del sprint seguridad-avanzada:
sanitización de texto libre, política de contraseñas, IP del cliente y
registro en audit_log.

Centralizado acá (en vez de duplicado en auth.py/piar.py/grupos.py) para
que las reglas de sanitización y contraseña se apliquen una sola vez y
de forma consistente en todos los endpoints que las necesitan.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

import bleach
from fastapi import Request
from sqlalchemy.orm import Session

from models import AuditLog


# ============================================================
# SANITIZACIÓN DE TEXTO LIBRE (XSS)
# ============================================================

def sanitizar_texto(texto: Optional[str], max_len: int) -> Optional[str]:
    """
    Elimina HTML/scripts de un campo de texto libre y lo trunca a
    `max_len`. bleach.clean(strip=True) remueve las etiquetas (en vez de
    escaparlas) porque estos campos se usan tal cual en DOCX y prompts al
    LLM, no en HTML — no necesitamos preservar el markup, sólo que no
    sobreviva ningún tag.

    None pasa a través sin tocar (todos los llamadores tratan campos
    opcionales) — la validación de "requerido" es responsabilidad de
    Pydantic, no de este helper.
    """
    if texto is None:
        return None
    limpio = bleach.clean(texto, tags=[], attributes={}, strip=True).strip()
    return limpio[:max_len]


# ============================================================
# VALIDACIÓN DE CELDAS CSV IMPORTADAS (inyección de fórmulas / control)
# ============================================================

# Excel/Sheets interpreta como fórmula cualquier celda que empiece con
# uno de estos caracteres al abrir el archivo — incluso si el CSV nunca
# pasó por una hoja de cálculo al crearse. Es un vector clásico ("CSV/
# Formula injection", CWE-1236) independiente de XSS: sanitizar_texto
# (que sólo quita HTML) no lo cubre.
_PREFIJOS_FORMULA_CSV = ("=", "+", "-", "@")

_CARACTERES_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def celda_csv_es_riesgosa(valor: Optional[str]) -> Optional[str]:
    """
    Revisa una celda cruda de un CSV importado por el usuario en busca de
    dos clases de contenido peligroso que sanitizar_texto no cubre
    (sanitizar_texto sólo quita HTML/XSS):

      - Inyección de fórmulas: la celda empieza (ignorando espacios al
        inicio) con =, +, - o @.
      - Caracteres de control no imprimibles.

    Devuelve una razón legible en español si encuentra algo, o None si la
    celda es segura. No modifica `valor` — la fila se rechaza entera en
    vez de guardarse "pelada" (ver importar_estudiantes_csv en grupos.py).
    """
    if not valor:
        return None
    if valor.lstrip().startswith(_PREFIJOS_FORMULA_CSV):
        return "empieza con un carácter que Excel/Sheets interpreta como fórmula (=, +, - o @)"
    if _CARACTERES_CONTROL_RE.search(valor):
        return "contiene caracteres de control no permitidos"
    return None


# ============================================================
# GUARDA BÁSICA CONTRA PROMPT INJECTION (chat con el LLM)
# ============================================================

# Frases que intentan hacer que el LLM ignore su system prompt o cambie
# de rol. No es (ni pretende ser) una defensa completa — el LLM real ya
# tiene su propio system prompt con instrucciones explícitas de dominio
# pedagógico — esto es una primera capa que remueve los patrones más
# obvios antes de que el texto llegue al modelo.
_PATRONES_INYECCION = (
    "ignore previous instructions",
    "ignora las instrucciones anteriores",
    "ignora todas las instrucciones",
    "disregard previous instructions",
    "olvida las instrucciones",
    "you are now",
    "ahora eres",
    "act as",
    "actúa como si",
    "system prompt",
    "system:",
    "\\nsystem:",
    "nueva instrucción:",
    "new instruction:",
    "sobreescribe tus instrucciones",
    "override your instructions",
)


def sanitizar_mensaje_chat(texto: str, max_len: int = 2000) -> str:
    """
    Limpia el input del docente antes de enviarlo al LLM: quita HTML,
    trunca a `max_len` y remueve (case-insensitive) las frases de la
    lista de patrones de inyección conocidos, dejando el resto del
    mensaje intacto.
    """
    limpio = sanitizar_texto(texto, max_len) or ""
    minuscula = limpio.lower()
    for patron in _PATRONES_INYECCION:
        if patron in minuscula:
            # Reemplazo case-insensitive preservando el resto del texto.
            idx = 0
            while True:
                pos = limpio.lower().find(patron, idx)
                if pos == -1:
                    break
                limpio = limpio[:pos] + limpio[pos + len(patron):]
                idx = pos
    return limpio.strip()


# ============================================================
# POLÍTICA DE CONTRASEÑAS
# ============================================================

# Top de contraseñas más filtradas/comunes (subset representativo de las
# listas públicas tipo "10-million-password-list" / rockyou). No es
# exhaustivo — es una barrera contra los casos más obvios y evidentes.
CONTRASENAS_COMUNES = frozenset({
    "password", "password1", "password123", "12345678", "123456789",
    "1234567890", "qwerty123", "qwertyuiop", "123123123", "111111111",
    "administrator", "letmein123", "welcome123", "iloveyou1", "sunshine1",
    "princess1", "football1", "baseball1", "dragon123", "monkey123",
    "master123", "superman1", "trustno1a", "abc123456", "changeme1",
    "passw0rd1", "p@ssw0rd1", "qazwsx123", "1q2w3e4r5t", "zaq12wsx3",
    "asdfghjkl", "1qaz2wsx3", "michael1234", "jennifer1234", "computer1",
    "internet1", "maestria1", "colombia123", "docente123", "profesor123",
    "estudiante1", "bienvenido1", "contraseña1", "contrasena1",
    "12341234", "11111111", "00000000", "99999999", "88888888",
    "asdasdasd", "qweqweqwe", "zxczxczxc", "poiuytrewq", "mnbvcxz123",
    "aaaaaaaa", "abcdefgh", "abcabc123", "test12345", "demo12345",
    "guest1234", "temporal1", "cambiame1", "nuevaclave", "12345qwerty",
    "letmein12", "trustno12", "shadow123", "matrix123", "batman123",
    "starwars1", "pokemon123", "hunter123", "ranger123", "buster123",
    "soccer123", "harley123", "hockey123", "yankees1", "ashley123",
    "bailey123", "george123", "andrew123", "charlie1", "thomas123",
    "hannah123", "amanda123", "loveme123", "jordan23", "cheese123",
    "tigger123", "chicken123", "purple123", "orange123", "yellow123",
    "freedom123", "whatever1", "cookie123", "summer2024", "winter2024",
    "spring2024", "autumn2024", "january123", "december12",
    "password12", "password2024", "colombia2024", "maestria2024",
})


def es_contrasena_comun(password: str) -> bool:
    return password.strip().lower() in CONTRASENAS_COMUNES


def validar_password_fuerte(password: str) -> Optional[str]:
    """
    Devuelve un mensaje de error si la contraseña no cumple la política,
    o None si es válida.

    Reglas: mínimo 8 caracteres, al menos 1 mayúscula, al menos 1 dígito,
    y que no esté en la lista de contraseñas más comunes.
    """
    if len(password) < 8:
        return "La contraseña debe tener al menos 8 caracteres."
    if not any(c.isupper() for c in password):
        return "La contraseña debe incluir al menos una letra mayúscula."
    if not any(c.isdigit() for c in password):
        return "La contraseña debe incluir al menos un número."
    if es_contrasena_comun(password):
        return "Esta contraseña es demasiado común. Elige una más segura."
    return None


# ============================================================
# IP DEL CLIENTE
# ============================================================

def obtener_ip_cliente(request: Request) -> Optional[str]:
    """
    Extrae la IP del cliente respetando proxies confiables (Railway pone
    X-Forwarded-For). Usado tanto para auditoría de consentimiento
    Ley 1581 (auth.py) como para audit_log (este módulo).
    """
    xff = request.headers.get("x-forwarded-for")
    if xff:
        # X-Forwarded-For puede ser una lista: "client, proxy1, proxy2".
        # El cliente es siempre el primero.
        return xff.split(",")[0].strip()[:45]
    if request.client and request.client.host:
        return request.client.host[:45]
    return None


# ============================================================
# AUDIT LOG
# ============================================================

def registrar_auditoria(
    db: Session,
    docente_id: str,
    accion: str,
    *,
    recurso_tipo: Optional[str] = None,
    recurso_id: Optional[str] = None,
    ip: Optional[str] = None,
) -> None:
    """
    Inserta una fila en audit_log. Nunca lanza — un fallo al auditar no
    debe tumbar la operación que se está auditando (ver PIAR, exportar
    DOCX, etc.); si el insert falla se hace rollback silencioso de ESA
    fila y se loguea por consola, sin propagar la excepción.
    """
    try:
        db.add(AuditLog(
            id_docente=docente_id,
            accion=accion,
            recurso_tipo=recurso_tipo,
            recurso_id=recurso_id,
            ip=ip,
            timestamp=datetime.utcnow(),
        ))
        db.commit()
    except Exception as exc:  # pragma: no cover — defensivo
        db.rollback()
        print(f"⚠️  audit_log: no se pudo registrar '{accion}' para docente {docente_id}: {exc}")
