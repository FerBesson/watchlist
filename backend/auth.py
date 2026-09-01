import os
from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests
import jwt
from sqlalchemy.orm import Session

from .database import get_db
from .models import User
from .schemas import GoogleAuthRequest, TokenResponse, UserResponse

router = APIRouter(prefix="/api/auth", tags=["auth"])

JWT_SECRET = os.getenv("JWT_SECRET", "watchlist-app-jwt-secret-key-2026-safe")
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_DAYS = 30
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", None)

security = HTTPBearer(auto_error=False)


def create_access_token(user_id: int, email: str) -> str:
    expire = datetime.utcnow() + timedelta(days=JWT_EXPIRATION_DAYS)
    payload = {
        "sub": str(user_id),
        "email": email,
        "exp": expire,
        "iat": datetime.utcnow()
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: Session = Depends(get_db)
) -> User:
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No se proporcionó token de autenticación",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = credentials.credentials
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id = int(payload.get("sub"))
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido o expirado",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario no encontrado",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


@router.post("/google", response_model=TokenResponse)
def login_with_google(req: GoogleAuthRequest, db: Session = Depends(get_db)):
    try:
        # Validar el token contra los servidores de Google
        # Si GOOGLE_CLIENT_ID está configurado, valida la audiencia (audience)
        id_info = id_token.verify_oauth2_token(
            req.token,
            google_requests.Request(),
            audience=GOOGLE_CLIENT_ID
        )

        google_id = id_info.get("sub")
        email = id_info.get("email")
        name = id_info.get("name", "")
        picture = id_info.get("picture", "")

        if not email or not google_id:
            raise HTTPException(status_code=400, detail="Información de usuario de Google incompleta")

    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Token de Google inválido: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al verificar cuenta de Google: {str(e)}")

    # Buscar usuario existente o crearlo
    user = db.query(User).filter(User.google_id == google_id).first()
    if not user:
        # Verificar si existe por email (por si migración manual)
        user = db.query(User).filter(User.email == email).first()
        if user:
            user.google_id = google_id
            if name: user.name = name
            if picture: user.picture = picture
            db.commit()
            db.refresh(user)
        else:
            user = User(
                google_id=google_id,
                email=email,
                name=name,
                picture=picture
            )
            db.add(user)
            db.commit()
            db.refresh(user)

            # Crear lista por defecto "Favoritas" para el nuevo usuario
            try:
                from . import crud
                default_wl = schemas.WatchlistCreate(
                    name="Favoritas",
                    description="Mi lista de seguimiento principal",
                    metrics="sector,price,prev_close,change_percent"
                )
                created_wl = crud.create_watchlist(db, default_wl, user_id=user.id)
                crud.add_item_to_watchlist(db, created_wl.id, schemas.WatchlistItemCreate(symbol="CARTERA", is_divider=True))
                for sym in ["AAPL", "MSFT", "TSLA"]:
                    crud.add_item_to_watchlist(db, created_wl.id, schemas.WatchlistItemCreate(symbol=sym, is_divider=False))
                crud.add_item_to_watchlist(db, created_wl.id, schemas.WatchlistItemCreate(symbol="CRIPTO", is_divider=True))
                crud.add_item_to_watchlist(db, created_wl.id, schemas.WatchlistItemCreate(symbol="BTC-USD", is_divider=False))
            except Exception as seed_err:
                print(f"[Auth] Error creando lista inicial: {seed_err}")

    else:
        # Actualizar datos de perfil si cambiaron
        updated = False
        if name and user.name != name:
            user.name = name
            updated = True
        if picture and user.picture != picture:
            user.picture = picture
            updated = True
        if updated:
            db.commit()
            db.refresh(user)

    access_token = create_access_token(user.id, user.email)
    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        user=UserResponse.model_validate(user)
    )


@router.get("/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_user)):
    return UserResponse.model_validate(current_user)


@router.get("/config")
def get_auth_config():
    """Retorna la configuración pública para el frontend (Google Client ID)."""
    return {
        "google_client_id": GOOGLE_CLIENT_ID
    }

