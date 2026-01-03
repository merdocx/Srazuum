"""Очередь для новых постов во время миграции."""

from typing import Dict, List, Any, Set
import asyncio
from app.utils.logger import get_logger

logger = get_logger(__name__)


class MigrationQueue:
    """Очередь для хранения новых постов во время миграции."""

    def __init__(self):
        # Словарь: link_id -> список сообщений
        self._queues: Dict[int, List[Dict[str, Any]]] = {}
        # Множество активных миграций
        self._active_migrations: Set[int] = set()
        # Блокировка для потокобезопасности
        self._lock = asyncio.Lock()

    async def start_migration(self, link_id: int) -> None:
        """
        Начать миграцию для связи.

        Args:
            link_id: ID связи для миграции
        """
        async with self._lock:
            self._active_migrations.add(link_id)
            if link_id not in self._queues:
                self._queues[link_id] = []
            logger.info("migration_started", link_id=link_id)

    async def stop_migration(self, link_id: int) -> None:
        """
        Остановить миграцию для связи.

        Args:
            link_id: ID связи для миграции
        """
        async with self._lock:
            self._active_migrations.discard(link_id)
            logger.info("migration_stopped", link_id=link_id)

    async def is_migrating(self, link_id: int) -> bool:
        """
        Проверить, идет ли миграция для связи.

        Args:
            link_id: ID связи для проверки

        Returns:
            True если миграция активна, False в противном случае
        """
        async with self._lock:
            return link_id in self._active_migrations

    async def add_message(self, link_id: int, message_data: Dict[str, Any]) -> None:
        """
        Добавить сообщение в очередь для связи.

        Args:
            link_id: ID связи
            message_data: Данные сообщения для очереди
        """
        async with self._lock:
            if link_id not in self._queues:
                self._queues[link_id] = []
            self._queues[link_id].append(message_data)
            logger.debug("message_added_to_migration_queue", link_id=link_id, queue_size=len(self._queues[link_id]))

    async def get_queued_messages(self, link_id: int) -> List[Dict[str, Any]]:
        """
        Получить все сообщения из очереди для связи.

        Args:
            link_id: ID связи

        Returns:
            Список сообщений из очереди
        """
        async with self._lock:
            messages = self._queues.get(link_id, [])
            return messages.copy()

    async def clear_queue(self, link_id: int) -> None:
        """
        Очистить очередь для связи.

        Args:
            link_id: ID связи
        """
        async with self._lock:
            if link_id in self._queues:
                self._queues[link_id] = []
                logger.info("migration_queue_cleared", link_id=link_id)


# Глобальный экземпляр очереди миграции
migration_queue = MigrationQueue()
