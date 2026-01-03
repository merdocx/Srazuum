"""API для управления связями кросспостинга."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import Optional

from app.core.database import get_db
from app.api.auth import get_current_admin
from app.models.admin import Admin
from app.models.shared import CrosspostingLink, TelegramChannel, MaxChannel

router = APIRouter()


@router.get("")
async def get_links(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    user_id: Optional[int] = None,
    is_enabled: Optional[bool] = None,
    telegram_channel_id: Optional[int] = None,
    max_channel_id: Optional[int] = None,
    current_admin: Admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Получить список связей кросспостинга."""
    try:
        query = select(CrosspostingLink)

        if user_id:
            query = query.where(CrosspostingLink.user_id == user_id)
        if is_enabled is not None:
            query = query.where(CrosspostingLink.is_enabled == is_enabled)
        if telegram_channel_id:
            query = query.where(CrosspostingLink.telegram_channel_id == telegram_channel_id)
        if max_channel_id:
            query = query.where(CrosspostingLink.max_channel_id == max_channel_id)

        # Общее количество
        count_result = await db.execute(select(func.count(CrosspostingLink.id)).select_from(query.subquery()))
        total = count_result.scalar() or 0

        # Данные с пагинацией
        query = query.order_by(CrosspostingLink.created_at.desc()).offset(skip).limit(limit)
        result = await db.execute(query)
        links = result.scalars().all()

        # Загружаем связанные данные
        links_data = []
        for link in links:
            # Получаем каналы
            tg_channel_result = await db.execute(select(TelegramChannel).where(TelegramChannel.id == link.telegram_channel_id))
            tg_channel = tg_channel_result.scalar_one_or_none()

            max_channel_result = await db.execute(select(MaxChannel).where(MaxChannel.id == link.max_channel_id))
            max_channel = max_channel_result.scalar_one_or_none()

            links_data.append(
                {
                    "id": link.id,
                    "user_id": link.user_id,
                    "telegram_channel": (
                        {
                            "id": tg_channel.id if tg_channel else None,
                            "title": tg_channel.channel_title if tg_channel else None,
                            "username": tg_channel.channel_username if tg_channel else None,
                        }
                        if tg_channel
                        else None
                    ),
                    "max_channel": (
                        {
                            "id": max_channel.id if max_channel else None,
                            "title": max_channel.channel_title if max_channel else None,
                            "username": max_channel.channel_username if max_channel else None,
                        }
                        if max_channel
                        else None
                    ),
                    "is_enabled": link.is_enabled,
                    "created_at": link.created_at,
                    "updated_at": link.updated_at,
                }
            )

        return {"total": total, "skip": skip, "limit": limit, "data": links_data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка получения связей: {str(e)}")


@router.get("/{link_id}")
async def get_link(link_id: int, current_admin: Admin = Depends(get_current_admin), db: AsyncSession = Depends(get_db)):
    """Получить детальную информацию о связи."""
    try:
        result = await db.execute(select(CrosspostingLink).where(CrosspostingLink.id == link_id))
        link = result.scalar_one_or_none()

        if not link:
            raise HTTPException(status_code=404, detail="Связь не найдена")

        # Получаем каналы
        tg_channel_result = await db.execute(select(TelegramChannel).where(TelegramChannel.id == link.telegram_channel_id))
        tg_channel = tg_channel_result.scalar_one_or_none()

        max_channel_result = await db.execute(select(MaxChannel).where(MaxChannel.id == link.max_channel_id))
        max_channel = max_channel_result.scalar_one_or_none()

        return {
            "id": link.id,
            "user_id": link.user_id,
            "telegram_channel_id": link.telegram_channel_id,
            "max_channel_id": link.max_channel_id,
            "is_enabled": link.is_enabled,
            "created_at": link.created_at,
            "updated_at": link.updated_at,
            "telegram_channel": (
                {
                    "id": tg_channel.id,
                    "channel_id": tg_channel.channel_id,
                    "username": tg_channel.channel_username,
                    "title": tg_channel.channel_title,
                    "is_active": tg_channel.is_active,
                }
                if tg_channel
                else None
            ),
            "max_channel": (
                {
                    "id": max_channel.id,
                    "channel_id": max_channel.channel_id,
                    "username": max_channel.channel_username,
                    "title": max_channel.channel_title,
                    "is_active": max_channel.is_active,
                }
                if max_channel
                else None
            ),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка получения связи: {str(e)}")
