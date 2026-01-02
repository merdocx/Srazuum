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
    database_pool_size: int = 20  # Увеличено для production
    database_max_overflow: int = 40  # Увеличено для production
    
    # Redis
    redis_url: str = "redis://localhost:6379/0"
    redis_cache_ttl: int = 600  # 10 minutes
    
    # Application
    log_level: str = "INFO"
    environment: str = "development"
    
    # Retry settings
    max_retry_attempts: int = 5  # Увеличено для production
    retry_base_delay: int = 1  # seconds
    retry_max_delay: int = 60  # seconds
    retry_exponential_base: float = 2.0  # База для exponential backoff
    
    # Media storage
    media_storage_path: str = "media/temp"  # Относительный путь
    media_public_url: str = "http://localhost:8080/media"  # Базовый URL для доступа к медиа
    media_cleanup_after_seconds: int = 1800  # Удалять файлы через 30 минут после создания (production)
    media_max_file_size_mb: int = 300  # Увеличено для production
    media_cleanup_interval_seconds: int = 1800  # Интервал автоматической очистки (30 минут)
    
    # API timeouts
    max_api_timeout: float = 30.0  # Таймаут для MAX API запросов
    max_api_upload_timeout: float = 120.0  # Таймаут для загрузки файлов
    telegram_api_timeout: float = 60.0  # Таймаут для Telegram API
    
    # Delays (adaptive)
    media_upload_delay_photo: float = 0.5  # Задержка между загрузками фото
    media_upload_delay_video: float = 1.0  # Задержка между загрузками видео
    media_processing_delay_photo: float = 2.0  # Задержка после загрузки фото
    media_processing_delay_video: float = 3.0  # Задержка после загрузки видео
    media_group_timeout: int = 2  # Таймаут для сбора media groups
    
    # Circuit breaker
    circuit_breaker_failure_threshold: int = 5  # Количество ошибок для открытия
    circuit_breaker_recovery_timeout: int = 60  # Время восстановления (секунды)
    circuit_breaker_expected_exception: bool = True  # Ожидаемые исключения
    
    # Batch processing
    batch_size_media_uploads: int = 20  # Увеличено для лучшей производительности
    batch_size_db_updates: int = 20  # Размер батча для обновлений БД
    
    # Performance monitoring
    enable_metrics: bool = True  # Включить сбор метрик
    metrics_export_interval: int = 60  # Интервал экспорта метрик (секунды)
    
    # Миграция постов
    migration_parallel_posts: int = 10  # Параллельно обрабатывать 10 постов (увеличено для лучшей производительности)
    migration_batch_check_size: int = 1000  # Размер батча для проверки дублирования (если используется батчинг)
    migration_batch_log_size: int = 100  # Размер батча для вставок в message_log
    migration_progress_update_interval: int = 100  # Обновление прогресса каждые 100 постов
    migration_progress_update_time: int = 300  # Обновление прогресса каждые 5 минут (секунды)
    migration_streaming_enabled: bool = True  # Использовать потоковую обработку истории
    
    # Кросспостинг
    crossposting_parallel_links: int = 20  # Параллельно обрабатывать 20 связей для кросспостинга
    
    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()

