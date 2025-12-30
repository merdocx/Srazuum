"""Точка входа для MTProto Receiver."""
import asyncio
import signal
from app.mtproto.receiver import MTProtoReceiver
from app.utils.logger import setup_logging, get_logger

setup_logging()
logger = get_logger(__name__)


def main():
    """Главная функция для запуска MTProto Receiver."""
    receiver = MTProtoReceiver()
    
    try:
        # Запускаем receiver
        asyncio.run(receiver.run())
    except KeyboardInterrupt:
        logger.info("Получен KeyboardInterrupt")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")
        raise


if __name__ == "__main__":
    main()
