"""API для управления каналами."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import Optional

from app.core.database import get_db
from app.api.auth import get_current_admin
from app.models.admin import Admin
from app.models.shared import TelegramChannel, MaxChannel, CrosspostingLink

router = APIRouter()


@router.get("/telegram")
async def get_telegram_channels(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    user_id: Optional[int] = None,
    is_active: Optional[bool] = None,
    search: Optional[str] = None,
    current_admin: Admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """Получить список Telegram каналов."""
    try:
        query = select(TelegramChannel)
        
        if user_id:
            query = query.where(TelegramChannel.user_id == user_id)
        if is_active is not None:
            query = query.where(TelegramChannel.is_active == is_active)
        if search:
            query = query.where(
                (TelegramChannel.channel_title.ilike(f"%{search}%")) |
                (TelegramChannel.channel_username.ilike(f"%{search}%"))
            )
        
        # Общее количество
        count_result = await db.execute(select(func.count(TelegramChannel.id)).select_from(query.subquery()))
        total = count_result.scalar() or 0
        
        # Данные с пагинацией
        query = query.order_by(TelegramChannel.bot_added_at.desc() if TelegramChannel.bot_added_at else TelegramChannel.id.desc()).offset(skip).limit(limit)
        result = await db.execute(query)
        channels = result.scalars().all()
        
        # Получаем количество связей для каждого канала
        channels_data = []
        for channel in channels:
            links_count = await db.execute(
                select(func.count(CrosspostingLink.id)).where(
                    CrosspostingLink.telegram_channel_id == channel.id
                )
            )
            links = links_count.scalar() or 0
            
            channels_data.append({
                "id": channel.id,
                "user_id": channel.user_id,
                "channel_id": channel.channel_id,
                "channel_username": channel.channel_username,
                "channel_title": channel.channel_title,
                "is_active": channel.is_active,
                "bot_added_at": channel.bot_added_at,
                "links_count": links,
            })
        
        return {
            "total": total,
            "skip": skip,
            "limit": limit,
            "data": channels_data
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка получения каналов: {str(e)}")


@router.get("/telegram/{channel_id}")
async def get_telegram_channel(
    channel_id: int,
    current_admin: Admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """Получить детальную информацию о Telegram канале."""
    try:
        result = await db.execute(
            select(TelegramChannel).where(TelegramChannel.id == channel_id)
        )
        channel = result.scalar_one_or_none()
        
        if not channel:
            raise HTTPException(status_code=404, detail="Канал не найден")
        
        # Получаем связи
        links_result = await db.execute(
            select(CrosspostingLink).where(CrosspostingLink.telegram_channel_id == channel_id)
        )
        links = links_result.scalars().all()
        
        return {
            "id": channel.id,
            "user_id": channel.user_id,
            "channel_id": channel.channel_id,
            "channel_username": channel.channel_username,
            "channel_title": channel.channel_title,
            "is_active": channel.is_active,
            "bot_added_at": channel.bot_added_at,
            "links": [
                {
                    "id": link.id,
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
        raise HTTPException(status_code=500, detail=f"Ошибка получения канала: {str(e)}")


@router.get("/max")
async def get_max_channels(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    user_id: Optional[int] = None,
    is_active: Optional[bool] = None,
    search: Optional[str] = None,
    current_admin: Admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """Получить список MAX каналов."""
    try:
        query = select(MaxChannel)
        
        if user_id:
            query = query.where(MaxChannel.user_id == user_id)
        if is_active is not None:
            query = query.where(MaxChannel.is_active == is_active)
        if search:
            query = query.where(
                (MaxChannel.channel_title.ilike(f"%{search}%")) |
                (MaxChannel.channel_username.ilike(f"%{search}%"))
            )
        
        # Общее количество
        count_result = await db.execute(select(func.count(MaxChannel.id)).select_from(query.subquery()))
        total = count_result.scalar() or 0
        
        # Данные с пагинацией
        query = query.order_by(MaxChannel.bot_added_at.desc() if MaxChannel.bot_added_at else MaxChannel.id.desc()).offset(skip).limit(limit)
        result = await db.execute(query)
        channels = result.scalars().all()
        
        # Получаем количество связей для каждого канала
        channels_data = []
        for channel in channels:
            links_count = await db.execute(
                select(func.count(CrosspostingLink.id)).where(
                    CrosspostingLink.max_channel_id == channel.id
                )
            )
            links = links_count.scalar() or 0
            
            channels_data.append({
                "id": channel.id,
                "user_id": channel.user_id,
                "channel_id": channel.channel_id,
                "channel_username": channel.channel_username,
                "channel_title": channel.channel_title,
                "is_active": channel.is_active,
                "bot_added_at": channel.bot_added_at,
                "links_count": links,
            })
        
        return {
            "total": total,
            "skip": skip,
            "limit": limit,
            "data": channels_data
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка получения каналов: {str(e)}")


@router.get("/max/{channel_id}")
async def get_max_channel(
    channel_id: int,
    current_admin: Admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """Получить детальную информацию о MAX канале."""
    try:
        result = await db.execute(
            select(MaxChannel).where(MaxChannel.id == channel_id)
        )
        channel = result.scalar_one_or_none()
        
        if not channel:
            raise HTTPException(status_code=404, detail="Канал не найден")
        
        # Получаем связи
        links_result = await db.execute(
            select(CrosspostingLink).where(CrosspostingLink.max_channel_id == channel_id)
        )
        links = links_result.scalars().all()
        
        return {
            "id": channel.id,
            "user_id": channel.user_id,
            "channel_id": channel.channel_id,
            "channel_username": channel.channel_username,
            "channel_title": channel.channel_title,
            "is_active": channel.is_active,
            "bot_added_at": channel.bot_added_at,
            "links": [
                {
                    "id": link.id,
                    "telegram_channel_id": link.telegram_channel_id,
                    "is_enabled": link.is_enabled,
                    "created_at": link.created_at,
                }
                for link in links
            ],
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка получения канала: {str(e)}")
