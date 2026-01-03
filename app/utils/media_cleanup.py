"""Автоматическая очистка медиа-файлов."""

import asyncio
from app.utils.media_handler import cleanup_old_media_files
from app.utils.logger import get_logger
from config.settings import settings

logger = get_logger(__name__)


async def periodic_media_cleanup():
    """
    Периодическая очистка старых медиа-файлов.
    Запускается в фоновом режиме.
    """
    cleanup_interval = settings.media_cleanup_interval_seconds
    max_age_hours = settings.media_cleanup_after_seconds // 3600

    logger.info("media_cleanup_scheduler_started", interval_seconds=cleanup_interval, max_age_hours=max_age_hours)

    while True:
        try:
            await asyncio.sleep(cleanup_interval)

            deleted_count = await cleanup_old_media_files(max_age_hours)

            if deleted_count > 0:
                logger.info("periodic_cleanup_completed", deleted_count=deleted_count, max_age_hours=max_age_hours)
        except Exception as e:
            logger.error("periodic_cleanup_error", error=str(e), exc_info=True)
            # Продолжаем работу даже при ошибке
            await asyncio.sleep(60)  # Короткая пауза перед следующей попыткой
