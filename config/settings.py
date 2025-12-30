"""Конфигурация приложения."""
try:
    from pydantic_settings import BaseSettings
except ImportError:
    from pydantic import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    """Настройки приложения."""
    
    # Telegram
    telegram_bot_token: str
    telegram_api_id: str  # Будет преобразован в int при необходимости
    telegram_api_hash: str
    telegram_phone: str
    
    @property
    def telegram_api_id_int(self) -> int:
        """Получить API ID как integer."""
        return int(self.telegram_api_id)
    
    # MAX
    max_bot_token: str
    max_api_base_url: str = "https://platform-api.max.ru"
    
    # Database
    database_url: str
    database_pool_size: int = 10
    database_max_overflow: int = 20
    
    # Redis
    redis_url: str = "redis://localhost:6379/0"
    redis_cache_ttl: int = 600  # 10 minutes
    
    # Application
    log_level: str = "INFO"
    environment: str = "development"
    
    # Retry settings
    max_retry_attempts: int = 3
    retry_base_delay: int = 1  # seconds
    retry_max_delay: int = 60  # seconds
    
    # Media storage
    media_storage_path: str = "/root/crossposting_service/media/temp"
    media_public_url: str = "http://localhost:8080/media"  # Базовый URL для доступа к медиа
    media_cleanup_after_seconds: int = 3600  # Удалять файлы через 1 час после создания
    media_max_file_size_mb: int = 50  # Максимальный размер файла в MB
    
    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()

