"""API для аутентификации."""

from datetime import timedelta, datetime
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel

from app.core.database import get_db
from app.core.security import verify_password, create_access_token, decode_access_token
from app.core.config import settings
from app.models.admin import Admin
from app.schemas.auth import Token
from app.schemas.admin import AdminResponse

router = APIRouter()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


class LoginRequest(BaseModel):
    """Запрос на вход через JSON."""

    username: str
    password: str


async def get_current_admin(token: str = Depends(oauth2_scheme), db: AsyncSession = Depends(get_db)) -> Admin:
    """Получить текущего администратора из токена."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    payload = decode_access_token(token)
    if payload is None:
        raise credentials_exception

    username: str = payload.get("sub")
    if username is None:
        raise credentials_exception

    result = await db.execute(select(Admin).where(Admin.username == username, Admin.is_active == True))
    admin = result.scalar_one_or_none()

    if admin is None:
        raise credentials_exception

    return admin


async def authenticate_user(username: str, password: str, db: AsyncSession) -> Admin:
    """Аутентификация пользователя."""
    result = await db.execute(select(Admin).where(Admin.username == username))
    admin = result.scalar_one_or_none()

    if not admin or not admin.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not verify_password(password, admin.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return admin


@router.post("/login", response_model=Token)
async def login(form_data: OAuth2PasswordRequestForm = Depends(), db: AsyncSession = Depends(get_db)):
    """Вход в систему через OAuth2 form."""
    admin = await authenticate_user(form_data.username, form_data.password, db)

    # Обновляем last_login
    admin.last_login = datetime.utcnow()
    await db.commit()

    # Создаем токен
    access_token_expires = timedelta(minutes=settings.access_token_expire_minutes)
    access_token = create_access_token(data={"sub": admin.username, "admin_id": admin.id}, expires_delta=access_token_expires)

    return {"access_token": access_token, "token_type": "bearer"}


@router.post("/login/json", response_model=Token)
async def login_json(login_data: LoginRequest, db: AsyncSession = Depends(get_db)):
    """Вход в систему через JSON."""
    admin = await authenticate_user(login_data.username, login_data.password, db)

    # Обновляем last_login
    admin.last_login = datetime.utcnow()
    await db.commit()

    # Создаем токен
    access_token_expires = timedelta(minutes=settings.access_token_expire_minutes)
    access_token = create_access_token(data={"sub": admin.username, "admin_id": admin.id}, expires_delta=access_token_expires)

    return {"access_token": access_token, "token_type": "bearer"}


@router.get("/me", response_model=AdminResponse)
async def read_users_me(current_admin: Admin = Depends(get_current_admin)):
    """Получить информацию о текущем администраторе."""
    return current_admin
