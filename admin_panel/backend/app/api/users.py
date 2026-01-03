"""API для управления пользователями."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import Optional
import sys
from pathlib import Path

# Добавляем путь к основному приложению для импорта logger
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))
from app.utils.logger import get_logger

from app.core.database import get_db
from app.api.auth import get_current_admin
from app.models.admin import Admin
from app.models.shared import User, TelegramChannel, MaxChannel, CrosspostingLink

logger = get_logger(__name__)

router = APIRouter()


@router.get("")
async def get_users(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    search: Optional[str] = None,
    current_admin: Admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Получить список пользователей."""
    try:
        query = select(User)

        if search:
            query = query.where(
                (User.telegram_username.ilike(f"%{search}%")) | (User.telegram_user_id.cast(str).like(f"%{search}%"))
            )

        # Общее количество
        count_result = await db.execute(select(func.count(User.id)).select_from(query.subquery()))
        total = count_result.scalar() or 0

        # Данные с пагинацией
        query = query.order_by(User.created_at.desc()).offset(skip).limit(limit)
        result = await db.execute(query)
        users = result.scalars().all()

        # Получаем статистику для каждого пользователя
        users_data = []
        for user in users:
            # Количество каналов
            telegram_channels_count = await db.execute(
                select(func.count(TelegramChannel.id)).where(TelegramChannel.user_id == user.id)
            )
            tg_count = telegram_channels_count.scalar() or 0

            max_channels_count = await db.execute(select(func.count(MaxChannel.id)).where(MaxChannel.user_id == user.id))
            max_count = max_channels_count.scalar() or 0

            # Количество связей
            links_count = await db.execute(select(func.count(CrosspostingLink.id)).where(CrosspostingLink.user_id == user.id))
            links = links_count.scalar() or 0

            users_data.append(
                {
                    "id": user.id,
                    "telegram_user_id": user.telegram_user_id,
                    "telegram_username": user.telegram_username,
                    "created_at": user.created_at,
                    "updated_at": user.updated_at,
                    "channels_count": tg_count + max_count,
                    "links_count": links,
                }
            )

        return {"total": total, "skip": skip, "limit": limit, "data": users_data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка получения пользователей: {str(e)}")


@router.get("/{user_id}")
async def get_user(user_id: int, current_admin: Admin = Depends(get_current_admin), db: AsyncSession = Depends(get_db)):
    """Получить детальную информацию о пользователе."""
    try:
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()

        if not user:
            raise HTTPException(status_code=404, detail="Пользователь не найден")

        # Получаем каналы
        telegram_channels_result = await db.execute(select(TelegramChannel).where(TelegramChannel.user_id == user.id))
        telegram_channels = telegram_channels_result.scalars().all()

        max_channels_result = await db.execute(select(MaxChannel).where(MaxChannel.user_id == user.id))
        max_channels = max_channels_result.scalars().all()

        # Получаем связи
        links_result = await db.execute(select(CrosspostingLink).where(CrosspostingLink.user_id == user.id))
        links = links_result.scalars().all()

        return {
            "id": user.id,
            "telegram_user_id": user.telegram_user_id,
            "telegram_username": user.telegram_username,
            "created_at": user.created_at,
            "updated_at": user.updated_at,
            "telegram_channels": [
                {
                    "id": ch.id,
                    "channel_id": ch.channel_id,
                    "username": ch.channel_username,
                    "title": ch.channel_title,
                    "is_active": ch.is_active,
                }
                for ch in telegram_channels
            ],
            "max_channels": [
                {
                    "id": ch.id,
                    "channel_id": ch.channel_id,
                    "username": ch.channel_username,
                    "title": ch.channel_title,
                    "is_active": ch.is_active,
                }
                for ch in max_channels
            ],
            "links": [
                {
                    "id": link.id,
                    "telegram_channel_id": link.telegram_channel_id,
                    "max_channel_id": link.max_channel_id,
                    "is_enabled": link.is_enabled,
                    "created_at": link.created_at,
                }
                for link in links
            ],
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка получения пользователя: {str(e)}")
