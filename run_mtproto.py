"""Точка входа для запуска MTProto Receiver."""
import asyncio
import sys
from pathlib import Path

# Добавляем корень проекта в путь
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.mtproto.receiver import MTProtoReceiver
from app.utils.logger import setup_logging, get_logger

logger = get_logger(__name__)


async def main():
    """Главная функция запуска MTProto Receiver."""
    setup_logging()
    
    receiver = MTProtoReceiver()
    
    try:
        await receiver.run()
    except KeyboardInterrupt:
        logger.info("Получен сигнал остановки")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")
        raise
    finally:
        await receiver.stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)



