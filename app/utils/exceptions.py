"""Кастомные исключения для приложения."""
from typing import Optional


class CrosspostingError(Exception):
    """Базовое исключение для кросспостинга."""
    pass


class APIError(CrosspostingError):
    """Ошибка API."""
    def __init__(self, message: str, status_code: Optional[int] = None, response: Optional[dict] = None):
        super().__init__(message)
        self.status_code = status_code
        self.response = response


class DatabaseError(CrosspostingError):
    """Ошибка базы данных."""
    pass


class ValidationError(CrosspostingError):
    """Ошибка валидации."""
    pass


class RateLimitError(CrosspostingError):
    """Превышен rate limit."""
    pass


class ChannelNotFoundError(CrosspostingError):
    """Канал не найден."""
    pass


class PermissionError(CrosspostingError):
    """Ошибка прав доступа."""
    pass


class MediaProcessingError(CrosspostingError):
    """Ошибка обработки медиа."""
    pass



