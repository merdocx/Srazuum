"""Конфигурация админ-панели."""

from pydantic_settings import BaseSettings
from pydantic import Field
from typing import List
import os
from pathlib import Path

# Получаем путь к корню проекта (crossposting_service)
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent.parent


class Settings(BaseSettings):
    """Настройки админ-панели."""

    # Database (используем существующую БД из основного проекта)
    database_url: str = ""

    # Security
    secret_key: str = Field(..., min_length=32, env="SECRET_KEY", description="Secret key for JWT tokens (min 32 chars)")
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30

    # Server
    admin_panel_host: str = "0.0.0.0"
    admin_panel_port: int = 8001

    # Redis (опционально)
    redis_url: str = "redis://localhost:6379/1"

    # CORS
    cors_origins: List[str] = ["https://srazuum.ru"]

    class Config:
        env_file = PROJECT_ROOT / ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False
        extra = "ignore"  # Игнорируем лишние поля из .env основного проекта

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Если database_url не задан, читаем из .env
        if not self.database_url:
            env_file = PROJECT_ROOT / ".env"
            if env_file.exists():
                try:
                    with open(env_file, "r") as f:
                        for line in f:
                            line = line.strip()
                            if line.startswith("DATABASE_URL="):
                                self.database_url = line.split("=", 1)[1].strip().strip('"').strip("'")
                                break
                except Exception:
                    pass


settings = Settings()
