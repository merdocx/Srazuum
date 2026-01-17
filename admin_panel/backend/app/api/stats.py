"""API для статистики."""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from datetime import datetime, timedelta
from typing import Optional
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.database import get_db
from app.api.auth import get_current_admin
from app.models.admin import Admin
from app.models.shared import User, CrosspostingLink, TelegramChannel, MaxChannel, MessageLog, FailedMessage

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)


@router.get("/dashboard")
@limiter.limit("30/1minute")
async def get_dashboard_stats(
    request: Request, current_admin: Admin = Depends(get_current_admin), db: AsyncSession = Depends(get_db)
):
    """Получить статистику для dashboard."""
    try:
        # Количество пользователей
        users_result = await db.execute(select(func.count(User.id)))
        total_users = users_result.scalar() or 0

        # Количество активных связей
        links_result = await db.execute(select(func.count(CrosspostingLink.id)).where(CrosspostingLink.is_enabled == True))
        active_links = links_result.scalar() or 0

        # Количество каналов
        telegram_channels_result = await db.execute(select(func.count(TelegramChannel.id)))
        telegram_channels_count = telegram_channels_result.scalar() or 0

        max_channels_result = await db.execute(select(func.count(MaxChannel.id)))
        max_channels_count = max_channels_result.scalar() or 0

        # Статистика сообщений за последние 24 часа
        yesterday = datetime.utcnow() - timedelta(days=1)
        messages_24h_result = await db.execute(select(func.count(MessageLog.id)).where(MessageLog.created_at >= yesterday))
        messages_24h = messages_24h_result.scalar() or 0

        # Успешные сообщения за 24 часа
        success_24h_result = await db.execute(
            select(func.count(MessageLog.id)).where(MessageLog.created_at >= yesterday, MessageLog.status == "success")
        )
        success_24h = success_24h_result.scalar() or 0

        # Неудачные сообщения за 24 часа
        failed_24h_result = await db.execute(
            select(func.count(MessageLog.id)).where(MessageLog.created_at >= yesterday, MessageLog.status == "failed")
        )
        failed_24h = failed_24h_result.scalar() or 0

        # Всего сообщений
        total_messages_result = await db.execute(select(func.count(MessageLog.id)))
        total_messages = total_messages_result.scalar() or 0

        # Неудачные сообщения (не решенные)
        unresolved_failed_result = await db.execute(
            select(func.count(FailedMessage.id)).where(FailedMessage.resolved_at.is_(None))
        )
        unresolved_failed = unresolved_failed_result.scalar() or 0

        return {
            "users": {
                "total": total_users,
            },
            "links": {
                "active": active_links,
            },
            "channels": {
                "telegram": telegram_channels_count,
                "max": max_channels_count,
                "total": telegram_channels_count + max_channels_count,
            },
            "messages": {
                "total": total_messages,
                "last_24h": messages_24h,
                "success_24h": success_24h,
                "failed_24h": failed_24h,
                "unresolved_failed": unresolved_failed,
            },
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка получения статистики: {str(e)}")


@router.get("/messages")
async def get_messages_stats(
    days: int = 7, current_admin: Admin = Depends(get_current_admin), db: AsyncSession = Depends(get_db)
):
    """Получить статистику сообщений за период."""
    try:
        start_date = datetime.utcnow() - timedelta(days=days)

        # Группировка по дням
        messages_by_day = await db.execute(
            select(func.date(MessageLog.created_at).label("date"), func.count(MessageLog.id).label("count"), MessageLog.status)
            .where(MessageLog.created_at >= start_date)
            .group_by(func.date(MessageLog.created_at), MessageLog.status)
            .order_by(func.date(MessageLog.created_at))
        )

        # Формируем данные для графика
        data = {}
        for row in messages_by_day:
            date_str = row.date.isoformat() if hasattr(row.date, "isoformat") else str(row.date)
            if date_str not in data:
                data[date_str] = {"date": date_str, "success": 0, "failed": 0, "pending": 0, "total": 0}
            data[date_str][row.status] = row.count
            data[date_str]["total"] += row.count

        return {"period_days": days, "data": list(data.values())}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка получения статистики: {str(e)}")
