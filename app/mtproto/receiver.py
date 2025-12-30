"""MTProto Receiver - получение сообщений из Telegram каналов."""
import asyncio
from pyrogram import Client, filters
from pyrogram.handlers import MessageHandler
from config.settings import settings
from app.utils.logger import setup_logging, get_logger
from app.core.message_processor import MessageProcessor

logger = get_logger(__name__)
setup_logging()


class MTProtoReceiver:
    """Класс для получения сообщений из Telegram каналов через MTProto."""
    
    def __init__(self):
        self.client = None
        self.message_processor = None
        self._running = False
    
    async def start(self, session_string: str = None):
        """
        Запуск MTProto Receiver.
        
        Args:
            session_string: Session string для авторизации (опционально)
        """
        logger.info("Запуск MTProto Receiver...")
        
        try:
            # Создаем клиент
            # Если передан session string, используем его
            if session_string:
                logger.info("Использование session string для авторизации")
                self.client = Client(
                    "crossposting_session",
                    api_id=settings.telegram_api_id_int,
                    api_hash=settings.telegram_api_hash,
                    session_string=session_string
                )
            else:
                # Иначе используем phone_number для интерактивной авторизации
                self.client = Client(
                    "crossposting_session",
                    api_id=settings.telegram_api_id_int,
                    api_hash=settings.telegram_api_hash,
                    phone_number=settings.telegram_phone
                )
            
            # Запускаем клиент
            await self.client.start()
            
            # Получаем информацию о себе
            me = await self.client.get_me()
            logger.info(f"Авторизован как: {me.first_name} (@{me.username or 'нет'})")
            
            # Инициализируем обработчик сообщений
            self.message_processor = MessageProcessor()
            
            # Добавляем обработчик сообщений из каналов
            self.client.add_handler(
                MessageHandler(
                    self._handle_message,
                    filters.channel
                )
            )
            
            self._running = True
            logger.info("MTProto Receiver запущен и готов к работе")
            
        except Exception as e:
            logger.error(f"Ошибка при запуске MTProto Receiver: {e}")
            raise
    
    async def _handle_message(self, client, message):
        """Обработка входящего сообщения из канала."""
        if not self._running:
            return
        
        try:
            # Пропускаем только полностью пустые сообщения (без текста, caption и медиа)
            if not message.text and not message.caption and not (message.photo or message.video or message.document or message.audio or message.voice or message.sticker):
                logger.debug(f"Пропущено служебное сообщение из канала {message.chat.id}")
                return
            
            logger.info(f"Получено сообщение из канала {message.chat.title} (ID: {message.chat.id})")
            
            # Обрабатываем сообщение с передачей клиента для загрузки медиа
            await self.message_processor.process_telegram_message(message, self.client)
            
        except Exception as e:
            logger.error(f"Ошибка при обработке сообщения: {e}")
    
    async def stop(self):
        """Остановка MTProto Receiver."""
        logger.info("Остановка MTProto Receiver...")
        self._running = False
        
        if self.client:
            try:
                await self.client.stop()
                logger.info("MTProto Receiver остановлен")
            except Exception as e:
                logger.warning(f"Ошибка при остановке клиента: {e}")
    
    async def run(self):
        """Запуск и работа в бесконечном цикле."""
        await self.start()
        
        try:
            # Держим соединение активным
            await asyncio.Event().wait()
        except KeyboardInterrupt:
            logger.info("Получен сигнал остановки")
        finally:
            await self.stop()
