"""Схемы для аутентификации."""
from pydantic import BaseModel, EmailStr
from typing import Optional


class AdminLogin(BaseModel):
    """Схема для входа."""
    username: str
    password: str


class Token(BaseModel):
    """Схема токена."""
    access_token: str
    token_type: str = "bearer"


class TokenData(BaseModel):
    """Данные из токена."""
    username: Optional[str] = None
    admin_id: Optional[int] = None

