"""Обработчик сообщений для кросспостинга."""
from typing import Optional, Dict, Any, List
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
import httpx

from app.models.crossposting_link import CrosspostingLink
from app.models.message_log import MessageLog
from app.models.failed_message import FailedMessage
from app.max_api.client import MaxAPIClient
from app.utils.logger import get_logger
from app.utils.cache import get_cache, set_cache, delete_cache
from app.utils.enums import MessageStatus, MessageType
from app.utils.exceptions import APIError, DatabaseError
from app.utils.rate_limiter import max_api_limiter
from config.database import async_session_maker
from config.settings import settings

logger = get_logger(__name__)


class MessageProcessor:
    """Обработчик сообщений для кросспостинга."""
    
    def __init__(self):
        self.max_client = MaxAPIClient()
        from app.core.media_group_handler import MediaGroupHandler
        self.media_group_handler = MediaGroupHandler(timeout_seconds=2)
    
    async def process_message(
        self,
        telegram_channel_id: int,
        telegram_message_id: int,
        message_data: Dict[str, Any]
    ) -> bool:
        """
        Обработать сообщение из Telegram и отправить в MAX.
        
        Args:
            telegram_channel_id: ID Telegram канала
            telegram_message_id: ID сообщения в Telegram
            message_data: Данные сообщения
        
        Returns:
            True если успешно, False в противном случае
        """
        start_time = datetime.utcnow()
        
        # Используем одну транзакцию для всего процесса
        async with async_session_maker() as session:
            async with session.begin():
                try:
                    # Получаем активные связи с eager loading для оптимизации
                    cache_key = f"channel_links:{telegram_channel_id}"
                    cached_data = await get_cache(cache_key)
                    
                    if cached_data and isinstance(cached_data, list) and len(cached_data) > 0:
                        # Используем кэш
                        link_ids = cached_data
                        result = await session.execute(
                            select(CrosspostingLink)
                            .options(
                                selectinload(CrosspostingLink.max_channel),
                                selectinload(CrosspostingLink.telegram_channel)
                            )
                            .where(CrosspostingLink.id.in_(link_ids))
                            .where(CrosspostingLink.is_enabled == True)
                        )
                        links: List[CrosspostingLink] = result.scalars().all()
                    else:
                        # Поиск активных связей для канала с eager loading
                        result = await session.execute(
                            select(CrosspostingLink)
                            .options(
                                selectinload(CrosspostingLink.max_channel),
                                selectinload(CrosspostingLink.telegram_channel)
                            )
                            .where(CrosspostingLink.telegram_channel_id == telegram_channel_id)
                            .where(CrosspostingLink.is_enabled == True)
                        )
                        links = result.scalars().all()
                        
                        # Кэширование ID связей
                        if links:
                            link_ids = [link.id for link in links]
                            await set_cache(cache_key, link_ids)
                    
                    if not links:
                        logger.debug("no_active_links", telegram_channel_id=telegram_channel_id)
                        return False
                    
                    # Проверка на дубликат для всех связей одним запросом
                    link_ids_list = [link.id for link in links]
                    existing_logs = await session.execute(
                        select(MessageLog)
                        .where(
                            MessageLog.crossposting_link_id.in_(link_ids_list),
                            MessageLog.telegram_message_id == telegram_message_id
                        )
                    )
                    existing_link_ids = {log.crossposting_link_id for log in existing_logs.scalars().all()}
                    
                    # Обрабатываем только те связи, для которых еще нет лога
                    links_to_process = [link for link in links if link.id not in existing_link_ids]
                    
                    if not links_to_process:
                        logger.debug("all_messages_duplicate", telegram_channel_id=telegram_channel_id, message_id=telegram_message_id)
                        return True
                    
                    # Обрабатываем каждую связь
                    success_count = 0
                    message_logs = []  # Сохраняем логи для обработки вне транзакции
                    
                    for link in links_to_process:
                        try:
                            # Создание записи в логе
                            message_log = MessageLog(
                                crossposting_link_id=link.id,
                                telegram_message_id=telegram_message_id,
                                status=MessageStatus.PENDING.value,
                                message_type=message_data.get("type", MessageType.TEXT.value),
                                created_at=datetime.utcnow()
                            )
                            session.add(message_log)
                            await session.flush()  # Flush для получения ID
                            message_logs.append((link, message_log))
                        except Exception as e:
                            logger.error(
                                "link_processing_error",
                                link_id=link.id,
                                error=str(e)
                            )
                            continue
                    
                    # Коммитим все логи одной транзакцией
                    # Теперь обрабатываем отправку сообщений вне транзакции
                    for link, message_log in message_logs:
                        try:
                            # Rate limiting
                            await max_api_limiter.wait_if_needed(f"max_api_{link.max_channel.channel_id}")
                            
                            max_message = await self._send_to_max(link, message_data)
                            
                            # Обновление лога в новой транзакции
                            async with async_session_maker() as update_session:
                                async with update_session.begin():
                                    await update_session.merge(message_log)
                                    message_log.status = MessageStatus.SUCCESS.value
                                    message_log.max_message_id = str(max_message.get("message_id", ""))
                                    message_log.sent_at = datetime.utcnow()
                                    message_log.processing_time_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)
                            
                            logger.info(
                                "message_processed",
                                link_id=link.id,
                                telegram_message_id=telegram_message_id,
                                max_message_id=max_message.get("message_id")
                            )
                            success_count += 1
                            
                        except APIError as e:
                            # Обработка ошибок API
                            await self._handle_send_error(
                                link.id,
                                telegram_message_id,
                                message_log,
                                str(e),
                                start_time
                            )
                        except Exception as e:
                            # Обработка других ошибок
                            await self._handle_send_error(
                                link.id,
                                telegram_message_id,
                                message_log,
                                str(e),
                                start_time
                            )
                    
                    return success_count > 0
                
                except Exception as e:
                    logger.error("message_processing_critical_error", error=str(e))
                    raise DatabaseError(f"Критическая ошибка обработки сообщения: {e}")
    
    async def _handle_send_error(
        self,
        link_id: int,
        telegram_message_id: int,
        message_log: MessageLog,
        error_message: str,
        start_time: datetime
    ) -> None:
        """Обработать ошибку отправки сообщения."""
        async with async_session_maker() as session:
            async with session.begin():
                await session.merge(message_log)
                message_log.status = MessageStatus.FAILED.value
                message_log.error_message = error_message
                message_log.processing_time_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)
                
                # Добавление в таблицу неудачных отправок
                failed_message = FailedMessage(
                    crossposting_link_id=link_id,
                    telegram_message_id=telegram_message_id,
                    error_message=error_message
                )
                session.add(failed_message)
        
        logger.error(
            "message_processing_failed",
            link_id=link_id,
            telegram_message_id=telegram_message_id,
            error=error_message
        )
    
    async def _send_to_max(
        self,
        link: CrosspostingLink,
        message_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Отправить сообщение в MAX канал.
        
        Args:
            link: Связь кросспостинга
            message_data: Данные сообщения
        
        Returns:
            Результат отправки
        
        Raises:
            APIError: При ошибке API
        """
        message_type = message_data.get("type", MessageType.TEXT.value)
        max_channel_id = link.max_channel.channel_id
        
        try:
            if message_type == MessageType.TEXT.value:
                text = message_data.get("text", "")
                return await self.max_client.send_message(
                    chat_id=max_channel_id,
                    text=text,
                    parse_mode=message_data.get("parse_mode")
                )
            elif message_type == MessageType.PHOTO.value:
                photo_url = message_data.get("photo_url")
                if not photo_url:
                    # Если нет URL, отправляем как текст с упоминанием фото
                    text = message_data.get("text", message_data.get("caption", "")) or "[Фото]"
                    return await self.max_client.send_message(
                        chat_id=max_channel_id,
                        text=text
                    )
                caption = message_data.get("caption")
                caption_parse_mode = message_data.get("caption_parse_mode")
                local_file_path = message_data.get("local_file_path")
                try:
                    result = await self.max_client.send_photo(
                        chat_id=max_channel_id,
                        photo_url=photo_url,
                        caption=caption,
                        local_file_path=local_file_path,
                        parse_mode=caption_parse_mode
                    )
                    # Удаляем файл после успешной отправки
                    if local_file_path:
                        from app.utils.media_handler import delete_media_file
                        await delete_media_file(local_file_path)
                        logger.info("media_file_deleted_after_send", file_path=local_file_path)
                    return result
                except Exception as e:
                    # В случае ошибки не удаляем файл сразу, он будет удален при очистке
                    logger.warning("failed_to_send_photo_keeping_file", error=str(e), photo_url=photo_url)
                    raise
            elif message_type == MessageType.VIDEO.value:
                video_url = message_data.get("video_url")
                if not video_url:
                    text = message_data.get("text", message_data.get("caption", "")) or "[Видео]"
                    return await self.max_client.send_message(
                        chat_id=max_channel_id,
                        text=text
                    )
                # TODO: Реализовать send_video когда будет доступно в MAX API
                caption = message_data.get("caption")
                return await self.max_client.send_message(
                    chat_id=max_channel_id,
                    text=f"[Видео]\n{caption}" if caption else "[Видео]"
                )
            else:
                # Для других типов отправляем как текст с указанием типа
                text = message_data.get("text", message_data.get("caption", "")) or f"[{message_type}]"
                return await self.max_client.send_message(
                    chat_id=max_channel_id,
                    text=text
                )
        except httpx.HTTPStatusError as e:
            raise APIError(
                f"HTTP ошибка при отправке в MAX: {e.response.status_code}",
                status_code=e.response.status_code,
                response=e.response.json() if e.response else None
            )
        except httpx.RequestError as e:
            raise APIError(f"Ошибка сети при отправке в MAX: {e}")
        except Exception as e:
            raise APIError(f"Неожиданная ошибка при отправке в MAX: {e}")
    
    async def process_telegram_message(self, message, client=None):
        """
        Обработать сообщение из Telegram (для MTProto).
        
        Args:
            message: Сообщение из Pyrogram
            client: Pyrogram клиент для загрузки медиа (опционально)
        """
        from pyrogram.types import Message
        from app.utils.media_handler import get_media_url, download_and_store_media
        from app.utils.enums import MessageType
        
        # Пропускаем только полностью пустые сообщения (без текста, caption и медиа)
        if not message.text and not message.caption and not (message.photo or message.video or message.document or message.audio or message.voice or message.sticker):
            logger.debug("skipping_empty_message", chat_id=message.chat.id if message.chat else None)
            return
        
        # Если сообщение входит в медиа-группу, обрабатываем через handler
        if hasattr(message, 'media_group_id') and message.media_group_id is not None:
            result = await self.media_group_handler.add_message(
                message,
                self._process_media_group,
                client=client
            )
            # Если сообщение добавлено в группу, обработка будет позже
            if result is None:
                return
            # Если группа обработана сразу (не должно быть), продолжаем
        
        # Подготовка данных сообщения
        message_data = {
            "type": MessageType.TEXT.value,
            "text": message.text or message.caption or "",
        }
        
        # Определение типа сообщения и получение URL медиа
        if message.photo:
            logger.info("processing_photo_message", chat_id=message.chat.id if message.chat else None)
            message_data["type"] = MessageType.PHOTO.value
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
            if client:
                try:
                    # Скачиваем фото и получаем публичный URL и локальный путь
                    logger.info("downloading_photo_start", chat_id=message.chat.id if message.chat else None)
                    photo_url, local_file_path = await download_and_store_media(client, message, "photo")
                    if photo_url:
                        logger.info("photo_downloaded", photo_url=photo_url, chat_id=message.chat.id if message.chat else None)
                        message_data["photo_url"] = photo_url
                        message_data["local_file_path"] = local_file_path
                    else:
                        logger.warning("photo_url_is_none", chat_id=message.chat.id if message.chat else None)
                        message_data["photo_url"] = None
                except Exception as e:
                    logger.error("failed_to_get_photo_url", error=str(e), exc_info=True)
                    message_data["photo_url"] = None
            else:
                logger.warning("no_client_for_photo_download", chat_id=message.chat.id if message.chat else None)
                message_data["photo_url"] = None
        elif message.video:
            message_data["type"] = MessageType.VIDEO.value
            message_data["caption"] = message.caption
            if client:
                try:
                    message_data["video_url"] = await get_media_url(client, message)
                except Exception as e:
                    logger.warning("failed_to_get_video_url", error=str(e))
                    message_data["video_url"] = None
            else:
                message_data["video_url"] = None
        elif message.document:
            message_data["type"] = MessageType.DOCUMENT.value
            message_data["caption"] = message.caption
            if client:
                try:
                    message_data["document_url"] = await get_media_url(client, message)
                except Exception as e:
                    logger.warning("failed_to_get_document_url", error=str(e))
                    message_data["document_url"] = None
            else:
                message_data["document_url"] = None
        elif message.audio:
            message_data["type"] = MessageType.AUDIO.value
            message_data["caption"] = message.caption
            if client:
                try:
                    message_data["audio_url"] = await get_media_url(client, message)
                except Exception as e:
                    logger.warning("failed_to_get_audio_url", error=str(e))
                    message_data["audio_url"] = None
            else:
                message_data["audio_url"] = None
        elif message.voice:
            message_data["type"] = MessageType.VOICE.value
            if client:
                try:
                    message_data["voice_url"] = await get_media_url(client, message)
                except Exception as e:
                    logger.warning("failed_to_get_voice_url", error=str(e))
                    message_data["voice_url"] = None
            else:
                message_data["voice_url"] = None
        elif message.sticker:
            message_data["type"] = MessageType.STICKER.value
            if client:
                try:
                    message_data["sticker_url"] = await get_media_url(client, message)
                except Exception as e:
                    logger.warning("failed_to_get_sticker_url", error=str(e))
                    message_data["sticker_url"] = None
            else:
                message_data["sticker_url"] = None
        
        # Обработка форматирования
        parse_mode = None
        if message.entities:
            from app.utils.text_formatter import apply_formatting
            formatted_text, parse_mode = apply_formatting(
                message_data.get("text", ""),
                message.entities
            )
            message_data["text"] = formatted_text
            message_data["parse_mode"] = parse_mode
        
        # Получаем ID канала Telegram
        telegram_chat_id = message.chat.id if message.chat else None
        if not telegram_chat_id:
            return
        
        # Находим запись канала в БД по channel_id
        from app.models.telegram_channel import TelegramChannel
        async with async_session_maker() as session:
            result = await session.execute(
                select(TelegramChannel).where(TelegramChannel.channel_id == telegram_chat_id)
            )
            telegram_channel = result.scalar_one_or_none()
            
            if not telegram_channel:
                logger.debug(
                    "telegram_channel_not_found",
                    channel_id=telegram_chat_id,
                    channel_title=message.chat.title if message.chat else None
                )
                return
            
            # Используем ID записи в БД для поиска связей
            telegram_channel_id = telegram_channel.id
        
        # Обрабатываем сообщение
        await self.process_message(
            telegram_channel_id=telegram_channel_id,
            telegram_message_id=message.id,
            message_data=message_data
        )
    
    async def _process_media_group(self, messages: List, client=None) -> None:
        """
        Обработать группу медиа-сообщений (альбом).
        
        Args:
            messages: Список сообщений из одной медиа-группы
            client: Pyrogram клиент для загрузки медиа
        """
        from app.utils.media_handler import download_and_store_media, delete_media_file
        
        if not messages:
            return
        
        # Берем первое сообщение для получения информации о канале
        first_message = messages[0]
        
        # Получаем ID канала Telegram
        telegram_chat_id = first_message.chat.id if first_message.chat else None
        if not telegram_chat_id:
            return
        
        # Находим запись канала в БД
        from app.models.telegram_channel import TelegramChannel
        async with async_session_maker() as session:
            result = await session.execute(
                select(TelegramChannel).where(TelegramChannel.channel_id == telegram_chat_id)
            )
            telegram_channel = result.scalar_one_or_none()
            
            if not telegram_channel:
                logger.debug(
                    "telegram_channel_not_found_for_media_group",
                    channel_id=telegram_chat_id
                )
                return
            
            telegram_channel_id = telegram_channel.id
        
        # Собираем все фото из группы
        photos_data = []
        caption = None
        caption_parse_mode = None
        text = ""
        
        for msg in messages:
            if msg.photo:
                # Получаем caption (обычно только у первого сообщения)
                if msg.caption and not caption:
                    caption = msg.caption
                    # Обрабатываем форматирование caption, если есть
                    if msg.caption_entities:
                        from app.utils.text_formatter import apply_formatting
                        formatted_caption, parse_mode = apply_formatting(
                            msg.caption or "",
                            msg.caption_entities
                        )
                        caption = formatted_caption
                        caption_parse_mode = parse_mode
                if msg.text and not text:
                    text = msg.text
                
                # Скачиваем фото
                try:
                    public_url, local_path = await download_and_store_media(
                        client,
                        msg,
                        "photo"
                    )
                    if local_path:
                        photos_data.append({
                            "local_file_path": local_path,
                            "public_url": public_url
                        })
                except Exception as e:
                    logger.error("failed_to_download_photo_from_group", error=str(e))
        
        if not photos_data:
            logger.warning("no_photos_in_media_group")
            return
        
        logger.info(
            "processing_media_group",
            photos_count=len(photos_data),
            channel_id=telegram_chat_id
        )
        
        # Отправляем все фото одним сообщением
        try:
            # Получаем связи для кросспостинга
            async with async_session_maker() as session:
                result = await session.execute(
                    select(CrosspostingLink)
                    .where(CrosspostingLink.telegram_channel_id == telegram_channel_id)
                    .where(CrosspostingLink.is_enabled == True)
                    .options(selectinload(CrosspostingLink.max_channel))
                )
                links = result.scalars().all()
            
            if not links:
                logger.debug("no_active_links_for_media_group", channel_id=telegram_chat_id)
                return
            
            # Отправляем в каждый MAX канал
            for link in links:
                try:
                    max_channel_id = link.max_channel.channel_id
                    
                    # Используем caption или text как подпись
                    album_caption = caption or text or ""
                    
                    # Отправляем альбом
                    local_paths = [photo["local_file_path"] for photo in photos_data]
                    result = await self.max_client.send_photos(
                        chat_id=max_channel_id,
                        local_file_paths=local_paths,
                        caption=album_caption,
                        parse_mode=caption_parse_mode
                    )
                    
                    logger.info(
                        "media_group_sent",
                        max_channel_id=max_channel_id,
                        photos_count=len(local_paths)
                    )
                    
                    # Удаляем файлы после успешной отправки
                    for photo_data in photos_data:
                        if photo_data.get("local_file_path"):
                            await delete_media_file(photo_data["local_file_path"])
                    
                except Exception as e:
                    logger.error(
                        "failed_to_send_media_group",
                        max_channel_id=link.max_channel.channel_id,
                        error=str(e)
                    )
        
        except Exception as e:
            logger.error("media_group_processing_error", error=str(e), exc_info=True)
    
    async def close(self):
        """Закрыть клиенты."""
        await self.max_client.close()

