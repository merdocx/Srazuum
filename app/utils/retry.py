"""Утилиты для повторных попыток."""
import asyncio
import random
from typing import Callable, TypeVar, Any
from config.settings import settings
from app.utils.logger import get_logger

T = TypeVar('T')
logger = get_logger(__name__)


async def retry_with_backoff(
    func: Callable[..., T],
    *args,
    max_attempts: int = None,
    base_delay: int = None,
    max_delay: int = None,
    **kwargs
) -> T:
    """
    Повторная попытка выполнения функции с exponential backoff.
    
    Args:
        func: Функция для выполнения
        *args: Аргументы функции
        max_attempts: Максимальное количество попыток
        base_delay: Базовая задержка в секундах
        max_delay: Максимальная задержка в секундах
        **kwargs: Дополнительные аргументы функции
    
    Returns:
        Результат выполнения функции
    
    Raises:
        Последнее исключение после всех попыток
    """
    max_attempts = max_attempts or settings.max_retry_attempts
    base_delay = base_delay or settings.retry_base_delay
    max_delay = max_delay or settings.retry_max_delay
    
    last_exception = None
    
    for attempt in range(1, max_attempts + 1):
        try:
            if asyncio.iscoroutinefunction(func):
                return await func(*args, **kwargs)
            else:
                return func(*args, **kwargs)
        except Exception as e:
            last_exception = e
            if attempt < max_attempts:
                # Exponential backoff with jitter
                delay = min(base_delay * (2 ** (attempt - 1)) + random.uniform(0, 1), max_delay)
                logger.warning(
                    "retry_attempt",
                    attempt=attempt,
                    max_attempts=max_attempts,
                    delay=delay,
                    error=str(e)
                )
                await asyncio.sleep(delay)
            else:
                logger.error(
                    "retry_exhausted",
                    attempts=max_attempts,
                    error=str(e)
                )
    
    raise last_exception





