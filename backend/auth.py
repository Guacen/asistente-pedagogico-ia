import secrets
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from config import settings
from database import get_db
from email_service import enviar_correo_reset_password, enviar_correo_verificacion
from models import Docente, EmailVerification, PasswordResetToken, Suscripcion, UsoMensual
from schemas import (
    AceptarConsentimiento, ChangePassword, DocenteCreate, DocenteOut,
    DocenteUpdate, ForgotPassword, ReenviarVerificacion, ResetPassword, Token,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Ventana de vida de un token de verificación. 24h según el sprint.
_TOKEN_VERIFICACION_HORAS = 24

# Ventana de vida de un token de recuperación de contraseña. Más corto
# que el de verificación de email (1h vs 24h) — un link de reset es más
# sensible si queda vivo mucho tiempo en una bandeja comprometida.
_TOKEN_RESET_PASSWORD_HORAS = 1

# Configuración de seguridad
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


# ============================================================
# UTILIDADES JWT
# ============================================================

def _truncate_password(password: str) -> str:
    """bcrypt acepta máximo 72 bytes — truncar para evitar ValueError."""
    return password.encode("utf-8")[:72].decode("utf-8", errors="ignore")


def hash_password(password: str) -> str:
    return pwd_context.hash(_truncate_password(password))


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(_truncate_password(plain), hashed)


def create_access_token(data: dict) -> str:
    payload = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload.update({"exp": expire})
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def get_current_docente(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> Docente:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token inválido o expirado",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        docente_id: str = payload.get("sub")
        if not docente_id:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    docente = db.query(Docente).filter(Docente.id_docente == docente_id).first()
    if not docente:
        raise credentials_exception
    return docente


def get_current_docente_verificado(
    docente: Docente = Depends(get_current_docente),
) -> Docente:
    """
    Igual que get_current_docente pero además exige email verificado.

    Devuelve 401 con `code="email_no_verificado"` cuando el docente
    autenticó pero todavía no confirmó su correo — el frontend usa ese
    code para redirigir a la landing de "verifica tu correo" en lugar
    de pensar que el token expiró.

    Nota: `docente.email_verificado` es TRUE para todos los docentes
    grandfathered (ver migrate.py). Sólo los registros post-deploy
    arrancan en FALSE.
    """
    if not docente.email_verificado:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "email_no_verificado",
                "message": "Debes verificar tu correo antes de continuar.",
                "email": docente.email,
            },
        )
    return docente


def trial_vencido(docente: Docente, db: Session) -> bool:
    """
    True si el docente NO puede usar funciones de producto ahora mismo.

    Efecto lateral: si el trial venció recién en esta llamada (plan
    todavía en 'trial' pero trial_ends_at ya pasó), lo pasa a 'expirado'
    y commitea — mismo patrón self-healing que el resto de esta base de
    código usa para estados derivados (ver rate limits diarios). Los
    llamadores comparten esta función para no duplicar la lógica:
    verify_trial_active() (REST, vía Depends) y send_message() en
    socket_events.py (el chat en tiempo real, que NO pasa por Depends).
    """
    if docente.plan == "activo":
        return False
    if docente.plan == "trial":
        if docente.trial_ends_at and docente.trial_ends_at > datetime.utcnow():
            return False
        docente.plan = "expirado"
        db.commit()
        return True
    # plan == "expirado" (o cualquier valor inesperado) → bloqueado.
    return True


def verify_trial_active(
    response: Response,
    docente: Docente = Depends(get_current_docente),
    db: Session = Depends(get_db),
) -> Docente:
    """
    Dependencia para endpoints de producto (grupos, chat, piar, malla,
    observaciones, sesiones, institución). NO se aplica a /api/auth/*
    (gestión de cuenta debe seguir funcionando con trial vencido) ni a
    /api/suscripciones/* (si no, un docente con trial vencido jamás
    podría pagar para reactivarse — sería un callejón sin salida).

    Con trial activo agrega el header X-Trial-Days-Left para que el
    frontend pueda mostrar el banner sin una llamada aparte.
    """
    if trial_vencido(docente, db):
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="trial_expirado",
        )
    if docente.plan == "trial":
        from schemas import _dias_restantes_trial
        response.headers["X-Trial-Days-Left"] = str(
            _dias_restantes_trial(docente.plan, docente.trial_ends_at)
        )
    return docente


def verify_token_for_socket(token: str, db: Session) -> Optional[Docente]:
    """Verifica token JWT para conexiones WebSocket."""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        docente_id: str = payload.get("sub")
        if not docente_id:
            return None
        return db.query(Docente).filter(Docente.id_docente == docente_id).first()
    except JWTError:
        return None


# ============================================================
# ENDPOINTS
# ============================================================

def _crear_token_verificacion(
    db: Session, docente: Docente, request: Request,
) -> str:
    """
    Crea un EmailVerification (24h TTL) y devuelve el link absoluto que
    debe ir al correo. Extrae la URL base del request para que funcione
    detrás de proxies (Railway, Cloudflare) sin hardcodear el host.
    """
    token = secrets.token_urlsafe(32)  # 43 chars — cabe en VARCHAR(64)
    verificacion = EmailVerification(
        id_docente=docente.id_docente,
        token=token,
        expires_at=datetime.utcnow() + timedelta(hours=_TOKEN_VERIFICACION_HORAS),
    )
    db.add(verificacion)
    db.commit()

    base = str(request.base_url).rstrip("/")
    return f"{base}/verificar-email.html?token={token}"


def _crear_token_reset_password(
    db: Session, docente: Docente, request: Request,
) -> str:
    """
    Crea un PasswordResetToken (1h TTL) y devuelve el link absoluto que
    debe ir al correo. Mismo patrón que `_crear_token_verificacion`.
    """
    token = secrets.token_urlsafe(32)  # 43 chars — cabe en VARCHAR(64)
    reset = PasswordResetToken(
        id_docente=docente.id_docente,
        token=token,
        expires_at=datetime.utcnow() + timedelta(hours=_TOKEN_RESET_PASSWORD_HORAS),
    )
    db.add(reset)
    db.commit()

    base = str(request.base_url).rstrip("/")
    return f"{base}/nueva-password.html?token={token}"


def _obtener_ip_cliente(request: Request) -> Optional[str]:
    """
    Extrae la IP del cliente respetando proxies confiables (Railway pone
    X-Forwarded-For). Se guarda para auditoría de consentimiento Ley 1581.
    """
    xff = request.headers.get("x-forwarded-for")
    if xff:
        # X-Forwarded-For puede ser una lista: "client, proxy1, proxy2".
        # El cliente es siempre el primero.
        return xff.split(",")[0].strip()[:45]
    if request.client and request.client.host:
        return request.client.host[:45]
    return None


@router.post("/register", response_model=Token, status_code=status.HTTP_201_CREATED)
def register(data: DocenteCreate, request: Request, db: Session = Depends(get_db)):
    # Consentimiento Ley 1581 — obligatorio para nuevos registros.
    # Grandfathered (docentes previos al deploy) aceptan post-login vía
    # POST /aceptar-consentimiento; ese path NO pasa por este endpoint.
    if not data.consentimiento_datos:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Debes aceptar la Política de Tratamiento de Datos Personales.",
        )

    # Verificar que el email no exista
    if db.query(Docente).filter(Docente.email == data.email).first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El email ya está registrado",
        )

    ahora = datetime.utcnow()
    # Crear docente — email_verificado=False (default); el docente no
    # puede acceder a /api/auth/me hasta clicar el link del correo.
    # Prueba gratuita: arranca en 'trial' con 7 días desde el registro,
    # sin pedir tarjeta ni aprobación manual (sprint trial-7-dias).
    docente = Docente(
        nombre_completo=data.nombre_completo,
        email=data.email,
        password_hash=hash_password(data.password),
        consentimiento_datos=True,
        fecha_consentimiento=ahora,
        ip_consentimiento=_obtener_ip_cliente(request),
        plan="trial",
        trial_ends_at=ahora + timedelta(days=settings.TRIAL_DIAS),
    )
    db.add(docente)
    db.flush()

    # Crear suscripción gratuita
    suscripcion = Suscripcion(id_docente=docente.id_docente, plan="free")
    db.add(suscripcion)
    db.commit()
    db.refresh(docente)

    # Enviar correo de verificación. Un fallo en el envío NO aborta el
    # registro — el docente puede pedir reenviar después. Loguea si falla.
    link = _crear_token_verificacion(db, docente, request)
    enviar_correo_verificacion(docente.email, docente.nombre_completo, link)

    # Emitimos el JWT igual — el frontend redirige a "verifica tu correo"
    # y la mayoría de endpoints exigen get_current_docente_verificado.
    token = create_access_token({"sub": docente.id_docente})
    return Token(
        access_token=token,
        token_type="bearer",
        docente=DocenteOut.model_validate(docente),
    )


@router.get("/verificar-email")
def verificar_email(token: str, db: Session = Depends(get_db)):
    """
    Consume un token de verificación de email. Idempotente: llamarlo dos
    veces con el mismo token válido devuelve éxito ambas veces (el segundo
    reconoce que ya está verificado).
    """
    verificacion = db.query(EmailVerification).filter(
        EmailVerification.token == token
    ).first()
    if not verificacion:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Token de verificación no encontrado o inválido.",
        )
    if verificacion.expires_at < datetime.utcnow():
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail={
                "code": "token_expirado",
                "message": "El enlace expiró. Solicita uno nuevo.",
            },
        )

    docente = db.query(Docente).filter(
        Docente.id_docente == verificacion.id_docente
    ).first()
    if not docente:
        raise HTTPException(status_code=404, detail="Docente asociado no existe.")

    ahora = datetime.utcnow()
    if not docente.email_verificado:
        docente.email_verificado = True
        docente.fecha_verificacion = ahora
    if verificacion.verified_at is None:
        verificacion.verified_at = ahora
    db.commit()

    return {
        "verificado": True,
        "email": docente.email,
        "mensaje": "Correo verificado correctamente.",
    }


@router.post("/reenviar-verificacion")
def reenviar_verificacion(
    data: ReenviarVerificacion,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Genera un nuevo token y reenvía el correo de verificación.

    Contrato de privacidad: devuelve 200 con el mismo mensaje sea el
    email conocido o no — así no exponemos qué correos están registrados.
    Sólo emitimos correo si realmente hay un docente con ese email y
    todavía no está verificado.
    """
    docente = db.query(Docente).filter(Docente.email == data.email).first()
    if docente and not docente.email_verificado:
        link = _crear_token_verificacion(db, docente, request)
        enviar_correo_verificacion(docente.email, docente.nombre_completo, link)

    return {"mensaje": "Si el correo existe y no está verificado, te enviamos un nuevo enlace."}


@router.post("/aceptar-consentimiento", response_model=DocenteOut)
def aceptar_consentimiento(
    data: AceptarConsentimiento,
    request: Request,
    docente: Docente = Depends(get_current_docente),
    db: Session = Depends(get_db),
):
    """
    Registra el consentimiento Ley 1581 para docentes grandfathered
    (los que ya existían al momento del deploy y por eso tienen
    `consentimiento_datos IS NULL`).

    Idempotente para docentes que ya lo tenían en TRUE — sólo re-guarda
    la fecha e IP. Los que rechazan (`aceptado=False`) reciben 400: el
    consentimiento es requisito para usar la plataforma, y el "rechazo"
    real del usuario es no seguir usándola.
    """
    if not data.aceptado:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Debes aceptar la política para continuar usando Maestr.ia.",
        )
    docente.consentimiento_datos = True
    docente.fecha_consentimiento = datetime.utcnow()
    docente.ip_consentimiento = _obtener_ip_cliente(request)
    db.commit()
    db.refresh(docente)
    return docente


@router.post("/login", response_model=Token)
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    docente = db.query(Docente).filter(Docente.email == form.username).first()

    if not docente or not verify_password(form.password, docente.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales inválidas",
        )

    token = create_access_token({"sub": docente.id_docente})
    return Token(
        access_token=token,
        token_type="bearer",
        docente=DocenteOut.model_validate(docente),
    )


@router.get("/me", response_model=DocenteOut)
def get_me(docente: Docente = Depends(get_current_docente_verificado)):
    """
    Endpoint canónico "quién soy". Requiere email verificado — el
    frontend detecta el 401 con `code="email_no_verificado"` y redirige
    a la landing de "verifica tu correo" en lugar de asumir que expiró
    el token. Grandfathered pasan porque `email_verificado=TRUE`.
    """
    return docente


@router.get("/me-raw", response_model=DocenteOut)
def get_me_raw(docente: Docente = Depends(get_current_docente)):
    """
    Variante de /me que NO exige email verificado. La usa el flujo de
    "verificar tu correo" (landing verificar-email.html) que necesita
    saber quién es el docente sin bootstrappear la app entera.
    """
    return docente


@router.put("/perfil", response_model=DocenteOut)
def update_perfil(
    data: DocenteUpdate,
    docente: Docente = Depends(get_current_docente),
    db: Session = Depends(get_db),
):
    for field, value in data.model_dump(exclude_none=True).items():
        setattr(docente, field, value)
    db.commit()
    db.refresh(docente)
    return docente


@router.post("/cambiar-password")
def cambiar_password(
    data: ChangePassword,
    docente: Docente = Depends(get_current_docente),
    db: Session = Depends(get_db),
):
    if not verify_password(data.password_actual, docente.password_hash):
        raise HTTPException(status_code=400, detail="Contraseña actual incorrecta")

    docente.password_hash = hash_password(data.password_nuevo)
    db.commit()
    return {"mensaje": "Contraseña actualizada correctamente"}


@router.post("/forgot-password")
def forgot_password(
    data: ForgotPassword,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Inicia la recuperación de contraseña. Mismo contrato de privacidad
    que `reenviar_verificacion`: devuelve 200 con mensaje genérico sea el
    email conocido o no, para no exponer qué correos están registrados.
    """
    docente = db.query(Docente).filter(Docente.email == data.email).first()
    if docente:
        link = _crear_token_reset_password(db, docente, request)
        enviar_correo_reset_password(docente.email, docente.nombre_completo, link)

    return {"mensaje": "Si el correo está registrado, te enviamos un enlace para restablecer tu contraseña."}


@router.post("/reset-password")
def reset_password(
    token: str,
    data: ResetPassword,
    db: Session = Depends(get_db),
):
    """
    Consume un token de recuperación y establece la nueva contraseña.
    De un solo uso: `used_at` se marca al consumirlo y una segunda
    llamada con el mismo token es rechazada como inválida.
    """
    reset = db.query(PasswordResetToken).filter(
        PasswordResetToken.token == token
    ).first()
    if not reset or reset.used_at is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Token de recuperación no encontrado o ya utilizado.",
        )
    if reset.expires_at < datetime.utcnow():
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail={
                "code": "token_expirado",
                "message": "El enlace expiró. Solicita uno nuevo.",
            },
        )

    docente = db.query(Docente).filter(
        Docente.id_docente == reset.id_docente
    ).first()
    if not docente:
        raise HTTPException(status_code=404, detail="Docente asociado no existe.")

    docente.password_hash = hash_password(data.password_nuevo)
    reset.used_at = datetime.utcnow()
    db.commit()

    return {"mensaje": "Contraseña actualizada correctamente."}


@router.delete("/cuenta")
def eliminar_cuenta(
    docente: Docente = Depends(get_current_docente),
    db: Session = Depends(get_db),
):
    db.delete(docente)
    db.commit()
    return {"mensaje": "Cuenta eliminada"}
