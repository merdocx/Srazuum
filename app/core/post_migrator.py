"""Модуль для переноса старых постов из Telegram в MAX."""
from typing import Dict, Any, List, Optional, Callable, Set
from datetime import datetime
from collections import defaultdict
import asyncio
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from pyrogram import Client
from pyrogram.types import Message as PyrogramMessage

from app.models.crossposting_link import CrosspostingLink
from app.models.message_log import MessageLog
from app.models.telegram_channel import TelegramChannel
from app.core.message_processor import MessageProcessor
from app.core.migration_queue import migration_queue
from app.utils.logger import get_logger
from app.utils.enums import MessageStatus
from config.database import async_session_maker
from config.settings import settings

logger = get_logger(__name__)


class PostMigrator:
    """Класс для переноса старых постов из Telegram в MAX."""
    
    def __init__(self, pyrogram_client: Client, message_processor: MessageProcessor):
        """
        Инициализация мигратора.
        
        Args:
            pyrogram_client: Pyrogram клиент для получения истории
            message_processor: Процессор сообщений для отправки в MAX
        """
        self.pyrogram_client = pyrogram_client
        self.message_processor = message_processor
        self.semaphore = asyncio.Semaphore(settings.migration_parallel_posts)
        self.max_retry_attempts = 1  # 1 попытка без ретраев
    
    async def migrate_link_posts(
        self,
        link_id: int,
        progress_callback: Optional[Callable[[int, int, int, int], None]] = None
    ) -> Dict[str, Any]:
        """
        Перенести все старые посты для связи.
        
        Args:
            link_id: ID связи для миграции
            progress_callback: Функция для обновления прогресса (processed, success, skipped, failed)
        
        Returns:
            Словарь со статистикой миграции
        """
        start_time = datetime.utcnow()
        stats = {
            "total": 0,
            "success": 0,
            "skipped": 0,
            "failed": 0
        }
        
        try:
            # Получаем информацию о связи
            async with async_session_maker() as session:
                result = await session.execute(
                    select(CrosspostingLink)
                    .options(
                        selectinload(CrosspostingLink.telegram_channel),
                        selectinload(CrosspostingLink.max_channel)
                    )
                    .where(CrosspostingLink.id == link_id)
                )
                link = result.scalar_one_or_none()
                
                if not link:
                    logger.error("link_not_found_for_migration", link_id=link_id)
                    return stats
                
                telegram_channel_id = link.telegram_channel.channel_id
                telegram_channel_db_id = link.telegram_channel.id
                
                logger.info(
                    "migration_link_info",
                    link_id=link_id,
                    telegram_channel_id=telegram_channel_id,
                    telegram_channel_db_id=telegram_channel_db_id
                )
                
                # Определяем идентификатор канала для Pyrogram
                chat_identifier = None
                if link.telegram_channel.channel_username:
                    chat_identifier = f"@{link.telegram_channel.channel_username}"
                else:
                    chat_identifier = telegram_channel_id
                
                logger.info(
                    "migration_started",
                    link_id=link_id,
                    telegram_channel_id=telegram_channel_id,
                    chat_identifier=chat_identifier
                )
            
            # КРИТИЧНО: Загрузить все уже перенесенные посты одним запросом в set
            async with async_session_maker() as session:
                existing_message_ids = await self._load_existing_messages_cache(link_id, session)
            logger.info("existing_messages_loaded", count=len(existing_message_ids))
            
            # Получаем историю постов потоком
            all_messages = []
            async for message in self._get_chat_history_stream(chat_identifier):
                all_messages.append(message)
            
            stats["total"] = len(all_messages)
            logger.info("chat_history_loaded", total_messages=stats["total"])
            
            if stats["total"] == 0:
                # Обработка постов из очереди
                await self._process_queued_messages(link_id)
                return stats
            
            # ОПТИМИЗАЦИЯ: Предварительная группировка медиа-групп
            grouped_messages, standalone_messages = await self._group_messages_by_media_group(all_messages)
            
            logger.info(
                "messages_grouped",
                link_id=link_id,
                total_messages=stats["total"],
                media_groups=len(grouped_messages),
                standalone_messages=len(standalone_messages)
            )
            
            # Обрабатываем медиа-группы и отдельные посты
            processed_count = 0
            last_progress_update = start_time
            
            # Обрабатываем медиа-группы
            for group in grouped_messages:
                processed_count += len(group)
                
                # Проверка на дублирование для медиа-группы
                group_ids = {msg.id for msg in group}
                if any(msg_id in existing_message_ids for msg_id in group_ids):
                    stats["skipped"] += len(group)
                    logger.debug("media_group_skipped_duplicate", group_size=len(group))
                    continue
                
                # Обработка медиа-группы
                try:
                    # Конвертируем группу в формат для MessageProcessor
                    primary_message = group[0]
                    message_data = await self._convert_message(primary_message)
                    
                    # Обрабатываем медиа-группу через MessageProcessor
                    await self.message_processor._process_media_group(
                        group,
                        client=self.pyrogram_client,
                        link_id=link_id
                    )
                    
                    # Добавляем все ID группы в кэш
                    for msg in group:
                        existing_message_ids.add(msg.id)
                    
                    stats["success"] += len(group)
                    logger.info("media_group_migrated", group_size=len(group), link_id=link_id)
                    
                except Exception as e:
                    stats["failed"] += len(group)
                    logger.error("media_group_migration_failed", error=str(e), group_size=len(group), exc_info=True)
                
                # Периодические обновления прогресса
                if progress_callback and (
                    processed_count % settings.migration_progress_update_interval == 0 or
                    (datetime.utcnow() - last_progress_update).total_seconds() >= settings.migration_progress_update_time
                ):
                    await progress_callback(processed_count, stats["success"], stats["skipped"], stats["failed"])
                    last_progress_update = datetime.utcnow()
            
            # КРИТИЧНО: Сортируем отдельные посты по дате (от старых к новым) для сохранения порядка
            standalone_messages_sorted = sorted(
                standalone_messages,
                key=lambda m: m.date if m.date else datetime.min
            )
            
            # Обрабатываем отдельные посты последовательно для сохранения порядка
            standalone_to_process = [
                msg for msg in standalone_messages_sorted
                if msg.id not in existing_message_ids
            ]
            
            logger.info(
                "processing_standalone_messages",
                link_id=link_id,
                total_standalone=len(standalone_to_process),
                telegram_channel_id=telegram_channel_id
            )
            
            logs_to_create = []
            
            # Последовательная обработка для сохранения порядка постов
            for idx, msg in enumerate(standalone_to_process, 1):
                processed_count += 1
                
                # Пропускаем пустые сообщения (без текста, caption и медиа)
                has_content = bool(msg.text or msg.caption or msg.photo or msg.video or msg.document or msg.audio or msg.voice or msg.sticker)
                
                logger.info(
                    "processing_post",
                    message_id=msg.id,
                    link_id=link_id,
                    processed=idx,
                    total=len(standalone_to_process),
                    has_text=bool(msg.text),
                    has_caption=bool(msg.caption),
                    has_photo=bool(msg.photo),
                    has_video=bool(msg.video),
                    has_content=has_content
                )
                
                # Пропускаем пустые сообщения
                if not has_content:
                    stats["skipped"] += 1
                    logger.info("post_skipped_empty", message_id=msg.id, link_id=link_id, processed=idx, total=len(standalone_to_process))
                    continue
                
                try:
                    # Обработка с semaphore для контроля параллелизма (но последовательно)
                    async with self.semaphore:
                        result = await self._process_single_post(
                            msg, link_id, telegram_channel_db_id, existing_message_ids
                        )
                    
                    if result:
                        stats["success"] += 1
                        existing_message_ids.add(msg.id)
                        # Собираем данные для батчинга вставок в message_log
                        logs_to_create.append({
                            "crossposting_link_id": link_id,
                            "telegram_channel_id": telegram_channel_db_id,
                            "telegram_message_id": msg.id,
                            "status": MessageStatus.SUCCESS.value,
                            "message_type": self._get_message_type(msg),
                            "created_at": datetime.utcnow(),
                            "sent_at": datetime.utcnow()
                        })
                        logger.info("post_migrated_success", message_id=msg.id, link_id=link_id, processed=idx, total=len(standalone_to_process))
                    else:
                        stats["skipped"] += 1
                        logger.info("post_skipped", message_id=msg.id, link_id=link_id, processed=idx, total=len(standalone_to_process))
                        
                except Exception as e:
                    stats["failed"] += 1
                    logger.error("post_migration_failed", message_id=msg.id, error=str(e), exc_info=True, processed=idx, total=len(standalone_to_process))
                    # Продолжаем обработку следующих постов даже при ошибке
                
                # Батчинг создания записей в message_log (каждые N записей)
                if len(logs_to_create) >= settings.migration_batch_log_size:
                    await self._batch_create_message_logs(logs_to_create)
                    logs_to_create = []
                
                # Периодические обновления прогресса
                if progress_callback and (
                    processed_count % settings.migration_progress_update_interval == 0 or
                    (datetime.utcnow() - last_progress_update).total_seconds() >= settings.migration_progress_update_time
                ):
                    await progress_callback(processed_count, stats["success"], stats["skipped"], stats["failed"])
                    last_progress_update = datetime.utcnow()
            
            # Обрабатываем оставшиеся логи
            if logs_to_create:
                await self._batch_create_message_logs(logs_to_create)
            
            logger.info(
                "migration_completed",
                link_id=link_id,
                total=stats["total"],
                success=stats["success"],
                skipped=stats["skipped"],
                failed=stats["failed"],
                processed=processed_count
            )
            
        except Exception as e:
            logger.error("migration_error", link_id=link_id, error=str(e), exc_info=True)
            # Устанавливаем duration даже при ошибке
            end_time = datetime.utcnow()
            stats["duration"] = (end_time - start_time).total_seconds()
        finally:
            # Остановить миграцию и обработать очередь
            await migration_queue.stop_migration(link_id)
            await self._process_queued_messages(link_id)
        
        # Убеждаемся, что duration установлен
        if "duration" not in stats:
            end_time = datetime.utcnow()
            stats["duration"] = (end_time - start_time).total_seconds()
        
        return stats
    
    async def _get_chat_history_stream(self, chat_identifier: str):
        """
        Получить историю постов потоком (async generator).
        
        Args:
            chat_identifier: Идентификатор чата (username или ID)
        
        Yields:
            Сообщения из истории (от старых к новым)
        """
        try:
            # Получаем информацию о чате для правильного ID
            chat = await self.pyrogram_client.get_chat(chat_identifier)
            chat_id = chat.id
            
            # Получаем историю потоком
            messages = []
            async for message in self.pyrogram_client.get_chat_history(chat_id, limit=None):
                messages.append(message)
            
            # Сортируем от старых к новым (по дате)
            messages.sort(key=lambda m: m.date if m.date else datetime.min)
            
            # Возвращаем от старых к новым
            for message in messages:
                yield message
                
        except Exception as e:
            logger.error("failed_to_get_chat_history", chat_identifier=chat_identifier, error=str(e))
            raise
    
    async def _load_existing_messages_cache(self, link_id: int, session: AsyncSession) -> Set[int]:
        """
        Загрузить все уже перенесенные посты одним запросом в set.
        
        КРИТИЧНО: O(1) проверка вместо запросов к БД.
        
        Args:
            link_id: ID связи
            session: Сессия БД
        
        Returns:
            Set с ID уже перенесенных сообщений
        """
        result = await session.execute(
            select(MessageLog.telegram_message_id)
            .where(MessageLog.crossposting_link_id == link_id)
            .where(MessageLog.status == MessageStatus.SUCCESS.value)
        )
        return set(result.scalars().all())
    
    async def _group_messages_by_media_group(
        self,
        messages: List[PyrogramMessage]
    ) -> tuple[List[List[PyrogramMessage]], List[PyrogramMessage]]:
        """
        Группировать сообщения по media_group_id.
        
        Args:
            messages: Список сообщений
        
        Returns:
            Tuple: (список групп, список отдельных сообщений)
        """
        groups = defaultdict(list)
        standalone = []
        
        for msg in messages:
            if hasattr(msg, 'media_group_id') and msg.media_group_id:
                groups[msg.media_group_id].append(msg)
            else:
                standalone.append(msg)
        
        # Сортируем группы по дате первого сообщения (от старых к новым)
        sorted_groups = []
        for group_id, group_messages in groups.items():
            group_messages.sort(key=lambda m: m.date if m.date else datetime.min)
            sorted_groups.append(group_messages)
        
        sorted_groups.sort(key=lambda g: min(m.date if m.date else datetime.min for m in g))
        
        return sorted_groups, standalone
    
    async def _process_single_post(
        self,
        message: PyrogramMessage,
        link_id: int,
        telegram_channel_db_id: int,
        existing_ids: Set[int]
    ) -> bool:
        """
        Обработать один пост.
        
        Args:
            message: Pyrogram сообщение
            link_id: ID связи
            telegram_channel_db_id: ID записи канала в БД (telegram_channels.id)
            existing_ids: Set уже перенесенных ID
        
        Returns:
            True если успешно, False если пропущен
        """
        # Проверка на дублирование (O(1) в памяти)
        if message.id in existing_ids:
            logger.debug("post_skipped_duplicate", message_id=message.id)
            return False
        
        try:
            # Конвертируем сообщение
            message_data = await self._convert_message(message)
            
            logger.debug(
                "calling_process_message",
                message_id=message.id,
                telegram_channel_db_id=telegram_channel_db_id,
                link_id=link_id
            )
            
            # Обрабатываем через MessageProcessor
            # ВАЖНО: передаем telegram_channel_db_id (ID записи в БД), так как process_message
            # ищет связи по CrosspostingLink.telegram_channel_id (внешний ключ на telegram_channels.id)
            success = await self.message_processor.process_message(
                telegram_channel_id=telegram_channel_db_id,
                telegram_message_id=message.id,
                message_data=message_data,
                link_id=link_id
            )
            
            if success:
                existing_ids.add(message.id)
                logger.debug("post_migrated_successfully", message_id=message.id, link_id=link_id)
                return True
            else:
                logger.warning("post_migration_failed_no_success", message_id=message.id, link_id=link_id)
                return False
                
        except Exception as e:
            logger.error("failed_to_process_single_post", message_id=message.id, error=str(e), exc_info=True)
            return False
    
    async def _convert_message(self, message: PyrogramMessage) -> Dict[str, Any]:
        """
        Конвертировать Pyrogram сообщение в формат для MessageProcessor.
        
        Args:
            message: Pyrogram сообщение
        
        Returns:
            Словарь с данными сообщения
        """
        message_data = {
            "message_id": message.id,
            "date": message.date,
            "text": message.text or "",
            "caption": message.caption or "",
            "photo": None,
            "video": None,
            "document": None,
            "media_group_id": getattr(message, 'media_group_id', None)
        }
        
        if message.photo:
            message_data["photo"] = message.photo
        elif message.video:
            message_data["video"] = message.video
        elif message.document:
            message_data["document"] = message.document
        
        # Обработка форматирования
        if message.caption_entities:
            from app.utils.text_formatter import apply_formatting
            formatted_caption, parse_mode = apply_formatting(
                message.caption or "",
                message.caption_entities
            )
            message_data["caption"] = formatted_caption
            message_data["caption_parse_mode"] = parse_mode
        
        return message_data
    
    def _get_message_type(self, message: PyrogramMessage) -> str:
        """Определить тип сообщения."""
        if message.photo:
            return "photo"
        elif message.video:
            return "video"
        elif message.document:
            return "document"
        else:
            return "text"
    
    async def _batch_create_message_logs(self, logs_data: List[Dict[str, Any]]) -> None:
        """
        Создать записи в message_log батчами.
        
        КРИТИЧНО: Батчинг вставок в БД (по 100 записей).
        
        Args:
            logs_data: Список данных для создания записей
        """
        if not logs_data:
            return
        
        async with async_session_maker() as session:
            batch_size = settings.migration_batch_log_size
            
            for i in range(0, len(logs_data), batch_size):
                batch = logs_data[i:i + batch_size]
                session.add_all([MessageLog(**log_data) for log_data in batch])
                await session.commit()
            
            logger.debug("message_logs_created_batch", count=len(logs_data))
    
    async def _process_queued_messages(self, link_id: int) -> None:
        """
        Обработать сообщения из очереди после миграции.
        
        Args:
            link_id: ID связи
        """
        queued_messages = await migration_queue.get_queued_messages(link_id)
        
        if not queued_messages:
            return
        
        logger.info("processing_queued_messages", link_id=link_id, count=len(queued_messages))
        
        # Получаем информацию о связи
        async with async_session_maker() as session:
            result = await session.execute(
                select(CrosspostingLink)
                .where(CrosspostingLink.id == link_id)
                .options(selectinload(CrosspostingLink.telegram_channel))
            )
            link = result.scalar_one_or_none()
            
            if not link:
                logger.error("link_not_found_for_queue_processing", link_id=link_id)
                return
            
            telegram_channel_db_id = link.telegram_channel.id
        
        # Обрабатываем сообщения из очереди
        for message_data in queued_messages:
            try:
                await self.message_processor.process_message(
                    telegram_channel_id=telegram_channel_db_id,
                    telegram_message_id=message_data.get("message_id"),
                    message_data=message_data,
                    link_id=link_id
                )
            except Exception as e:
                logger.error("failed_to_process_queued_message", error=str(e))
        
        # Очищаем очередь
        await migration_queue.clear_queue(link_id)
        logger.info("queued_messages_processed", link_id=link_id, count=len(queued_messages))
