"""Валидаторы для входных данных."""
from pydantic import BaseModel, Field, validator
from typing import Optional


class TelegramChannelInput(BaseModel):
    """Валидация входных данных для Telegram канала."""
    channel_id: Optional[int] = None
    channel_username: Optional[str] = None
    channel_title: str = Field(..., min_length=1, max_length=255)
    
    @validator('channel_username')
    def validate_username(cls, v):
        if v and not v.startswith('@'):
            return v
        elif v:
            return v[1:]  # Убираем @ если есть
        return v
    
    class Config:
        extra = "forbid"


class MaxChannelInput(BaseModel):
    """Валидация входных данных для MAX канала."""
    channel_id: str = Field(..., min_length=1, max_length=255)
    channel_username: Optional[str] = None
    channel_title: Optional[str] = None
    
    class Config:
        extra = "forbid"


class CrosspostingLinkInput(BaseModel):
    """Валидация входных данных для связи кросспостинга."""
    telegram_channel_id: int = Field(..., gt=0)
    max_channel_id: int = Field(..., gt=0)
    is_enabled: bool = True
    
    class Config:
        extra = "forbid"





