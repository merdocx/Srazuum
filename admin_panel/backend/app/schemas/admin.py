"""Схемы для администраторов."""

from pydantic import BaseModel, EmailStr
from datetime import datetime
from typing import Optional


class AdminCreate(BaseModel):
    """Схема для создания администратора."""

    username: str
    password: str
    email: Optional[EmailStr] = None


class AdminResponse(BaseModel):
    """Схема ответа с данными администратора."""

    id: int
    username: str
    email: Optional[str]
    is_active: bool
    last_login: Optional[datetime]
    created_at: datetime

    class Config:
        from_attributes = True
