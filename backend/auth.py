from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from config import settings
from database import get_db
from models import Docente, Suscripcion, UsoMensual
from schemas import ChangePassword, DocenteCreate, DocenteOut, DocenteUpdate, Token

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Configuración de seguridad
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


# ============================================================
# UTILIDADES JWT
# ============================================================

def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


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


def verify_token_for_socket(token: str, db: Session) -> Docente | None:
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

@router.post("/register", response_model=Token, status_code=status.HTTP_201_CREATED)
def register(data: DocenteCreate, db: Session = Depends(get_db)):
    # Verificar que el email no exista
    if db.query(Docente).filter(Docente.email == data.email).first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El email ya está registrado",
        )

    # Crear docente
    docente = Docente(
        nombre_completo=data.nombre_completo,
        email=data.email,
        password_hash=hash_password(data.password),
    )
    db.add(docente)
    db.flush()

    # Crear suscripción gratuita
    suscripcion = Suscripcion(id_docente=docente.id_docente, plan="free")
    db.add(suscripcion)
    db.commit()
    db.refresh(docente)

    token = create_access_token({"sub": docente.id_docente})
    return Token(
        access_token=token,
        token_type="bearer",
        docente=DocenteOut.model_validate(docente),
    )


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
def get_me(docente: Docente = Depends(get_current_docente)):
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


@router.delete("/cuenta")
def eliminar_cuenta(
    docente: Docente = Depends(get_current_docente),
    db: Session = Depends(get_db),
):
    db.delete(docente)
    db.commit()
    return {"mensaje": "Cuenta eliminada"}
