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
from app.core.message_processor import MessageProcessor
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
            "skipped_empty": 0,  # Пустые сообщения
            "skipped_duplicate": 0,  # Дубликаты
            "failed": 0
        }
        
        # Приостанавливаем кросспостинг для связи на время миграции
        link_was_enabled = None
        telegram_channel_db_id = None
        telegram_channel_id = None
        chat_identifier = None
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
                
                # Приостанавливаем кросспостинг
                link_was_enabled = link.is_enabled
                if link_was_enabled:
                    link.is_enabled = False
                    await session.commit()
                    # Очищаем кэш связей для этого канала
                    from app.utils.cache import delete_cache
                    cache_key = f"channel_links:{telegram_channel_db_id}"
                    await delete_cache(cache_key)
                    logger.info("crossposting_paused_for_migration", link_id=link_id, telegram_channel_db_id=telegram_channel_db_id)
                
                logger.info(
                    "migration_link_info",
                    link_id=link_id,
                    telegram_channel_id=telegram_channel_id,
                    telegram_channel_db_id=telegram_channel_db_id
                )
                
                # Определяем идентификатор канала для Pyrogram
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
            
            # Проверяем, что chat_identifier определен
            if not chat_identifier:
                logger.error("chat_identifier_not_defined", link_id=link_id)
                return stats
            
            # Получаем историю постов потоком
            all_messages = []
            async for message in self._get_chat_history_stream(chat_identifier):
                all_messages.append(message)
            
            stats["total"] = len(all_messages)
            logger.info("chat_history_loaded", total_messages=stats["total"])
            
            if stats["total"] == 0:
                logger.info("no_messages_to_migrate", link_id=link_id)
                return stats
            
            # ОПТИМИЗАЦИЯ: Предварительная группировка медиа-групп
            grouped_messages, standalone_messages = self._group_messages_by_media_group(all_messages)
            
            logger.info(
                "messages_grouped",
                           link_id=link_id,
                total_messages=stats["total"],
                media_groups=len(grouped_messages),
                standalone_messages=len(standalone_messages)
            )
            
            # КРИТИЧНО: Объединяем медиа-группы и отдельные посты в один список для сохранения хронологического порядка
            # Создаем список элементов для обработки: каждая медиа-группа и каждый отдельный пост
            items_to_process = []
            
            # Добавляем медиа-группы (используем дату первого сообщения в группе)
            for group in grouped_messages:
                group_date = min(msg.date if msg.date else datetime.min for msg in group)
                items_to_process.append({
                    "type": "media_group",
                    "date": group_date,
                    "group": group
                })
            
            # Добавляем отдельные посты
            for msg in standalone_messages:
                items_to_process.append({
                    "type": "standalone",
                    "date": msg.date if msg.date else datetime.min,
                    "message": msg
                })
            
            # КРИТИЧНО: Сортируем все элементы по дате (от старых к новым) для сохранения порядка
            items_to_process_sorted = sorted(
                items_to_process,
                key=lambda item: item["date"]
            )
            
            logger.info(
                "items_sorted_for_migration",
                               link_id=link_id,
                total_items=len(items_to_process_sorted),
                media_groups=len(grouped_messages),
                standalone_messages=len(standalone_messages)
            )
            
            # Обрабатываем все элементы в хронологическом порядке
            processed_count = 0
            last_progress_update = start_time
            
            for item in items_to_process_sorted:
                if item["type"] == "media_group":
                    # Обработка медиа-группы
                    group = item["group"]
                    processed_count += len(group)
                    
                    # Проверка на дублирование для медиа-группы
                    group_ids = {msg.id for msg in group}
                    if any(msg_id in existing_message_ids for msg_id in group_ids):
                        stats["skipped"] += len(group)
                        logger.debug("media_group_skipped_duplicate", group_size=len(group))
                        continue
                    
                    # Обработка медиа-группы
                    try:
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
                
                elif item["type"] == "standalone":
                    # Обработка отдельного поста
                    msg = item["message"]
                    processed_count += 1
                    
                    # Пропускаем пустые сообщения (без текста, caption и медиа)
                    has_content = bool(msg.text or msg.caption or msg.photo or msg.video or msg.document or msg.audio or msg.voice or msg.sticker)
                    
                    logger.info(
                        "processing_post",
                        message_id=msg.id,
                        link_id=link_id,
                        processed=processed_count,
                        total=len(items_to_process_sorted),
                        has_text=bool(msg.text),
                        has_caption=bool(msg.caption),
                        has_photo=bool(msg.photo),
                        has_video=bool(msg.video),
                        has_content=has_content
                    )
                    
                    # Пропускаем пустые сообщения
                    if not has_content:
                        stats["skipped"] += 1
                        stats["skipped_empty"] += 1
                        logger.info("post_skipped_empty", message_id=msg.id, link_id=link_id, processed=processed_count, total=len(items_to_process_sorted))
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
                            logger.info("post_migrated_success", message_id=msg.id, link_id=link_id, processed=processed_count, total=len(items_to_process_sorted))
                        else:
                            stats["skipped"] += 1
                            stats["skipped_duplicate"] += 1
                            logger.info("post_skipped", message_id=msg.id, link_id=link_id, processed=processed_count, total=len(items_to_process_sorted))
                            
                    except Exception as e:
                        stats["failed"] += 1
                        logger.error("post_migration_failed", message_id=msg.id, error=str(e), exc_info=True, processed=processed_count, total=len(items_to_process_sorted))
                        # Продолжаем обработку следующих постов даже при ошибке
                
                # Периодические обновления прогресса
                if progress_callback and (
                    processed_count % settings.migration_progress_update_interval == 0 or
                    (datetime.utcnow() - last_progress_update).total_seconds() >= settings.migration_progress_update_time
                ):
                    await progress_callback(processed_count, stats["success"], stats["skipped"], stats["failed"])
                    last_progress_update = datetime.utcnow()
            
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
            # Восстанавливаем кросспостинг для связи (включаем обратно, если был включен до миграции)
            if link_was_enabled is not None:
                try:
                    async with async_session_maker() as session:
                        result = await session.execute(
                            select(CrosspostingLink).where(CrosspostingLink.id == link_id)
                        )
                        link = result.scalar_one_or_none()
                        if link:
                            if link_was_enabled:
                                # Включаем обратно, если был включен до миграции
                                link.is_enabled = True
                                await session.commit()
                                logger.info("link_enabled_after_migration", link_id=link_id, is_enabled=link.is_enabled)
                                
                                # ВАЖНО: Пересоздаем кэш после коммита, используя новую сессию для гарантии актуальности данных
                                # В process_message используется telegram_channel_db_id (ID записи в БД) как ключ кэша
                                if telegram_channel_db_id:
                                    from app.utils.cache import set_cache, delete_cache, get_cache
                                    cache_key = f"channel_links:{telegram_channel_db_id}"
                                    
                                    # Используем новую сессию для загрузки активных связей после коммита
                                    async with async_session_maker() as new_session:
                                        result = await new_session.execute(
                                            select(CrosspostingLink)
                                            .where(CrosspostingLink.telegram_channel_id == telegram_channel_db_id)
                                            .where(CrosspostingLink.is_enabled == True)
                                        )
                                        active_links = result.scalars().all()
                                        
                                        if active_links:
                                            link_ids = [link.id for link in active_links]
                                            # ВАЖНО: Сначала очищаем старый кэш (если есть), затем создаем новый
                                            # Это гарантирует, что кэш всегда актуален
                                            await delete_cache(cache_key)
                                            # Создаем новый кэш с актуальными данными
                                            await set_cache(cache_key, link_ids)
                                            # Проверяем, что кэш действительно создан и содержит правильные данные
                                            verify_cache = await get_cache(cache_key)
                                            logger.info(
                                                "cache_recreated_after_migration",
                                                cache_key=cache_key,
                                                link_ids=link_ids,
                                                link_id=link_id,
                                                active_links_count=len(active_links),
                                                cache_verified=verify_cache is not None,
                                                cached_link_ids=verify_cache,
                                                cache_match=verify_cache == link_ids
                                            )
                                        else:
                                            # Если активных связей нет, очищаем кэш
                                            deleted = await delete_cache(cache_key)
                                            logger.warning("cache_cleared_after_migration_no_links", cache_key=cache_key, link_id=link_id, cache_deleted=deleted)
                                
                                logger.info(
                                    "crossposting_resumed_after_migration",
                                    link_id=link_id,
                                    telegram_channel_db_id=telegram_channel_db_id,
                                    is_enabled=link.is_enabled,
                                    cache_key=cache_key,
                                    cache_ready=True
                                )
                                # ВАЖНО: Убеждаемся, что MTProto receiver продолжает работать
                                # Проверяем, что кэш действительно создан и готов к использованию
                                final_cache_check = await get_cache(cache_key)
                                if final_cache_check:
                                    logger.info(
                                        "cache_verified_after_migration",
                                        link_id=link_id,
                                        cache_key=cache_key,
                                        cached_link_ids=final_cache_check,
                                        mtproto_receiver_should_work=True
                                    )
                                else:
                                    logger.error(
                                        "cache_not_found_after_migration",
                                        link_id=link_id,
                                        cache_key=cache_key,
                                        mtproto_receiver_may_not_work=True
                                    )
                                # ВАЖНО: Перезапускаем MTProto receiver после миграции
                                # чтобы убедиться, что он продолжает получать сообщения
                                try:
                                    import subprocess
                                    result = subprocess.run(
                                        ["systemctl", "restart", "crossposting-mtproto.service"],
                                        capture_output=True,
                                        text=True,
                                        timeout=10
                                    )
                                    if result.returncode == 0:
                                        logger.info("mtproto_receiver_restarted_after_migration", link_id=link_id)
                                    else:
                                        logger.warning(
                                            "mtproto_receiver_restart_failed",
                                            link_id=link_id,
                                            error=result.stderr
                                        )
                                except Exception as e:
                                    logger.error(
                                        "failed_to_restart_mtproto_receiver",
                                        link_id=link_id,
                                        error=str(e),
                                        exc_info=True
                                    )
                            else:
                                # Оставляем отключенным, если был отключен до миграции
                                logger.info("crossposting_remains_disabled_after_migration", link_id=link_id)
                except Exception as e:
                    logger.error("failed_to_resume_crossposting_after_migration", link_id=link_id, error=str(e), exc_info=True)
            
            # Очищаем старые медиа-файлы (старше 1 часа) после завершения миграции
            try:
                from app.utils.media_handler import cleanup_old_media_files
                deleted_count = await cleanup_old_media_files(max_age_hours=1)
                if deleted_count > 0:
                    logger.info("old_media_cleaned_after_migration", deleted_count=deleted_count, link_id=link_id)
            except Exception as cleanup_error:
                logger.warning("failed_to_cleanup_old_media_after_migration", error=str(cleanup_error), link_id=link_id)
        
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
    
    def _group_messages_by_media_group(
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
            # Конвертируем сообщение с загрузкой медиа
            message_data = await self._convert_message(message, client=self.pyrogram_client)
            
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
                # Проверяем, был ли пост действительно перенесен сейчас или уже был перенесен ранее
                # Если process_message вернул True, но пост уже был в existing_ids, значит он был пропущен как дубликат
                if message.id in existing_ids:
                    # Пост уже был перенесен ранее - это дубликат, не считаем как success
                    logger.debug("post_already_migrated_duplicate", message_id=message.id, link_id=link_id)
                    return False
                else:
                    # Пост успешно перенесен сейчас
                    existing_ids.add(message.id)
                    logger.debug("post_migrated_successfully", message_id=message.id, link_id=link_id)
                    return True
            else:
                logger.warning("post_migration_failed_no_success", message_id=message.id, link_id=link_id)
                return False
                
        except Exception as e:
            logger.error("failed_to_process_single_post", message_id=message.id, error=str(e), exc_info=True)
            return False
    
    async def _convert_message(self, message: PyrogramMessage, client=None) -> Dict[str, Any]:
        """
        Конвертировать Pyrogram сообщение в формат для MessageProcessor.
        
        Args:
            message: Pyrogram сообщение
            client: Pyrogram клиент для загрузки медиа (опционально)
        
        Returns:
            Словарь с данными сообщения
        """
        from app.utils.media_handler import download_and_store_media
        
        message_data = {
            "message_id": message.id,
            "date": message.date,
            "text": message.text or "",
            "caption": message.caption or "",
            "type": "text",  # Используем строковые значения напрямую
            "photo": None,
            "video": None,
            "document": None,
            "media_group_id": getattr(message, 'media_group_id', None)
        }
        
        # Определение типа сообщения и загрузка медиа
        if message.photo:
            message_data["type"] = "photo"
            message_data["photo"] = message.photo
            # Обрабатываем форматирование caption, если есть
            if message.caption_entities:
                from app.utils.text_formatter import apply_formatting
                formatted_caption, caption_parse_mode = apply_formatting(
                    message.caption or "",
                    message.caption_entities
                )
                message_data["caption"] = formatted_caption
                message_data["caption_parse_mode"] = caption_parse_mode
            else:
                message_data["caption"] = message.caption
            
            # Скачиваем фото если есть client
            if client:
                try:
                    photo_url, local_file_path = await download_and_store_media(client, message, "photo")
                    if photo_url:
                        message_data["photo_url"] = photo_url
                        message_data["local_file_path"] = local_file_path
                    else:
                        message_data["photo_url"] = None
                except Exception as e:
                    logger.error("failed_to_download_photo_in_migration", message_id=message.id, error=str(e), exc_info=True)
                    message_data["photo_url"] = None
        elif message.video:
            message_data["type"] = "video"
            message_data["video"] = message.video
            # Обрабатываем форматирование caption, если есть
            if message.caption_entities:
                from app.utils.text_formatter import apply_formatting
                formatted_caption, caption_parse_mode = apply_formatting(
                    message.caption or "",
                    message.caption_entities
                )
                message_data["caption"] = formatted_caption
                message_data["parse_mode"] = caption_parse_mode
            else:
                message_data["caption"] = message.caption
            
            # Скачиваем видео если есть client
            if client:
                try:
                    video_url, local_file_path = await download_and_store_media(client, message, "video")
                    if video_url and local_file_path:
                        message_data["video_url"] = video_url
                        message_data["local_file_path"] = local_file_path
                    else:
                        message_data["video_url"] = None
                        message_data["local_file_path"] = None
                except Exception as e:
                    logger.error("failed_to_download_video_in_migration", message_id=message.id, error=str(e), exc_info=True)
                    message_data["video_url"] = None
                    message_data["local_file_path"] = None
        elif message.document:
            message_data["type"] = "document"
            message_data["document"] = message.document
            message_data["caption"] = message.caption
        elif message.audio:
            message_data["type"] = "audio"
            message_data["caption"] = message.caption
        elif message.voice:
            message_data["type"] = "voice"
        elif message.sticker:
            message_data["type"] = "sticker"
        
        # Обработка форматирования текста (для текстовых сообщений)
        if message.entities and not message.photo and not message.video:
            from app.utils.text_formatter import apply_formatting
            formatted_text, parse_mode = apply_formatting(
                message_data.get("text", ""),
                message.entities
            )
            message_data["text"] = formatted_text
            message_data["parse_mode"] = parse_mode
        
        return message_data

