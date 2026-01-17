"""Настройка Redis клиента."""
import redis.asyncio as aioredis
from typing import Optional
from config.settings import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

redis_client: Optional[aioredis.Redis] = None


async def init_redis() -> None:
    """Инициализация Redis клиента."""
    global redis_client
    try:
        redis_client = await aioredis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True
        )
        # Проверка соединения
        await redis_client.ping()
        logger.info("redis_connected", url=settings.redis_url)
    except Exception as e:
        logger.error("redis_connection_error", error=str(e))
        raise


async def close_redis() -> None:
    """Закрытие соединения с Redis."""
    global redis_client
    if redis_client:
        try:
            await redis_client.close()
            logger.info("redis_disconnected")
        except Exception as e:
            logger.warning("redis_close_error", error=str(e))
        finally:
            redis_client = None


async def get_redis() -> aioredis.Redis:
    """
    Получить Redis клиент.
    
    Returns:
        Redis клиент
    
    Raises:
        RuntimeError: Если Redis не инициализирован
    """
    if redis_client is None:
        await init_redis()
    
    # Проверка здоровья соединения
    try:
        await redis_client.ping()
    except Exception as e:
        logger.warning("redis_health_check_failed", error=str(e))
        # Попытка переподключения
        await init_redis()
    
    return redis_client


async def health_check() -> bool:
    """
    Проверка здоровья Redis.
    
    Returns:
        True если Redis доступен, False в противном случае
    """
    try:
        if redis_client is None:
            return False
        await redis_client.ping()
        return True
    except Exception:
        return False

