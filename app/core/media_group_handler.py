"""Обработчик медиа-групп из Telegram."""
import asyncio
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from collections import defaultdict
from app.utils.logger import get_logger

logger = get_logger(__name__)


class MediaGroupHandler:
    """Обработчик для группировки медиа из Telegram в альбомы."""
    
    def __init__(self, timeout_seconds: int = 2):
        """
        Инициализация обработчика медиа-групп.
        
        Args:
            timeout_seconds: Время ожидания завершения группы (секунды)
        """
        self.timeout_seconds = timeout_seconds
        # {media_group_id: [messages]}
        self.groups: Dict[int, List[Any]] = defaultdict(list)
        # {media_group_id: asyncio.Task}
        self.pending_tasks: Dict[int, asyncio.Task] = {}
        # {media_group_id: datetime}
        self.group_timestamps: Dict[int, datetime] = {}
    
    async def add_message(self, message, process_callback, client=None) -> Optional[Any]:
        """
        Добавить сообщение в группу и обработать, если группа завершена.
        
        Args:
            message: Сообщение из Telegram
            process_callback: Функция для обработки группы сообщений
            client: Pyrogram клиент для загрузки медиа
        
        Returns:
            Результат обработки или None, если сообщение добавлено в группу
        """
        # Если у сообщения нет media_group_id, обрабатываем сразу
        if not hasattr(message, 'media_group_id') or message.media_group_id is None:
            return await process_callback([message])
        
        media_group_id = message.media_group_id
        
        # Добавляем сообщение в группу
        self.groups[media_group_id].append(message)
        self.group_timestamps[media_group_id] = datetime.utcnow()
        
        logger.debug(
            "media_group_message_added",
            media_group_id=media_group_id,
            group_size=len(self.groups[media_group_id])
        )
        
        # Отменяем предыдущую задачу для этой группы, если она есть
        if media_group_id in self.pending_tasks:
            self.pending_tasks[media_group_id].cancel()
        
        # Сохраняем client для использования при обработке группы
        if client and not hasattr(self, 'group_clients'):
            self.group_clients = {}
        if client:
            self.group_clients[media_group_id] = client
        
        # Создаем новую задачу с таймаутом
        task = asyncio.create_task(
            self._process_group_after_timeout(media_group_id, process_callback)
        )
        self.pending_tasks[media_group_id] = task
        
        # Возвращаем None, так как сообщение будет обработано вместе с группой
        return None
    
    async def _process_group_after_timeout(
        self,
        media_group_id: int,
        process_callback: Any
    ) -> None:
        """
        Обработать группу медиа после таймаута.
        
        Args:
            media_group_id: ID медиа-группы
            process_callback: Функция для обработки группы сообщений
        """
        """
        Обработать группу после таймаута.
        
        Args:
            media_group_id: ID медиа-группы
            process_callback: Функция для обработки группы сообщений
        """
        try:
            # Ждем таймаут
            await asyncio.sleep(self.timeout_seconds)
            
            # Проверяем, что группа еще существует
            if media_group_id not in self.groups:
                return
            
            # Получаем все сообщения группы
            messages = self.groups[media_group_id]
            
            if not messages:
                return
            
            logger.info(
                "processing_media_group",
                media_group_id=media_group_id,
                messages_count=len(messages)
            )
            
            # Обрабатываем группу
            try:
                # Получаем client для этой группы
                client = getattr(self, 'group_clients', {}).get(media_group_id)
                await process_callback(messages, client)
            except Exception as e:
                logger.error(
                    "media_group_processing_error",
                    media_group_id=media_group_id,
                    error=str(e),
                    exc_info=True
                )
            finally:
                # Удаляем группу после обработки
                if media_group_id in self.groups:
                    del self.groups[media_group_id]
                if media_group_id in self.group_timestamps:
                    del self.group_timestamps[media_group_id]
                if media_group_id in self.pending_tasks:
                    del self.pending_tasks[media_group_id]
                if hasattr(self, 'group_clients') and media_group_id in self.group_clients:
                    del self.group_clients[media_group_id]
        
        except asyncio.CancelledError:
            # Задача была отменена (добавлено новое сообщение в группу)
            logger.debug("media_group_task_cancelled", media_group_id=media_group_id)
        except Exception as e:
            logger.error(
                "media_group_timeout_error",
                media_group_id=media_group_id,
                error=str(e),
                exc_info=True
            )
    
    def cleanup_old_groups(self, max_age_seconds: int = 60) -> int:
        """
        Очистить старые группы, которые не были обработаны.
        
        Args:
            max_age_seconds: Максимальный возраст группы (секунды)
        
        Returns:
            Количество удаленных групп
        """
        now = datetime.utcnow()
        removed_count = 0
        
        for media_group_id in list(self.groups.keys()):
            if media_group_id in self.group_timestamps:
                age = (now - self.group_timestamps[media_group_id]).total_seconds()
                if age > max_age_seconds:
                    logger.warning(
                        "removing_stale_media_group",
                        media_group_id=media_group_id,
                        age_seconds=age
                    )
                    if media_group_id in self.groups:
                        del self.groups[media_group_id]
                    if media_group_id in self.group_timestamps:
                        del self.group_timestamps[media_group_id]
                    if media_group_id in self.pending_tasks:
                        self.pending_tasks[media_group_id].cancel()
                        del self.pending_tasks[media_group_id]
                    removed_count += 1
        
        return removed_count

