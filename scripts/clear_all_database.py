"""Скрипт для полной очистки базы данных."""
import asyncio
import sys
from pathlib import Path

# Добавляем корневую директорию проекта в путь
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import text
from config.database import async_session_maker
from app.utils.logger import setup_logging, get_logger

setup_logging()
logger = get_logger(__name__)


async def clear_all_tables():
    """Очистить все таблицы базы данных."""
    async with async_session_maker() as session:
        try:
            # Порядок удаления важен из-за внешних ключей
            tables_to_clear = [
                "messages_log",
                "failed_messages",
                "audit_log",
                "crossposting_links",
                "telegram_channels",
                "max_channels",
                "users",
            ]
            
            logger.info("Начало очистки базы данных...")
            
            for table in tables_to_clear:
                try:
                    # Отключаем проверку внешних ключей для безопасного удаления
                    await session.execute(text(f"TRUNCATE TABLE {table} CASCADE"))
                    logger.info(f"✅ Таблица {table} очищена")
                except Exception as e:
                    logger.error(f"❌ Ошибка при очистке таблицы {table}: {e}")
                    # Пробуем DELETE если TRUNCATE не работает
                    try:
                        await session.execute(text(f"DELETE FROM {table}"))
                        logger.info(f"✅ Таблица {table} очищена (через DELETE)")
                    except Exception as e2:
                        logger.error(f"❌ Критическая ошибка при очистке {table}: {e2}")
            
            await session.commit()
            logger.info("✅ База данных полностью очищена")
            
            # Проверяем результат
            for table in tables_to_clear:
                result = await session.execute(text(f"SELECT COUNT(*) FROM {table}"))
                count = result.scalar()
                if count > 0:
                    logger.warning(f"⚠️  В таблице {table} осталось {count} записей")
                else:
                    logger.info(f"✅ Таблица {table} пуста")
            
        except Exception as e:
            await session.rollback()
            logger.error(f"❌ Критическая ошибка при очистке базы данных: {e}")
            raise


async def main():
    """Главная функция."""
    print("=" * 60)
    print("ОЧИСТКА БАЗЫ ДАННЫХ")
    print("=" * 60)
    print("\n⚠️  ВНИМАНИЕ: Все данные будут удалены!")
    print("   Таблицы, которые будут очищены:")
    print("   - messages_log")
    print("   - failed_messages")
    print("   - audit_log")
    print("   - crossposting_links")
    print("   - telegram_channels")
    print("   - max_channels")
    print("   - users")
    print("\n   Таблица alembic_version (миграции) НЕ будет затронута.")
    print("=" * 60)
    
    # Запрашиваем подтверждение
    confirm = input("\nПродолжить? (yes/no): ").strip().lower()
    if confirm not in ['yes', 'y', 'да', 'д']:
        print("❌ Очистка отменена")
        return
    
    try:
        await clear_all_tables()
        print("\n✅ База данных успешно очищена!")
    except Exception as e:
        print(f"\n❌ Ошибка при очистке базы данных: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())

