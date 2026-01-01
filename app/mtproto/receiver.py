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
        self.cleanup_task = None
        self.metrics_task = None
        self._running = False
    
    async def start(self, session_string: str = None):
        """
        Запуск MTProto Receiver.
        
        Args:
            session_string: Session string для авторизации (опционально)
        """
        logger.info("Запуск MTProto Receiver...")
        
        try:
            from pathlib import Path
            
            # Путь к файлу сессии
            session_file = Path("crossposting_session.session")
            session_string_file = Path("session_string.txt")
            
            # Создаем клиент
            # Приоритет: 1) переданный session_string, 2) файл session_string.txt, 3) файл сессии, 4) phone_number
            if session_string:
                logger.info("Использование переданного session string для авторизации")
                self.client = Client(
                    "crossposting_session",
                    api_id=settings.telegram_api_id_int,
                    api_hash=settings.telegram_api_hash,
                    session_string=session_string
                )
            elif session_string_file.exists():
                # Читаем session string из файла
                logger.info(f"Чтение session string из файла: {session_string_file}")
                with open(session_string_file, "r") as f:
                    file_session_string = f.read().strip()
                if file_session_string:
                    logger.info("Использование session string из файла для авторизации")
                    self.client = Client(
                        "crossposting_session",
                        api_id=settings.telegram_api_id_int,
                        api_hash=settings.telegram_api_hash,
                        session_string=file_session_string
                    )
                else:
                    logger.warning("Файл session_string.txt пуст, используем файл сессии")
                    self.client = Client(
                        "crossposting_session",
                        api_id=settings.telegram_api_id_int,
                        api_hash=settings.telegram_api_hash
                    )
            elif session_file.exists():
                # Используем существующий файл сессии (без phone_number)
                logger.info(f"Использование существующего файла сессии: {session_file}")
                self.client = Client(
                    "crossposting_session",
                    api_id=settings.telegram_api_id_int,
                    api_hash=settings.telegram_api_hash
                )
            else:
                # Файла сессии нет, используем phone_number для интерактивной авторизации
                logger.warning("Файл сессии не найден, требуется интерактивная авторизация")
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
            
            # Запускаем периодическую очистку медиа-файлов
            from app.utils.media_cleanup import periodic_media_cleanup
            self.cleanup_task = asyncio.create_task(periodic_media_cleanup())
            
            # Запускаем периодический экспорт метрик
            if settings.enable_metrics:
                from app.utils.metrics import metrics_collector
                self.metrics_task = asyncio.create_task(self._periodic_metrics_export())
            
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
            
            logger.info(
                "Получено сообщение из канала",
                channel_title=message.chat.title if message.chat else None,
                channel_id=message.chat.id if message.chat else None,
                message_id=message.id,
                has_text=bool(message.text),
                has_caption=bool(message.caption),
                has_photo=bool(message.photo),
                has_video=bool(message.video)
            )
            
            # Обрабатываем сообщение с передачей клиента для загрузки медиа
            await self.message_processor.process_telegram_message(message, self.client)
            
        except Exception as e:
            logger.error(
                "Ошибка при обработке сообщения",
                error=str(e),
                channel_id=message.chat.id if message.chat else None,
                message_id=message.id,
                exc_info=True
            )
    
    async def stop(self):
        """Остановка MTProto Receiver."""
        logger.info("Остановка MTProto Receiver...")
        self._running = False
        
        # Останавливаем задачу очистки
        if self.cleanup_task:
            try:
                self.cleanup_task.cancel()
                await self.cleanup_task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.warning(f"Ошибка при остановке задачи очистки: {e}")
        
        # Останавливаем задачу экспорта метрик
        if self.metrics_task:
            try:
                self.metrics_task.cancel()
                await self.metrics_task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.warning(f"Ошибка при остановке задачи метрик: {e}")
        
        if self.client:
            try:
                await self.client.stop()
                logger.info("MTProto Receiver остановлен")
            except Exception as e:
                logger.warning(f"Ошибка при остановке клиента: {e}")
    
    async def _periodic_metrics_export(self):
        """Периодический экспорт метрик."""
        from app.utils.metrics import metrics_collector
        from config.settings import settings
        
        while self._running:
            try:
                await asyncio.sleep(settings.metrics_export_interval)
                
                if metrics_collector.enabled:
                    all_metrics = metrics_collector.get_all_metrics()
                    metrics_collector.log_summary()
                    
                    # Логируем системные метрики отдельно
                    if all_metrics.get("system"):
                        logger.info("system_metrics", **all_metrics["system"])
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("metrics_export_error", error=str(e))
                await asyncio.sleep(60)  # Короткая пауза при ошибке
    
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
