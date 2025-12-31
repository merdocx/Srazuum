"""Dead Letter Queue для обработки неудачных сообщений."""
import asyncio
from typing import List, Dict, Any
from datetime import datetime, timedelta
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.failed_message import FailedMessage
from app.models.crossposting_link import CrosspostingLink
from app.utils.logger import get_logger
from app.utils.exceptions import APIError
from config.database import async_session_maker
from config.settings import settings

logger = get_logger(__name__)


class DeadLetterQueue:
    """Очередь для повторной обработки неудачных сообщений."""
    
    def __init__(self, max_retries: int = 3, retry_delay_minutes: int = 5):
        """
        Инициализация DLQ.
        
        Args:
            max_retries: Максимальное количество попыток
            retry_delay_minutes: Задержка между попытками (минуты)
        """
        self.max_retries = max_retries
        self.retry_delay_minutes = retry_delay_minutes
    
    async def get_pending_messages(self, limit: int = 10) -> List[FailedMessage]:
        """
        Получить сообщения для повторной обработки.
        
        Args:
            limit: Максимальное количество сообщений
        
        Returns:
            Список сообщений для обработки
        """
        try:
            async with async_session_maker() as session:
                cutoff_time = datetime.utcnow() - timedelta(minutes=self.retry_delay_minutes)
                
                result = await session.execute(
                    select(FailedMessage)
                    .where(FailedMessage.retry_count < self.max_retries)
                    .where(
                        (FailedMessage.last_retry_at.is_(None)) |
                        (FailedMessage.last_retry_at < cutoff_time)
                    )
                    .where(FailedMessage.resolved_at.is_(None))
                    .limit(limit)
                )
                
                return result.scalars().all()
        except Exception as e:
            logger.error("failed_to_get_pending_messages", error=str(e), exc_info=True)
            return []
    
    async def mark_retry(self, failed_message_id: int, error_message: str = None):
        """
        Отметить попытку повторной обработки.
        
        Args:
            failed_message_id: ID неудачного сообщения
            error_message: Сообщение об ошибке (если повторная попытка не удалась)
        """
        try:
            async with async_session_maker() as session:
                async with session.begin():
                    result = await session.execute(
                        select(FailedMessage).where(FailedMessage.id == failed_message_id)
                    )
                    failed_message = result.scalar_one_or_none()
                    
                    if failed_message:
                        failed_message.retry_count += 1
                        failed_message.last_retry_at = datetime.utcnow()
                        if error_message:
                            failed_message.error_message = error_message
        except Exception as e:
            logger.error("failed_to_mark_retry", failed_message_id=failed_message_id, error=str(e))
    
    async def mark_resolved(self, failed_message_id: int):
        """
        Отметить сообщение как обработанное.
        
        Args:
            failed_message_id: ID неудачного сообщения
        """
        try:
            async with async_session_maker() as session:
                async with session.begin():
                    result = await session.execute(
                        select(FailedMessage).where(FailedMessage.id == failed_message_id)
                    )
                    failed_message = result.scalar_one_or_none()
                    
                    if failed_message:
                        failed_message.resolved_at = datetime.utcnow()
        except Exception as e:
            logger.error("failed_to_mark_resolved", failed_message_id=failed_message_id, error=str(e))


# Глобальный экземпляр
dlq = DeadLetterQueue(max_retries=settings.max_retry_attempts, retry_delay_minutes=5)


