#!/usr/bin/env python3
"""Скрипт для очистки неиспользуемых каналов (без связей)."""
import asyncio
import sys
from pathlib import Path

# Добавляем корневую директорию проекта в путь
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import text, delete
from sqlalchemy.ext.asyncio import AsyncSession
from config.database import async_session_maker
from app.models.telegram_channel import TelegramChannel
from app.models.max_channel import MaxChannel
from app.models.crossposting_link import CrosspostingLink
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def cleanup_orphaned_channels(dry_run: bool = False) -> tuple[int, int]:
    """
    Удалить каналы, которые не используются в связях.
    
    Args:
        dry_run: Если True, только показывает что будет удалено, без удаления
    
    Returns:
        Кортеж (количество удаленных Telegram каналов, количество удаленных MAX каналов)
    """
    async with async_session_maker() as session:
        # Находим MAX каналы без связей
        max_channels_result = await session.execute(text("""
            SELECT mc.id, mc.channel_id, mc.channel_username, mc.channel_title
            FROM max_channels mc
            LEFT JOIN crossposting_links cl ON cl.max_channel_id = mc.id
            GROUP BY mc.id, mc.channel_id, mc.channel_username, mc.channel_title
            HAVING COUNT(cl.id) = 0
        """))
        orphaned_max_channels = max_channels_result.fetchall()
        
        # Находим Telegram каналы без связей
        telegram_channels_result = await session.execute(text("""
            SELECT tc.id, tc.channel_id, tc.channel_username, tc.channel_title
            FROM telegram_channels tc
            LEFT JOIN crossposting_links cl ON cl.telegram_channel_id = tc.id
            GROUP BY tc.id, tc.channel_id, tc.channel_username, tc.channel_title
            HAVING COUNT(cl.id) = 0
        """))
        orphaned_telegram_channels = telegram_channels_result.fetchall()
        
        print(f"\n=== Найдено неиспользуемых каналов ===")
        print(f"MAX каналы: {len(orphaned_max_channels)}")
        print(f"Telegram каналы: {len(orphaned_telegram_channels)}")
        
        if len(orphaned_max_channels) > 0:
            print(f"\nMAX каналы для удаления:")
            for row in orphaned_max_channels:
                print(f"  ID: {row[0]}, channel_id: {row[1]}, username: {row[2]}, title: {row[3]}")
        
        if len(orphaned_telegram_channels) > 0:
            print(f"\nTelegram каналы для удаления:")
            for row in orphaned_telegram_channels:
                print(f"  ID: {row[0]}, channel_id: {row[1]}, username: {row[2]}, title: {row[3]}")
        
        if dry_run:
            print("\n⚠️  DRY RUN: изменения не применены")
            return len(orphaned_telegram_channels), len(orphaned_max_channels)
        
        # Удаляем MAX каналы
        deleted_max_count = 0
        if orphaned_max_channels:
            max_ids = [row[0] for row in orphaned_max_channels]
            result = await session.execute(
                delete(MaxChannel).where(MaxChannel.id.in_(max_ids))
            )
            deleted_max_count = result.rowcount
            logger.info("orphaned_max_channels_deleted", count=deleted_max_count, channel_ids=max_ids)
        
        # Удаляем Telegram каналы
        deleted_telegram_count = 0
        if orphaned_telegram_channels:
            telegram_ids = [row[0] for row in orphaned_telegram_channels]
            result = await session.execute(
                delete(TelegramChannel).where(TelegramChannel.id.in_(telegram_ids))
            )
            deleted_telegram_count = result.rowcount
            logger.info("orphaned_telegram_channels_deleted", count=deleted_telegram_count, channel_ids=telegram_ids)
        
        await session.commit()
        
        print(f"\n✅ Удалено:")
        print(f"  MAX каналов: {deleted_max_count}")
        print(f"  Telegram каналов: {deleted_telegram_count}")
        
        return deleted_telegram_count, deleted_max_count


async def main():
    """Основная функция."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Очистка неиспользуемых каналов")
    parser.add_argument("--dry-run", action="store_true", help="Показать что будет удалено без удаления")
    args = parser.parse_args()
    
    try:
        deleted_tg, deleted_max = await cleanup_orphaned_channels(dry_run=args.dry_run)
        sys.exit(0)
    except Exception as e:
        logger.error("cleanup_orphaned_channels_error", error=str(e), exc_info=True)
        print(f"\n❌ Ошибка: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())

