"""Утилиты для работы с кэшем Redis."""

from typing import Optional, Any
import json
from config.redis_client import get_redis
from config.settings import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def get_cache(key: str) -> Optional[Any]:
    """
    Получить значение из кэша.

    Args:
        key: Ключ кэша

    Returns:
        Значение из кэша или None
    """
    try:
        redis = await get_redis()
        value = await redis.get(key)
        if value:
            return json.loads(value)
        return None
    except Exception as e:
        logger.error("cache_get_error", key=key, error=str(e))
        # При ошибке Redis возвращаем None, чтобы не ломать работу приложения
        return None


async def set_cache(key: str, value: Any, ttl: Optional[int] = None) -> None:
    """
    Установить значение в кэш.

    Args:
        key: Ключ кэша
        value: Значение для кэширования
        ttl: Время жизни в секундах (по умолчанию из настроек)
    """
    try:
        redis = await get_redis()
        ttl = ttl or settings.redis_cache_ttl
        await redis.setex(key, ttl, json.dumps(value, default=str))
    except Exception as e:
        logger.error("cache_set_error", key=key, error=str(e))
        # При ошибке Redis просто логируем, не прерываем работу


async def delete_cache(key: str) -> None:
    """
    Удалить значение из кэша.

    Args:
        key: Ключ кэша
    """
    try:
        redis = await get_redis()
        await redis.delete(key)
    except Exception as e:
        logger.error("cache_delete_error", key=key, error=str(e))


def get_channel_cache_key(channel_id: int) -> str:
    """Получить ключ кэша для канала."""
    return f"channel:{channel_id}"


def get_links_cache_key(user_id: int) -> str:
    """Получить ключ кэша для связей пользователя."""
    return f"user_links:{user_id}"


def get_active_links_cache_key() -> str:
    """Получить ключ кэша для активных связей."""
    return "active_links"
