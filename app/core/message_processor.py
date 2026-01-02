"""Обработчик сообщений для кросспостинга."""
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from sqlalchemy.orm import selectinload
import httpx
import asyncio

from app.models.crossposting_link import CrosspostingLink
from app.models.message_log import MessageLog
from app.models.failed_message import FailedMessage
from app.max_api.client import MaxAPIClient
from app.utils.logger import get_logger
from app.utils.cache import get_cache, set_cache, delete_cache
from app.utils.enums import MessageStatus
from app.utils.exceptions import APIError, DatabaseError, MediaProcessingError
from app.utils.rate_limiter import max_api_limiter
from app.utils.circuit_breaker import CircuitBreaker
from app.utils.metrics import metrics_collector, record_operation_time
from app.utils.chat_id_converter import convert_chat_id
from config.database import async_session_maker
from config.settings import settings

logger = get_logger(__name__)

# Circuit breaker для MAX API
max_api_circuit_breaker = CircuitBreaker(
    failure_threshold=settings.circuit_breaker_failure_threshold,
    recovery_timeout=settings.circuit_breaker_recovery_timeout,
    expected_exception=APIError
)


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
        message_data: Dict[str, Any],
        link_id: Optional[int] = None
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
                    # Если передан link_id (миграция), обрабатываем только эту связь
                    # ВАЖНО: При миграции не проверяем is_enabled, так как связь временно отключается во время миграции
                    if link_id:
                        result = await session.execute(
                            select(CrosspostingLink)
                            .options(
                                selectinload(CrosspostingLink.max_channel),
                                selectinload(CrosspostingLink.telegram_channel)
                            )
                            .where(CrosspostingLink.id == link_id)
                        )
                        link = result.scalar_one_or_none()
                        if not link:
                            logger.warning("link_not_found_for_migration", link_id=link_id, telegram_channel_id=telegram_channel_id)
                            return False
                        links = [link]
                    else:
                        # Получаем активные связи с eager loading для оптимизации
                        cache_key = f"channel_links:{telegram_channel_id}"
                        cached_data = await get_cache(cache_key)
                        
                        if cached_data and isinstance(cached_data, list) and len(cached_data) > 0:
                            # Используем кэш
                            link_ids = cached_data
                            logger.info("using_cache_for_links", cache_key=cache_key, link_ids=link_ids, telegram_channel_id=telegram_channel_id)
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
                            logger.info("links_from_cache", cache_key=cache_key, cached_link_ids=link_ids, found_links_count=len(links), telegram_channel_id=telegram_channel_id)
                            if len(links) == 0 and len(link_ids) > 0:
                                # Проблема: кэш содержит ID связей, но они не найдены в БД или отключены
                                # Это может произойти после миграции, если кэш был создан до коммита или данные изменились
                                # Очищаем кэш и перезагружаем связи из БД
                                logger.warning("cache_contains_invalid_links", cache_key=cache_key, cached_link_ids=link_ids, telegram_channel_id=telegram_channel_id)
                                from app.utils.cache import delete_cache
                                await delete_cache(cache_key)
                                # Перезагружаем связи из БД с актуальными данными
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
                                logger.info("links_reloaded_after_cache_invalidation", cache_key=cache_key, found_links_count=len(links), telegram_channel_id=telegram_channel_id)
                                # Обновляем кэш с актуальными данными
                                if links:
                                    link_ids = [link.id for link in links]
                                    await set_cache(cache_key, link_ids)
                                    # Проверяем, что кэш обновлен правильно
                                    verify_cache = await get_cache(cache_key)
                                    logger.info("cache_updated_after_invalidation", cache_key=cache_key, link_ids=link_ids, telegram_channel_id=telegram_channel_id, cache_verified=verify_cache == link_ids)
                                else:
                                    logger.warning("no_active_links_after_cache_invalidation", cache_key=cache_key, telegram_channel_id=telegram_channel_id)
                        else:
                            # Поиск активных связей для канала с eager loading
                            logger.warning("cache_miss_or_empty", cache_key=cache_key, telegram_channel_id=telegram_channel_id)
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
                            logger.info("links_from_db", cache_key=cache_key, found_links_count=len(links), telegram_channel_id=telegram_channel_id)
                            
                            # Кэширование ID связей
                            if links:
                                link_ids = [link.id for link in links]
                                await set_cache(cache_key, link_ids)
                                logger.info("cache_updated", cache_key=cache_key, link_ids=link_ids, telegram_channel_id=telegram_channel_id)
                    
                    if not links:
                        logger.warning("no_active_links", telegram_channel_id=telegram_channel_id, cache_key=cache_key, link_id=link_id)
                        # Дополнительная проверка: возможно, связь отключена или удалена
                        async with async_session_maker() as check_session:
                            result = await check_session.execute(
                                select(CrosspostingLink)
                                .where(CrosspostingLink.telegram_channel_id == telegram_channel_id)
                            )
                            all_links = result.scalars().all()
                            logger.warning("all_links_for_channel", telegram_channel_id=telegram_channel_id, total_links=len(all_links), enabled_links=sum(1 for l in all_links if l.is_enabled))
                        return False
                    
                    # Проверка на дубликат для всех связей одним запросом
                    # ВАЖНО: Проверяем только записи со статусом SUCCESS, чтобы не пропускать
                    # сообщения, которые были обработаны с ошибкой (FAILED) или еще обрабатываются (PENDING)
                    link_ids_list = [link.id for link in links]
                    existing_logs = await session.execute(
                        select(MessageLog)
                        .where(
                            MessageLog.crossposting_link_id.in_(link_ids_list),
                            MessageLog.telegram_message_id == telegram_message_id,
                            MessageLog.status == MessageStatus.SUCCESS.value
                        )
                    )
                    existing_link_ids = {log.crossposting_link_id for log in existing_logs.scalars().all()}
                    
                    # Обрабатываем только те связи, для которых еще нет успешного лога
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
                                message_type=message_data.get("type", "text"),  # Используем строковое значение напрямую
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
                    # Теперь обрабатываем отправку сообщений параллельно
                    async def process_link(link: CrosspostingLink, message_log: MessageLog) -> Tuple[int, Optional[Dict], Optional[str], int]:
                        """Обработать одну связь."""
                        link_start_time = datetime.utcnow()
                        try:
                            # Rate limiting
                            await max_api_limiter.wait_if_needed(f"max_api_{link.max_channel.channel_id}")
                            
                            # Используем circuit breaker с таймаутом
                            try:
                                # Создаем задачу для возможности отмены при таймауте
                                send_task = asyncio.create_task(
                                    max_api_circuit_breaker.call(
                                        self._send_to_max,
                                        link,
                                        message_data
                                    )
                                )
                                max_message = await asyncio.wait_for(
                                    send_task,
                                    timeout=settings.max_api_timeout
                                )
                            except asyncio.TimeoutError:
                                # Отменяем задачу при таймауте
                                if not send_task.done():
                                    send_task.cancel()
                                    try:
                                        await send_task
                                    except asyncio.CancelledError:
                                        pass
                                raise APIError(f"Таймаут при отправке в MAX API (>{settings.max_api_timeout}с)")
                            
                            processing_time = int((datetime.utcnow() - link_start_time).total_seconds() * 1000)
                            
                            # Безопасное извлечение message_id
                            max_message_id = None
                            if max_message and isinstance(max_message, dict):
                                max_message_id = max_message.get("message_id")
                            
                            logger.info(
                                "message_processed",
                                link_id=link.id,
                                telegram_message_id=telegram_message_id,
                                max_message_id=max_message_id
                            )
                            
                            return (link.id, max_message, None, processing_time)
                            
                        except (APIError, httpx.HTTPStatusError, httpx.RequestError, asyncio.TimeoutError) as e:
                            # Конкретные исключения для API ошибок
                            error_msg = str(e)
                            processing_time = int((datetime.utcnow() - link_start_time).total_seconds() * 1000)
                            
                            # Проверяем, является ли это ошибкой неподдерживаемого формата (TGS стикеры, IMAGE_INVALID_FORMAT и т.д.)
                            # В таком случае просто пропускаем пост, не создавая запись об ошибке
                            error_lower = error_msg.lower()
                            if any(keyword in error_lower for keyword in ['tgs', 'не поддерживается', 'not supported', 'стикер не поддерживается', 'image_invalid_format', 'invalid format', 'не получен token', 'expecting value', 'jsondecodeerror', 'невалидный ответ']):
                                logger.info("message_skipped_unsupported_format", link_id=link.id, telegram_message_id=telegram_message_id, error=error_msg)
                                # Удаляем запись из лога, так как пост пропускается
                                try:
                                    async with async_session_maker() as skip_session:
                                        await skip_session.delete(message_log)
                                        await skip_session.commit()
                                except Exception as delete_error:
                                    logger.warning("failed_to_delete_message_log_for_skipped", error=str(delete_error))
                                # Возвращаем None, чтобы пост был пропущен
                                return (link.id, None, None, processing_time)
                            
                            await self._handle_send_error(
                                link.id,
                                telegram_message_id,
                                message_log,
                                error_msg,
                                link_start_time
                            )
                            return (link.id, None, error_msg, processing_time)
                        except (DatabaseError, MediaProcessingError) as e:
                            # Конкретные исключения для внутренних ошибок
                            error_msg = str(e)
                            processing_time = int((datetime.utcnow() - link_start_time).total_seconds() * 1000)
                            await self._handle_send_error(
                                link.id,
                                telegram_message_id,
                                message_log,
                                error_msg,
                                link_start_time
                            )
                            return (link.id, None, error_msg, processing_time)
                        except Exception as e:
                            # Неожиданные ошибки
                            error_msg = f"Неожиданная ошибка: {str(e)}"
                            processing_time = int((datetime.utcnow() - link_start_time).total_seconds() * 1000)
                            logger.error(
                                "unexpected_error_processing_link",
                                link_id=link.id,
                                error=str(e),
                                exc_info=True
                            )
                            await self._handle_send_error(
                                link.id,
                                telegram_message_id,
                                message_log,
                                error_msg,
                                link_start_time
                            )
                            return (link.id, None, error_msg, processing_time)
                    
                    # Параллельная обработка всех связей
                    results = await asyncio.gather(*[
                        process_link(link, message_log)
                        for link, message_log in message_logs
                    ], return_exceptions=True)
                    
                    # Batch update для всех успешных сообщений
                    success_updates = []
                    for result in results:
                        if isinstance(result, Exception):
                            logger.error("error_in_parallel_processing", error=str(result), exc_info=True)
                            continue
                        
                        link_id, max_message, error_msg, processing_time = result
                        
                        # Если error_msg=None, это означает, что пост был пропущен (неподдерживаемый формат)
                        # Не обрабатываем такие посты дальше
                        if error_msg is None and max_message is None:
                            logger.debug("message_skipped_in_parallel_processing", link_id=link_id, telegram_message_id=telegram_message_id)
                            continue
                        
                        if max_message:
                            message_log = next(ml for l, ml in message_logs if l.id == link_id)
                            # Безопасное извлечение message_id
                            max_message_id = ""
                            if isinstance(max_message, dict):
                                max_message_id = str(max_message.get("message_id", ""))
                            success_updates.append({
                                "message_log_id": message_log.id,
                                "max_message_id": max_message_id,
                                "processing_time": processing_time
                            })
                            success_count += 1
                    
                    # Batch update для всех успешных обновлений
                    if success_updates:
                        await self._batch_update_message_logs(success_updates, start_time)
                    
                    return success_count > 0
                
                except (DatabaseError, ValueError, TypeError) as e:
                    logger.error("message_processing_critical_error", error=str(e), exc_info=True)
                    raise DatabaseError(f"Критическая ошибка обработки сообщения: {e}")
                except Exception as e:
                    logger.error("message_processing_unexpected_error", error=str(e), exc_info=True)
                    raise DatabaseError(f"Неожиданная ошибка обработки сообщения: {e}")
    
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
    
    async def _batch_update_message_logs(
        self,
        updates: List[Dict[str, Any]],
        start_time: datetime
    ) -> None:
        """
        Batch update для message logs.
        
        Args:
            updates: Список словарей с данными для обновления
            start_time: Время начала обработки
        """
        if not updates:
            return
        
        async with async_session_maker() as session:
            async with session.begin():
                for update_data in updates:
                    message_log_id = update_data.get("message_log_id")
                    max_message_id = update_data.get("max_message_id")
                    processing_time = update_data.get("processing_time", 0)
                    
                    if message_log_id:
                        await session.execute(
                            update(MessageLog)
                            .where(MessageLog.id == message_log_id)
                            .values(
                                max_message_id=max_message_id,
                                status=MessageStatus.SUCCESS.value,
                                processing_time_ms=processing_time,
                                sent_at=datetime.utcnow()
                            )
                        )
        
        logger.debug(
            "batch_message_logs_updated",
            count=len(updates)
        )
    
    @record_operation_time("send_to_max")
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
        message_type = message_data.get("type", "text")  # Используем строковое значение напрямую
        max_channel_id = link.max_channel.channel_id
        
        try:
            if message_type == "text":
                text = message_data.get("text", "")
                return await self.max_client.send_message(
                    chat_id=max_channel_id,
                    text=text,
                    parse_mode=message_data.get("parse_mode")
                )
            elif message_type == "photo":
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
                    # Удаляем файл после успешной отправки (ДО return)
                    if local_file_path:
                        from app.utils.media_handler import delete_media_file
                        try:
                            await delete_media_file(local_file_path)
                            logger.info("media_file_deleted_after_send", file_path=local_file_path)
                        except Exception as delete_error:
                            # Логируем ошибку удаления, но не прерываем процесс
                            logger.warning("failed_to_delete_media_after_send", file_path=local_file_path, error=str(delete_error))
                    return result
                except Exception as e:
                    # Удаляем файл даже при ошибке отправки
                    if local_file_path:
                        from app.utils.media_handler import delete_media_file
                        try:
                            await delete_media_file(local_file_path)
                            logger.info("media_file_deleted_after_error", file_path=local_file_path)
                        except Exception as delete_error:
                            logger.warning("failed_to_delete_media_after_error", file_path=local_file_path, error=str(delete_error))
                    logger.warning("failed_to_send_photo", error=str(e), photo_url=photo_url)
                    raise
            elif message_type == "video":
                from app.utils.media_handler import delete_media_file
                video_url = message_data.get("video_url")
                local_file_path = message_data.get("local_file_path")
                caption = message_data.get("caption")
                parse_mode = message_data.get("parse_mode")
                
                if not local_file_path:
                    # Fallback: отправляем текст, если не удалось скачать видео
                    text = message_data.get("text", message_data.get("caption", "")) or "[Видео]"
                    return await self.max_client.send_message(
                        chat_id=max_channel_id,
                        text=text,
                        parse_mode=parse_mode
                    )
                
                try:
                    result = await self.max_client.send_video(
                        chat_id=max_channel_id,
                        video_url=video_url,
                        caption=caption,
                        local_file_path=local_file_path,
                        parse_mode=parse_mode
                    )
                    # Удаляем файл после успешной отправки (ДО return)
                    if local_file_path:
                        try:
                            await delete_media_file(local_file_path)
                            logger.info("video_file_deleted_after_send", file_path=local_file_path)
                        except Exception as delete_error:
                            # Логируем ошибку удаления, но не прерываем процесс
                            logger.warning("failed_to_delete_video_after_send", file_path=local_file_path, error=str(delete_error))
                    return result
                except Exception as e:
                    # Удаляем файл даже при ошибке отправки
                    if local_file_path:
                        try:
                            await delete_media_file(local_file_path)
                            logger.info("video_file_deleted_after_error", file_path=local_file_path)
                        except Exception as delete_error:
                            logger.warning("failed_to_delete_video_after_error", file_path=local_file_path, error=str(delete_error))
                    logger.warning("failed_to_send_video", error=str(e), video_url=video_url)
                    raise
            elif message_type == "document":
                from app.utils.media_handler import delete_media_file
                document_url = message_data.get("document_url")
                local_file_path = message_data.get("local_file_path")
                caption = message_data.get("caption")
                parse_mode = message_data.get("parse_mode")
                
                if not local_file_path:
                    # Fallback: отправляем текст, если не удалось скачать документ
                    text = message_data.get("text", message_data.get("caption", "")) or "[Документ]"
                    return await self.max_client.send_message(
                        chat_id=max_channel_id,
                        text=text,
                        parse_mode=parse_mode
                    )
                
                try:
                    result = await self.max_client.send_document(
                        chat_id=max_channel_id,
                        document_url=document_url,
                        caption=caption,
                        local_file_path=local_file_path,
                        parse_mode=parse_mode
                    )
                    # Удаляем файл после успешной отправки (ДО return)
                    if local_file_path:
                        try:
                            await delete_media_file(local_file_path)
                            logger.info("document_file_deleted_after_send", file_path=local_file_path)
                        except Exception as delete_error:
                            # Логируем ошибку удаления, но не прерываем процесс
                            logger.warning("failed_to_delete_document_after_send", file_path=local_file_path, error=str(delete_error))
                    return result
                except Exception as e:
                    # Удаляем файл даже при ошибке отправки
                    if local_file_path:
                        try:
                            await delete_media_file(local_file_path)
                            logger.info("document_file_deleted_after_error", file_path=local_file_path)
                        except Exception as delete_error:
                            logger.warning("failed_to_delete_document_after_error", file_path=local_file_path, error=str(delete_error))
                    logger.warning("failed_to_send_document", error=str(e), document_url=document_url)
                    raise
            elif message_type == "sticker":
                from app.utils.media_handler import delete_media_file
                sticker_url = message_data.get("sticker_url")
                local_file_path = message_data.get("local_file_path")
                
                if not local_file_path:
                    # Если не удалось скачать стикер, пропускаем его
                    logger.warning("sticker_not_downloaded_skipping", chat_id=max_channel_id)
                    raise APIError("Стикер не удалось скачать")
                
                try:
                    result = await self.max_client.send_sticker(
                        chat_id=max_channel_id,
                        sticker_url=sticker_url,
                        local_file_path=local_file_path
                    )
                    # Удаляем файл после успешной отправки (ДО return)
                    if local_file_path:
                        try:
                            await delete_media_file(local_file_path)
                            logger.info("sticker_file_deleted_after_send", file_path=local_file_path)
                        except Exception as delete_error:
                            # Логируем ошибку удаления, но не прерываем процесс
                            logger.warning("failed_to_delete_sticker_after_send", file_path=local_file_path, error=str(delete_error))
                    return result
                except APIError as e:
                    # Для TGS стикеров, IMAGE_INVALID_FORMAT и других неподдерживаемых форматов - пропускаем
                    error_msg = str(e).lower()
                    if any(keyword in error_msg for keyword in ['tgs', 'не поддерживается', 'not supported', 'image_invalid_format', 'invalid format']):
                        logger.info("sticker_not_supported_skipping", error=str(e), sticker_url=sticker_url, chat_id=max_channel_id)
                        # Удаляем файл
                        if local_file_path:
                            try:
                                await delete_media_file(local_file_path)
                            except Exception as delete_error:
                                logger.warning("failed_to_delete_unsupported_sticker", file_path=local_file_path, error=str(delete_error))
                        # Пропускаем стикер - выбрасываем исключение, которое будет обработано выше
                        raise APIError(f"Стикер не поддерживается: {e}")
                    # Для других ошибок - удаляем файл и пробрасываем
                    if local_file_path:
                        try:
                            await delete_media_file(local_file_path)
                            logger.info("sticker_file_deleted_after_error", file_path=local_file_path)
                        except Exception as delete_error:
                            logger.warning("failed_to_delete_sticker_after_error", file_path=local_file_path, error=str(delete_error))
                    logger.warning("failed_to_send_sticker", error=str(e), sticker_url=sticker_url)
                    raise
                except Exception as e:
                    # Удаляем файл даже при ошибке отправки
                    if local_file_path:
                        try:
                            await delete_media_file(local_file_path)
                            logger.info("sticker_file_deleted_after_error", file_path=local_file_path)
                        except Exception as delete_error:
                            logger.warning("failed_to_delete_sticker_after_error", file_path=local_file_path, error=str(delete_error))
                    logger.warning("failed_to_send_sticker", error=str(e), sticker_url=sticker_url)
                    raise
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
        except APIError:
            # Если это уже APIError, пробрасываем как есть (не оборачиваем)
            raise
        except Exception as e:
            raise APIError(f"Неожиданная ошибка при отправке в MAX: {e}")
    
    async def process_telegram_message(self, message, client=None):
        """
        Обработать сообщение из Telegram (для MTProto).
        
        Args:
            message: Сообщение из Pyrogram
            client: Pyrogram клиент для загрузки медиа (опционально)
        """
        try:
            from pyrogram.types import Message
            from app.utils.media_handler import get_media_url, download_and_store_media
            
            # Пропускаем только полностью пустые сообщения (без текста, caption и медиа)
            # ВАЖНО: Добавляем message.animation и message.video_note для поддержки GIF и кружочков
            if not message.text and not message.caption and not (message.photo or message.video or message.document or message.audio or message.voice or message.sticker or message.animation or message.video_note):
                logger.debug("skipping_empty_message", chat_id=message.chat.id if message.chat else None)
                return
            
            # Получаем ID канала Telegram
            telegram_chat_id = message.chat.id if message.chat else None
            if not telegram_chat_id:
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
                "type": "text",  # Используем строковое значение напрямую
                "text": message.text or message.caption or "",
            }
            
            # Определение типа сообщения и получение URL медиа
            if message.photo:
                logger.info("processing_photo_message", chat_id=message.chat.id if message.chat else None)
                message_data["type"] = "photo"
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
                logger.info("processing_video_message", chat_id=message.chat.id if message.chat else None)
                message_data["type"] = "video"
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
                if client:
                    try:
                        # Скачиваем видео и получаем публичный URL и локальный путь
                        logger.info("downloading_video_start", chat_id=message.chat.id if message.chat else None)
                        video_url, local_file_path = await download_and_store_media(client, message, "video")
                        if video_url and local_file_path:
                            logger.info("video_downloaded", video_url=video_url, local_file_path=local_file_path, chat_id=message.chat.id if message.chat else None)
                            message_data["video_url"] = video_url
                            message_data["local_file_path"] = local_file_path
                        else:
                            logger.warning("video_url_or_path_is_none", chat_id=message.chat.id if message.chat else None)
                            message_data["video_url"] = None
                            message_data["local_file_path"] = None
                    except Exception as e:
                        logger.error("failed_to_get_video_url", error=str(e), exc_info=True)
                        message_data["video_url"] = None
                        message_data["local_file_path"] = None
                else:
                    message_data["video_url"] = None
                    message_data["local_file_path"] = None
            elif message.document:
                logger.info("processing_document_message", chat_id=message.chat.id if message.chat else None)
                message_data["type"] = "document"
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
                if client:
                    try:
                        # Скачиваем документ и получаем публичный URL и локальный путь
                        logger.info("downloading_document_start", chat_id=message.chat.id if message.chat else None)
                        document_url, local_file_path = await download_and_store_media(client, message, "document")
                        if document_url and local_file_path:
                            logger.info("document_downloaded", document_url=document_url, local_file_path=local_file_path, chat_id=message.chat.id if message.chat else None)
                            message_data["document_url"] = document_url
                            message_data["local_file_path"] = local_file_path
                        else:
                            logger.warning("document_url_or_path_is_none", chat_id=message.chat.id if message.chat else None)
                            message_data["document_url"] = None
                            message_data["local_file_path"] = None
                    except Exception as e:
                        logger.error("failed_to_get_document_url", error=str(e), exc_info=True)
                        message_data["document_url"] = None
                        message_data["local_file_path"] = None
                else:
                    logger.warning("no_client_for_document_download", chat_id=message.chat.id if message.chat else None)
                    message_data["document_url"] = None
                    message_data["local_file_path"] = None
            elif message.animation:
                # Обработка GIF (message.animation)
                # В Pyrogram animation похож на video, но это специальный тип для анимированных GIF
                logger.info("processing_animation_message", chat_id=message.chat.id if message.chat else None)
                message_data["type"] = "video"  # Обрабатываем animation как video для MAX API
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
                if client:
                    try:
                        # Скачиваем animation (GIF) и получаем публичный URL и локальный путь
                        # Используем "animation" как тип для скачивания
                        logger.info("downloading_animation_start", chat_id=message.chat.id if message.chat else None)
                        animation_url, local_file_path = await download_and_store_media(client, message, "animation")
                        if animation_url and local_file_path:
                            logger.info("animation_downloaded", animation_url=animation_url, local_file_path=local_file_path, chat_id=message.chat.id if message.chat else None)
                            message_data["video_url"] = animation_url  # Используем video_url для совместимости с send_video
                            message_data["local_file_path"] = local_file_path
                        else:
                            logger.warning("animation_url_or_path_is_none", chat_id=message.chat.id if message.chat else None)
                            message_data["video_url"] = None
                            message_data["local_file_path"] = None
                    except Exception as e:
                        logger.error("failed_to_get_animation_url", error=str(e), exc_info=True)
                        message_data["video_url"] = None
                        message_data["local_file_path"] = None
                else:
                    logger.warning("no_client_for_animation_download", chat_id=message.chat.id if message.chat else None)
                    message_data["video_url"] = None
                    message_data["local_file_path"] = None
            elif message.audio:
                message_data["type"] = "audio"
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
                message_data["type"] = "voice"
                if client:
                    try:
                        message_data["voice_url"] = await get_media_url(client, message)
                    except Exception as e:
                        logger.warning("failed_to_get_voice_url", error=str(e))
                        message_data["voice_url"] = None
                else:
                    message_data["voice_url"] = None
            elif message.video_note:
                # Обработка video note (кружочки)
                # Video note - это обычное MP4 видео в квадратном формате, обрабатываем как video
                logger.info("processing_video_note_message", chat_id=message.chat.id if message.chat else None)
                message_data["type"] = "video"  # Обрабатываем video_note как video для MAX API
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
                if client:
                    try:
                        # Скачиваем video note и получаем публичный URL и локальный путь
                        logger.info("downloading_video_note_start", chat_id=message.chat.id if message.chat else None)
                        video_url, local_file_path = await download_and_store_media(client, message, "video_note")
                        if video_url and local_file_path:
                            logger.info("video_note_downloaded", video_url=video_url, local_file_path=local_file_path, chat_id=message.chat.id if message.chat else None)
                            message_data["video_url"] = video_url
                            message_data["local_file_path"] = local_file_path
                        else:
                            logger.warning("video_note_url_or_path_is_none", chat_id=message.chat.id if message.chat else None)
                            message_data["video_url"] = None
                            message_data["local_file_path"] = None
                    except Exception as e:
                        logger.error("failed_to_get_video_note_url", error=str(e), exc_info=True)
                        message_data["video_url"] = None
                        message_data["local_file_path"] = None
                else:
                    logger.warning("no_client_for_video_note_download", chat_id=message.chat.id if message.chat else None)
                    message_data["video_url"] = None
                    message_data["local_file_path"] = None
            elif message.sticker:
                logger.info("processing_sticker_message", chat_id=message.chat.id if message.chat else None)
                message_data["type"] = "sticker"
                if client:
                    try:
                        # Скачиваем стикер и получаем публичный URL и локальный путь
                        logger.info("downloading_sticker_start", chat_id=message.chat.id if message.chat else None)
                        sticker_url, local_file_path = await download_and_store_media(client, message, "sticker")
                        if sticker_url and local_file_path:
                            logger.info("sticker_downloaded", sticker_url=sticker_url, local_file_path=local_file_path, chat_id=message.chat.id if message.chat else None)
                            message_data["sticker_url"] = sticker_url
                            message_data["local_file_path"] = local_file_path
                        else:
                            logger.warning("sticker_url_or_path_is_none", chat_id=message.chat.id if message.chat else None)
                            message_data["sticker_url"] = None
                            message_data["local_file_path"] = None
                    except Exception as e:
                        logger.error("failed_to_get_sticker_url", error=str(e), exc_info=True)
                        message_data["sticker_url"] = None
                        message_data["local_file_path"] = None
                else:
                    logger.warning("no_client_for_sticker_download", chat_id=message.chat.id if message.chat else None)
                    message_data["sticker_url"] = None
                    message_data["local_file_path"] = None
            
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
                logger.info(
                    "processing_message_from_telegram",
                    telegram_channel_db_id=telegram_channel_id,
                    telegram_chat_id=telegram_chat_id,
                    message_id=message.id,
                    channel_title=message.chat.title if message.chat else None
                )
            
                # Обрабатываем сообщение
                result = await self.process_message(
                    telegram_channel_id=telegram_channel_id,
                    telegram_message_id=message.id,
                    message_data=message_data
                )
                logger.info(
                    "process_message_result",
                    telegram_channel_id=telegram_channel_id,
                    message_id=message.id,
                    result=result,
                    success=result is True
                )
        except Exception as e:
            # КРИТИЧНО: Обрабатываем любые ошибки при обработке сообщения из Telegram
            # Логируем ошибку, но не прерываем кросспостинг - продолжаем со следующего сообщения
            logger.error(
                "error_processing_telegram_message",
                message_id=message.id if message else None,
                chat_id=message.chat.id if message and message.chat else None,
                error=str(e),
                exc_info=True
            )
            # Просто возвращаемся - сообщение пропущено, кросспостинг продолжается
            return
    
    async def _process_media_group(self, messages: List, client=None, link_id: Optional[int] = None) -> None:
        """
        Обработать группу медиа-сообщений (альбом).
        
        Args:
            messages: Список сообщений из одной медиа-группы
            client: Pyrogram клиент для загрузки медиа
            link_id: ID связи для миграции (опционально)
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
        
        # Собираем все медиа из группы (фото и видео)
        # ВАЖНО: Нет ограничений на количество медиафайлов - обрабатываются ВСЕ файлы из группы
        photos_data = []
        videos_data = []
        caption = None
        caption_parse_mode = None
        text = ""
        
        for msg in messages:
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
            
            # Обрабатываем фото
            if msg.photo:
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
            
            # Обрабатываем видео
            elif msg.video:
                try:
                    public_url, local_path = await download_and_store_media(
                        client,
                        msg,
                        "video"
                    )
                    if local_path:
                        videos_data.append({
                            "local_file_path": local_path,
                            "public_url": public_url
                        })
                except Exception as e:
                    logger.error("failed_to_download_video_from_group", error=str(e))
        
        # КРИТИЧНО: Создаем записи в MessageLog для всех сообщений из группы
        # Это нужно как для миграции (link_id указан), так и для кросспостинга (link_id не указан)
        from app.models.message_log import MessageLog
        from app.utils.enums import MessageStatus
        from datetime import datetime
        from app.models.crossposting_link import CrosspostingLink
        
        async with async_session_maker() as session:
            # Определяем, для каких связей нужно создать записи
            if link_id:
                # Для миграции используем только указанную связь
                links_to_log = [link_id]
            else:
                # Для кросспостинга используем все активные связи
                result = await session.execute(
                    select(CrosspostingLink.id)
                    .where(CrosspostingLink.telegram_channel_id == telegram_channel_id)
                    .where(CrosspostingLink.is_enabled == True)
                )
                # result.scalars().all() уже возвращает список ID (int), не нужно обращаться к .id
                links_to_log = list(result.scalars().all())
            
            # Создаем записи в MessageLog для всех сообщений и всех связей
            for msg in messages:
                # Определяем тип сообщения
                msg_type = "photo" if msg.photo else "video" if msg.video else "text"
                
                for link_id_for_log in links_to_log:
                    # Проверяем, есть ли уже запись со статусом SUCCESS (дубликат)
                    existing_log = await session.execute(
                        select(MessageLog)
                        .where(MessageLog.telegram_message_id == msg.id)
                        .where(MessageLog.crossposting_link_id == link_id_for_log)
                        .where(MessageLog.status == MessageStatus.SUCCESS.value)
                    )
                    if existing_log.scalar_one_or_none():
                        # Уже есть успешная запись - пропускаем
                        continue
                    
                    # Проверяем, есть ли запись со статусом PENDING или FAILED
                    existing_pending = await session.execute(
                        select(MessageLog)
                        .where(MessageLog.telegram_message_id == msg.id)
                        .where(MessageLog.crossposting_link_id == link_id_for_log)
                    )
                    message_log = existing_pending.scalar_one_or_none()
                    
                    if not message_log:
                        # Создаем новую запись
                        message_log = MessageLog(
                            crossposting_link_id=link_id_for_log,
                            telegram_message_id=msg.id,
                            status=MessageStatus.PENDING.value,
                            message_type=msg_type,
                            created_at=datetime.utcnow()
                        )
                        session.add(message_log)
                    else:
                        # Обновляем существующую запись на PENDING
                        message_log.status = MessageStatus.PENDING.value
            await session.commit()
        
        # Определяем тип группы и обрабатываем соответственно
        if photos_data and not videos_data:
            # Только фото - отправляем как альбом фото
            media_type = "photos"
            media_data = photos_data
        elif videos_data and not photos_data:
            # Только видео - отправляем как альбом видео
            media_type = "videos"
            media_data = videos_data
        elif photos_data and videos_data:
            # Смешанная группа - отправляем все медиа одним сообщением
            logger.info("mixed_media_group", photos_count=len(photos_data), videos_count=len(videos_data))
            # КРИТИЧНО: Передаем messages всегда, чтобы можно было обновить MessageLog
            await self._send_mixed_media_group(telegram_channel_id, photos_data, videos_data, caption, caption_parse_mode, client, link_id=link_id, messages=messages)
            return
        else:
            logger.warning("no_media_in_media_group")
            return
        
            logger.info(
                "processing_media_group",
                media_type=media_type,
                media_count=len(media_data),
            channel_id=telegram_chat_id
            )
        
            # Отправляем группу медиа
        # КРИТИЧНО: Передаем messages всегда, чтобы можно было обновить MessageLog
        await self._send_media_group(telegram_channel_id, media_data, media_type, caption, caption_parse_mode, client, link_id=link_id, messages=messages)
    
    async def _send_media_group(
        self,
        telegram_channel_id: int,
        media_data: List[Dict[str, str]],
        media_type: str,
        caption: Optional[str],
        caption_parse_mode: Optional[str],
        client,
        link_id: Optional[int] = None,
        messages: Optional[List] = None
    ):
        """
        Отправить группу медиа (фото или видео) в MAX.
        
        Args:
            telegram_channel_id: ID Telegram канала в БД
            media_data: Список словарей с local_file_path и public_url
            media_type: "photos" или "videos"
            caption: Подпись к группе
            caption_parse_mode: Режим форматирования подписи
            client: Pyrogram клиент
            link_id: ID связи для миграции (опционально, если указан - используется только эта связь)
        """
        from app.utils.media_handler import delete_media_file
        
        try:
            # Получаем связи для кросспостинга
            async with async_session_maker() as session:
                if link_id:
                    # Для миграции используем только указанную связь
                    result = await session.execute(
                        select(CrosspostingLink)
                        .where(CrosspostingLink.id == link_id)
                        .where(CrosspostingLink.telegram_channel_id == telegram_channel_id)
                        .options(selectinload(CrosspostingLink.max_channel))
                    )
                    links = result.scalars().all()
                else:
                    # Для обычного кросспостинга используем все активные связи
                    result = await session.execute(
                        select(CrosspostingLink)
                        .where(CrosspostingLink.telegram_channel_id == telegram_channel_id)
                        .where(CrosspostingLink.is_enabled == True)
                        .options(selectinload(CrosspostingLink.max_channel))
                    )
                    links = result.scalars().all()
            
            if not links:
                logger.debug("no_active_links_for_media_group", channel_id=telegram_channel_id, link_id=link_id)
                return
            
            # Отправляем в каждый MAX канал
            for link in links:
                try:
                    max_channel_id = link.max_channel.channel_id
                    
                    # Используем caption или text как подпись
                    album_caption = caption or ""
                    
                    if media_type == "photos":
                        # Отправляем альбом фото
                        local_paths = [media["local_file_path"] for media in media_data]
                        result = await self.max_client.send_photos(
                            chat_id=max_channel_id,
                            local_file_paths=local_paths,
                            caption=album_caption,
                            parse_mode=caption_parse_mode
                        )
                        
                        logger.info(
                            "photos_group_sent",
                            max_channel_id=max_channel_id,
                            photos_count=len(local_paths)
                        )
                    elif media_type == "videos":
                        # Отправляем альбом видео
                        local_paths = [media["local_file_path"] for media in media_data]
                        result = await self.max_client.send_videos(
                            chat_id=max_channel_id,
                            local_file_paths=local_paths,
                            caption=album_caption,
                            parse_mode=caption_parse_mode
                        )
                        
                        logger.info(
                            "videos_group_sent",
                            max_channel_id=max_channel_id,
                            videos_count=len(local_paths)
                        )
                    
                    # КРИТИЧНО: Обновляем MessageLog для всех сообщений из группы
                    # Это нужно как для миграции (link_id указан), так и для кросспостинга (link_id не указан)
                    if result and messages:
                        from app.models.message_log import MessageLog
                        from app.utils.enums import MessageStatus
                        from datetime import datetime
                        from sqlalchemy import update
                        
                        # Извлекаем message_id из результата
                        max_message_id = None
                        if isinstance(result, dict):
                            max_message_id = result.get("message_id")
                        
                        # Обновляем все записи для сообщений из группы
                        async with async_session_maker() as session_for_update:
                            for msg in messages:
                                if link_id:
                                    # Для миграции обновляем только указанную связь
                                    await session_for_update.execute(
                                        update(MessageLog)
                                        .where(MessageLog.telegram_message_id == msg.id)
                                        .where(MessageLog.crossposting_link_id == link_id)
                                        .values(
                                            max_message_id=str(max_message_id) if max_message_id else None,
                                            status=MessageStatus.SUCCESS.value,
                                            sent_at=datetime.utcnow()
                                        )
                                    )
                                else:
                                    # Для кросспостинга обновляем все активные связи для этого сообщения
                                    await session_for_update.execute(
                                        update(MessageLog)
                                        .where(MessageLog.telegram_message_id == msg.id)
                                        .where(MessageLog.crossposting_link_id == link.id)
                                        .values(
                                            max_message_id=str(max_message_id) if max_message_id else None,
                                            status=MessageStatus.SUCCESS.value,
                                            sent_at=datetime.utcnow()
                                        )
                                    )
                            await session_for_update.commit()
                    
                    # Удаляем файлы после успешной отправки (ДО выхода из try блока)
                    for media_item in media_data:
                        if media_item.get("local_file_path"):
                            try:
                                await delete_media_file(media_item["local_file_path"])
                            except Exception as delete_error:
                                # Логируем ошибку удаления, но не прерываем процесс
                                logger.warning("failed_to_delete_media_in_group", file_path=media_item["local_file_path"], error=str(delete_error))
                    
                except Exception as e:
                    # Удаляем файлы даже при ошибке отправки
                    for media_item in media_data:
                        if media_item.get("local_file_path"):
                            try:
                                await delete_media_file(media_item["local_file_path"])
                                logger.info("media_file_deleted_after_error", file_path=media_item["local_file_path"])
                            except Exception as delete_error:
                                logger.warning("failed_to_delete_media_after_error", file_path=media_item["local_file_path"], error=str(delete_error))
                    logger.error(
                        "failed_to_send_media_group",
                        max_channel_id=link.max_channel.channel_id,
                        media_type=media_type,
                        error=str(e)
                    )
        
        except Exception as e:
            logger.error("media_group_send_error", media_type=media_type, error=str(e), exc_info=True)
    
    async def _send_mixed_media_group(
        self,
        telegram_channel_id: int,
        photos_data: List[Dict[str, str]],
        videos_data: List[Dict[str, str]],
        caption: Optional[str],
        caption_parse_mode: Optional[str],
        client,
        link_id: Optional[int] = None,
        messages: Optional[List] = None
    ):
        """
        Отправить смешанную группу медиа (фото + видео) одним сообщением в MAX.
        
        ВАЖНО: Нет ограничений на количество медиафайлов - отправляются ВСЕ фото и видео из группы.
        
        Args:
            telegram_channel_id: ID Telegram канала в БД
            photos_data: Список словарей с данными фото (без ограничений по количеству)
            videos_data: Список словарей с данными видео (без ограничений по количеству)
            caption: Подпись к группе
            caption_parse_mode: Режим форматирования подписи
            client: Pyrogram клиент
            link_id: ID связи для миграции (опционально, если указан - используется только эта связь)
        """
        from app.utils.media_handler import delete_media_file
        
        try:
            # Получаем связи для кросспостинга
            async with async_session_maker() as session:
                if link_id:
                    # Для миграции используем только указанную связь
                    result = await session.execute(
                        select(CrosspostingLink)
                        .where(CrosspostingLink.id == link_id)
                        .where(CrosspostingLink.telegram_channel_id == telegram_channel_id)
                        .options(selectinload(CrosspostingLink.max_channel))
                    )
                    links = result.scalars().all()
                else:
                    # Для обычного кросспостинга используем все активные связи
                    result = await session.execute(
                        select(CrosspostingLink)
                        .where(CrosspostingLink.telegram_channel_id == telegram_channel_id)
                        .where(CrosspostingLink.is_enabled == True)
                        .options(selectinload(CrosspostingLink.max_channel))
                    )
                    links = result.scalars().all()
            
            if not links:
                logger.debug("no_active_links_for_mixed_media_group", channel_id=telegram_channel_id, link_id=link_id)
                return
            
            # Отправляем в каждый MAX канал
            for link in links:
                try:
                    max_channel_id = link.max_channel.channel_id
                    
                    # Используем caption или text как подпись
                    album_caption = caption or ""
                    
                    # Загружаем все медиа и получаем токены
                    attachments = []
                    
                    # Загружаем фото
                    for photo_data in photos_data:
                        local_path = photo_data.get("local_file_path")
                        if local_path:
                            try:
                                token = await self.max_client.upload_file(local_path, "image")
                                attachments.append({
                                    "type": "image",
                                    "payload": {
                                        "token": token
                                    }
                                })
                                await asyncio.sleep(settings.media_upload_delay_photo)
                            except Exception as e:
                                logger.error("failed_to_upload_photo_in_mixed_group", error=str(e))
                    
                    # Загружаем видео
                    for video_data in videos_data:
                        local_path = video_data.get("local_file_path")
                        if local_path:
                            try:
                                token = await self.max_client.upload_file(local_path, "video")
                                attachments.append({
                                    "type": "video",
                                    "payload": {
                                        "token": token
                                    }
                                })
                                await asyncio.sleep(settings.media_upload_delay_video)
                            except Exception as e:
                                logger.error("failed_to_upload_video_in_mixed_group", error=str(e))
                    
                    if not attachments:
                        logger.warning("no_attachments_in_mixed_group")
                        continue
                    
                    # Адаптивная задержка обработки
                    processing_delay = min(
                        settings.media_processing_delay_video * (1 + len(attachments) * 0.1),
                        10.0
                    )
                    await asyncio.sleep(processing_delay)
                    
                    # Формируем запрос с массивом attachments (фото + видео)
                    text = album_caption or ""
                    data = {
                        "text": text,
                        "attachments": attachments
                    }
                    if caption_parse_mode:
                        data["format"] = caption_parse_mode
                    
                    # Преобразуем chat_id
                    try:
                        if isinstance(max_channel_id, str) and (max_channel_id.lstrip('-').isdigit() or max_channel_id.lstrip('-').replace('.', '').isdigit()):
                            chat_id_value = int(float(max_channel_id))
                        elif isinstance(max_channel_id, (int, float)):
                            chat_id_value = int(max_channel_id)
                        else:
                            chat_id_value = max_channel_id
                    except (ValueError, TypeError):
                        chat_id_value = max_channel_id
                    
                    # Отправляем смешанную группу
                    from app.utils.rate_limiter import max_api_limiter
                    from app.utils.retry import retry_with_backoff
                    
                    await max_api_limiter.wait_if_needed(f"max_api_{max_channel_id}")
                    
                    max_retries = 5
                    retry_delay = 3
                    result = None
                    
                    for attempt in range(max_retries):
                        try:
                            response = await retry_with_backoff(
                                self.max_client.client.post,
                                f"/messages?chat_id={chat_id_value}",
                                json=data
                            )
                            response.raise_for_status()
                            result = response.json()
                            
                            # Проверяем на ошибку attachment.not.ready
                            if 'error' in result or 'errors' in result:
                                error_msg = str(result.get('error', result.get('errors', '')))
                                if 'attachment.not.ready' in error_msg.lower() or 'not.ready' in error_msg.lower():
                                    if attempt < max_retries - 1:
                                        logger.warning(f"mixed_group_attachment_not_ready_retry", attempt=attempt+1, delay=retry_delay)
                                        await asyncio.sleep(retry_delay)
                                        retry_delay *= 2
                                        continue
                            
                            logger.info(
                                "mixed_media_group_sent",
                                max_channel_id=max_channel_id,
                                photos_count=len(photos_data),
                                videos_count=len(videos_data),
                                total_attachments=len(attachments)
                            )
                            break
                        except httpx.HTTPStatusError as e:
                            if e.response:
                                try:
                                    error_data = e.response.json()
                                    error_msg = str(error_data)
                                    if 'attachment.not.ready' in error_msg.lower() or 'not.ready' in error_msg.lower():
                                        if attempt < max_retries - 1:
                                            logger.warning(f"mixed_group_attachment_not_ready_retry", attempt=attempt+1, delay=retry_delay)
                                            await asyncio.sleep(retry_delay)
                                            retry_delay *= 2
                                            continue
                                except:
                                    pass
                            if attempt == max_retries - 1:
                                raise
                        except Exception as e:
                            if attempt == max_retries - 1:
                                raise
                            logger.warning(f"mixed_group_retry_after_error", attempt=attempt+1, error=str(e))
                            await asyncio.sleep(retry_delay)
                            retry_delay *= 2
                    
                    # КРИТИЧНО: Обновляем MessageLog для всех сообщений из группы
                    # Это нужно как для миграции (link_id указан), так и для кросспостинга (link_id не указан)
                    if result and messages:
                        from app.models.message_log import MessageLog
                        from app.utils.enums import MessageStatus
                        from datetime import datetime
                        from sqlalchemy import update
                        
                        # Извлекаем message_id из результата
                        max_message_id = None
                        if isinstance(result, dict):
                            max_message_id = result.get("message_id")
                        
                        # Обновляем все записи для сообщений из группы
                        async with async_session_maker() as session_for_update:
                            for msg in messages:
                                if link_id:
                                    # Для миграции обновляем только указанную связь
                                    await session_for_update.execute(
                                        update(MessageLog)
                                        .where(MessageLog.telegram_message_id == msg.id)
                                        .where(MessageLog.crossposting_link_id == link_id)
                                        .values(
                                            max_message_id=str(max_message_id) if max_message_id else None,
                                            status=MessageStatus.SUCCESS.value,
                                            sent_at=datetime.utcnow()
                                        )
                                    )
                                else:
                                    # Для кросспостинга обновляем все активные связи для этого сообщения
                                    await session_for_update.execute(
                                        update(MessageLog)
                                        .where(MessageLog.telegram_message_id == msg.id)
                                        .where(MessageLog.crossposting_link_id == link.id)
                                        .values(
                                            max_message_id=str(max_message_id) if max_message_id else None,
                                            status=MessageStatus.SUCCESS.value,
                                            sent_at=datetime.utcnow()
                                        )
                                    )
                                    await session_for_update.commit()
                    
                    # Удаляем файлы после успешной отправки (ДО выхода из try блока)
                    for photo_data in photos_data:
                        if photo_data.get("local_file_path"):
                            try:
                                await delete_media_file(photo_data["local_file_path"])
                            except Exception as delete_error:
                                # Логируем ошибку удаления, но не прерываем процесс
                                logger.warning("failed_to_delete_photo_in_mixed_group", file_path=photo_data["local_file_path"], error=str(delete_error))
                    for video_data in videos_data:
                        if video_data.get("local_file_path"):
                            try:
                                await delete_media_file(video_data["local_file_path"])
                            except Exception as delete_error:
                                # Логируем ошибку удаления, но не прерываем процесс
                                logger.warning("failed_to_delete_video_in_mixed_group", file_path=video_data["local_file_path"], error=str(delete_error))
                    
                except Exception as e:
                    # Удаляем файлы даже при ошибке отправки
                    for photo_data in photos_data:
                        if photo_data.get("local_file_path"):
                            try:
                                await delete_media_file(photo_data["local_file_path"])
                                logger.info("photo_file_deleted_after_error", file_path=photo_data["local_file_path"])
                            except Exception as delete_error:
                                logger.warning("failed_to_delete_photo_after_error", file_path=photo_data["local_file_path"], error=str(delete_error))
                    for video_data in videos_data:
                        if video_data.get("local_file_path"):
                            try:
                                await delete_media_file(video_data["local_file_path"])
                                logger.info("video_file_deleted_after_error", file_path=video_data["local_file_path"])
                            except Exception as delete_error:
                                logger.warning("failed_to_delete_video_after_error", file_path=video_data["local_file_path"], error=str(delete_error))
                    logger.error(
                        "failed_to_send_mixed_media_group",
                        max_channel_id=link.max_channel.channel_id,
                        error=str(e)
                    )
        
        except Exception as e:
            logger.error("mixed_media_group_send_error", error=str(e), exc_info=True)
    
    async def close(self):
        """Закрыть клиенты."""
        await self.max_client.close()

