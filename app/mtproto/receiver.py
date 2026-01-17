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
        self.session_keepalive_task = None
        self._running = False
        self._message_count = 0
        self._last_session_update = None

    async def start(self, session_string: str = None):
        """
        Запуск MTProto Receiver.

        Args:
            session_string: Session string для авторизации (опционально)
        """
        logger.info("Запуск MTProto Receiver...")

        try:
            from pathlib import Path

            # Путь к файлу сессии (ищем в app/mtproto/ и в корне проекта)
            project_root = Path(__file__).parent.parent.parent
            session_file_mtproto = project_root / "app" / "mtproto" / "crossposting_session.session"
            session_file_root = project_root / "crossposting_session.session"
            session_file = session_file_mtproto if session_file_mtproto.exists() else session_file_root
            session_string_file = project_root / "session_string.txt"

            # Создаем клиент
            # Приоритет: 1) переданный session_string, 2) файл session_string.txt, 3) файл сессии, 4) phone_number
            if session_string:
                logger.info("Использование переданного session string для авторизации")
                self.client = Client(
                    "crossposting_session",
                    api_id=settings.telegram_api_id_int,
                    api_hash=settings.telegram_api_hash,
                    session_string=session_string,
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
                        session_string=file_session_string,
                    )
                else:
                    logger.warning("Файл session_string.txt пуст, используем файл сессии")
                    self.client = Client(
                        "crossposting_session", api_id=settings.telegram_api_id_int, api_hash=settings.telegram_api_hash
                    )
            elif session_file.exists():
                # Используем существующий файл сессии (без phone_number)
                logger.info(f"Использование существующего файла сессии: {session_file}")
                self.client = Client(
                    "crossposting_session", api_id=settings.telegram_api_id_int, api_hash=settings.telegram_api_hash
                )
            else:
                # Файла сессии нет, используем phone_number для интерактивной авторизации
                logger.warning("Файл сессии не найден, требуется интерактивная авторизация")
                self.client = Client(
                    "crossposting_session",
                    api_id=settings.telegram_api_id_int,
                    api_hash=settings.telegram_api_hash,
                    phone_number=settings.telegram_phone,
                )

            # Запускаем клиент
            await self.client.start()

            # Получаем информацию о себе
            me = await self.client.get_me()
            logger.info(f"Авторизован как: {me.first_name} (@{me.username or 'нет'})")

            # Автоматически обновляем session_string после успешного подключения
            await self._update_session_string()
            import time

            self._last_session_update = time.time()

            # Инициализируем обработчик сообщений
            self.message_processor = MessageProcessor()

            # Запускаем периодическую очистку медиа-файлов
            from app.utils.media_cleanup import periodic_media_cleanup

            self.cleanup_task = asyncio.create_task(periodic_media_cleanup())

            # Запускаем периодический экспорт метрик
            if settings.enable_metrics:
                from app.utils.metrics import metrics_collector

                self.metrics_task = asyncio.create_task(self._periodic_metrics_export())

            # Запускаем периодическую проверку и обновление сессии (keep-alive)
            self.session_keepalive_task = asyncio.create_task(self._session_keepalive())

            # Добавляем обработчик сообщений из каналов
            self.client.add_handler(MessageHandler(self._handle_message, filters.channel))

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
            # ВАЖНО: Добавляем message.animation и message.video_note для поддержки GIF и кружочков
            if (
                not message.text
                and not message.caption
                and not (
                    message.photo
                    or message.video
                    or message.document
                    or message.audio
                    or message.voice
                    or message.sticker
                    or message.animation
                    or message.video_note
                )
            ):
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
                has_video=bool(message.video),
            )

            # Обрабатываем сообщение с передачей клиента для загрузки медиа
            await self.message_processor.process_telegram_message(message, self.client)

            # Периодически обновляем session_string (каждые 50 сообщений или каждые 30 минут)
            self._message_count += 1
            import time

            current_time = time.time()
            should_update = self._message_count % 50 == 0 or (  # Каждые 50 сообщений
                self._last_session_update is None or current_time - self._last_session_update > 1800
            )  # Или каждые 30 минут

            if should_update and self.client and self.client.is_connected:
                try:
                    await self._update_session_string()
                    self._last_session_update = current_time
                except Exception as update_error:
                    logger.warning(f"Не удалось обновить session_string при обработке сообщения: {update_error}")

        except Exception as e:
            # Проверяем, не связана ли ошибка с истекшей сессией
            error_str = str(e).lower()
            if any(keyword in error_str for keyword in ["session", "auth", "unauthorized", "401", "403"]):
                logger.error(f"Возможная проблема с сессией при обработке сообщения: {e}")
                # Пытаемся переподключиться в фоне
                asyncio.create_task(self._reconnect_session())
            logger.error(
                "Ошибка при обработке сообщения",
                error=str(e),
                channel_id=message.chat.id if message.chat else None,
                message_id=message.id,
                exc_info=True,
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

        # Останавливаем задачу keep-alive сессии
        if self.session_keepalive_task:
            try:
                self.session_keepalive_task.cancel()
                await self.session_keepalive_task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.warning(f"Ошибка при остановке задачи keep-alive: {e}")

        if self.client:
            try:
                await self.client.stop()
                logger.info("MTProto Receiver остановлен")
            except Exception as e:
                logger.warning(f"Ошибка при остановке клиента: {e}")

    async def _update_session_string(self):
        """
        Обновляет session_string после успешного подключения.
        Это предотвращает истечение сессии.
        """
        try:
            if not self.client:
                logger.debug("Клиент не инициализирован, пропускаем обновление session_string")
                return

            # Проверяем подключение
            if not hasattr(self.client, "is_connected") or not self.client.is_connected:
                logger.debug("Клиент не подключен, пропускаем обновление session_string")
                return

            # Экспортируем актуальный session_string
            session_string = await self.client.export_session_string()

            if not session_string:
                logger.warning("Получен пустой session_string, пропускаем сохранение")
                return

            # Сохраняем в файл для будущих запусков
            from pathlib import Path

            project_root = Path(__file__).parent.parent.parent
            session_string_file = project_root / "session_string.txt"

            # Создаем резервную копию перед обновлением
            if session_string_file.exists():
                backup_file = project_root / "session_string.txt.backup"
                try:
                    import shutil

                    shutil.copy2(session_string_file, backup_file)
                except Exception:
                    pass  # Игнорируем ошибки резервного копирования

            # Сохраняем новый session_string
            with open(session_string_file, "w") as f:
                f.write(session_string)

            logger.debug("Session string обновлен и сохранен")

        except Exception as e:
            logger.warning(f"Не удалось обновить session string: {e}", exc_info=True)

    async def _session_keepalive(self):
        """
        Периодическая проверка и обновление сессии для предотвращения истечения.
        Выполняет keep-alive запросы и обновляет session_string.
        """
        # Интервал проверки: каждые 1 час (для большей надежности)
        # Сессии обычно истекают через 7 дней бездействия, но лучше обновлять чаще
        keepalive_interval = 60 * 60  # 1 час

        while self._running:
            try:
                await asyncio.sleep(keepalive_interval)

                if not self._running:
                    break

                if not self.client or not self.client.is_connected:
                    logger.warning("Клиент не подключен, пропускаем keep-alive")
                    continue

                # Выполняем простой запрос для поддержания активности
                try:
                    me = await self.client.get_me()
                    logger.debug(f"Keep-alive: сессия активна (пользователь: {me.first_name})")

                    # Обновляем session_string
                    await self._update_session_string()
                    import time

                    self._last_session_update = time.time()

                except Exception as e:
                    error_str = str(e).lower()
                    logger.error(f"Ошибка при проверке сессии: {e}", exc_info=True)

                    # Если сессия истекла или есть проблемы с авторизацией, пытаемся переподключиться
                    if any(keyword in error_str for keyword in ["session", "auth", "unauthorized", "401", "403", "expired"]):
                        logger.warning("Обнаружена проблема с сессией, пытаемся переподключиться...")
                        try:
                            await self._reconnect_session()
                        except Exception as reconnect_error:
                            logger.error(f"Не удалось переподключиться: {reconnect_error}")
                    else:
                        # Другие ошибки - просто логируем
                        logger.warning(f"Временная ошибка при проверке сессии, продолжим работу")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Ошибка в keep-alive цикле: {e}", exc_info=True)
                await asyncio.sleep(300)  # Пауза 5 минут при ошибке

    async def _reconnect_session(self):
        """
        Переподключение при истечении сессии.
        Пытается использовать сохраненный session_string или файл сессии.
        """
        logger.info("Попытка переподключения сессии...")

        try:
            from pathlib import Path

            project_root = Path(__file__).parent.parent.parent
            session_string_file = project_root / "session_string.txt"
            session_file_mtproto = project_root / "app" / "mtproto" / "crossposting_session.session"
            session_file_root = project_root / "crossposting_session.session"
            session_file = session_file_mtproto if session_file_mtproto.exists() else session_file_root

            # Останавливаем текущий клиент
            if self.client:
                try:
                    if hasattr(self.client, "is_connected") and self.client.is_connected:
                        await self.client.stop()
                except Exception as stop_error:
                    logger.debug(f"Ошибка при остановке клиента: {stop_error}")

            # Пытаемся переподключиться с session_string (приоритет)
            if session_string_file.exists():
                try:
                    with open(session_string_file, "r") as f:
                        session_string = f.read().strip()
                    if session_string:
                        logger.info("Переподключение с использованием session_string")
                        self.client = Client(
                            "crossposting_session",
                            api_id=settings.telegram_api_id_int,
                            api_hash=settings.telegram_api_hash,
                            session_string=session_string,
                        )
                        await self.client.start()
                        await self._update_session_string()
                        # Восстанавливаем обработчики сообщений
                        self.client.add_handler(MessageHandler(self._handle_message, filters.channel))
                        logger.info("Переподключение успешно, обработчики восстановлены")
                        return
                except Exception as reconnect_error:
                    logger.warning(f"Не удалось переподключиться с session_string: {reconnect_error}")
                    # Пробуем следующий метод

            # Пытаемся переподключиться с файлом сессии
            if session_file.exists():
                try:
                    logger.info("Переподключение с использованием файла сессии")
                    self.client = Client(
                        "crossposting_session", api_id=settings.telegram_api_id_int, api_hash=settings.telegram_api_hash
                    )
                    await self.client.start()
                    await self._update_session_string()
                    # Восстанавливаем обработчики сообщений
                    self.client.add_handler(MessageHandler(self._handle_message, filters.channel))
                    logger.info("Переподключение успешно, обработчики восстановлены")
                    return
                except Exception as reconnect_error:
                    logger.warning(f"Не удалось переподключиться с файлом сессии: {reconnect_error}")

            logger.error("Не удалось переподключиться: нет доступных валидных сессий")
            # Не поднимаем исключение, чтобы сервис продолжал работать

        except Exception as e:
            logger.error(f"Критическая ошибка при переподключении: {e}", exc_info=True)
            # Не поднимаем исключение, чтобы сервис продолжал работать

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
        """
        Запуск и работа в бесконечном цикле с автоматическим восстановлением.
        """
        max_reconnect_attempts = 5
        reconnect_delay = 60  # секунды

        while True:
            try:
                await self.start()

                try:
                    # Держим соединение активным
                    await asyncio.Event().wait()
                except KeyboardInterrupt:
                    logger.info("Получен сигнал остановки")
                    break
                except Exception as e:
                    logger.error(f"Ошибка в основном цикле: {e}", exc_info=True)
                    # Если произошла ошибка, пытаемся переподключиться
                    await self.stop()
                    await asyncio.sleep(reconnect_delay)
                    continue

            except Exception as e:
                logger.error(f"Критическая ошибка при запуске: {e}", exc_info=True)
                max_reconnect_attempts -= 1

                if max_reconnect_attempts <= 0:
                    logger.error("Превышено максимальное количество попыток переподключения")
                    break

                logger.info(f"Попытка переподключения через {reconnect_delay} секунд...")
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2, 600)  # Увеличиваем задержку до максимум 10 минут
            finally:
                await self.stop()
                break
