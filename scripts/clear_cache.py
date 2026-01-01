"""Скрипт для очистки кэша Redis."""
import asyncio
import sys
from pathlib import Path

# Добавляем корневую директорию проекта в путь
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from config.redis_client import get_redis, close_redis
from app.utils.logger import setup_logging, get_logger

setup_logging()
logger = get_logger(__name__)


async def clear_all_cache():
    """Очистить весь кэш Redis."""
    try:
        redis = await get_redis()
        
        logger.info("Начало очистки кэша Redis...")
        
        # Получаем все ключи
        keys = []
        async for key in redis.scan_iter("*"):
            keys.append(key)
        
        if keys:
            # Удаляем все ключи
            deleted = await redis.delete(*keys)
            logger.info(f"✅ Удалено {deleted} ключей из кэша")
        else:
            logger.info("✅ Кэш уже пуст")
        
        # Альтернативный способ - FLUSHDB (очищает текущую БД)
        # await redis.flushdb()
        # logger.info("✅ Кэш очищен через FLUSHDB")
        
        logger.info("✅ Кэш Redis полностью очищен")
        
    except Exception as e:
        logger.error(f"❌ Ошибка при очистке кэша: {e}")
        raise
    finally:
        await close_redis()


async def main():
    """Главная функция."""
    print("=" * 60)
    print("ОЧИСТКА КЭША REDIS")
    print("=" * 60)
    print("\n⚠️  ВНИМАНИЕ: Все данные кэша будут удалены!")
    print("=" * 60)
    
    try:
        await clear_all_cache()
        print("\n✅ Кэш Redis успешно очищен!")
    except Exception as e:
        print(f"\n❌ Ошибка при очистке кэша: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())

