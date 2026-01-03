"""Главный файл для запуска Telegram бота."""

import asyncio
import sys
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from config.settings import settings
from app.utils.logger import setup_logging, get_logger
from app.bot.handlers import router, set_bot_instance
from app.bot.handlers_payments import router as payments_router

# Импортируем handlers_migration для регистрации обработчиков
import app.bot.handlers_migration

logger = get_logger(__name__)

# Глобальный экземпляр бота
bot_instance: Bot = None
bot_id: int = None


async def main():
    """Главная функция запуска бота."""
    global bot_instance, bot_id

    setup_logging()

    # Создание единого экземпляра бота
    bot_instance = Bot(token=settings.telegram_bot_token)

    # Получаем bot_id один раз при старте
    try:
        me = await bot_instance.get_me()
        bot_id = me.id
        logger.info("bot_info", bot_id=bot_id, username=me.username)
    except Exception as e:
        logger.error("failed_to_get_bot_info", error=str(e))
        raise

    # Устанавливаем экземпляр бота в handlers
    set_bot_instance(bot_instance, bot_id)

    dp = Dispatcher(storage=MemoryStorage())

    # Регистрация роутеров
    # Обработчики миграции уже зарегистрированы в том же router через импорт
    dp.include_router(router)
    dp.include_router(payments_router)
    
    # Запускаем фоновые задачи для подписок
    from app.payments.subscription_tasks import subscription_tasks_worker
    asyncio.create_task(subscription_tasks_worker(interval_seconds=300, bot_instance=bot_instance))
    
    logger.info("bot_starting", bot_token=settings.telegram_bot_token[:10] + "...")

    try:
        # Запуск polling
        await dp.start_polling(bot_instance)
    except KeyboardInterrupt:
        logger.info("bot_stopped")
    finally:
        await bot_instance.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
