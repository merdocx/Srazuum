"""API для управления пользователями."""

from fastapi import APIRouter, Depends, HTTPException, Query, Body, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_, and_, String
from typing import Optional
from pydantic import BaseModel
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.utils.logger import get_logger
from app.core.database import get_db
from app.api.auth import get_current_admin
from app.models.admin import Admin
from app.models.shared import User, TelegramChannel, MaxChannel, CrosspostingLink

logger = get_logger(__name__)

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)


class UpdateVIPStatusRequest(BaseModel):
    is_vip: bool


@router.get("")
@limiter.limit("60/1minute")
async def get_users(
    request: Request,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    search: Optional[str] = None,
    is_vip: Optional[bool] = None,
    current_admin: Admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Получить список пользователей."""
    try:
        query = select(User)

        # Поиск по ключевым полям: Telegram ID, Username, E-mail
        if search:
            search_conditions = []

            # Поиск по username (если не NULL)
            search_conditions.append(and_(User.telegram_username.isnot(None), User.telegram_username.ilike(f"%{search}%")))

            # Поиск по email (если не NULL)
            search_conditions.append(and_(User.email.isnot(None), User.email.ilike(f"%{search}%")))

            # Поиск по telegram_user_id (если search - число)
            try:
                search_int = int(search)
                search_conditions.append(User.telegram_user_id == search_int)
            except ValueError:
                # Если search не число, ищем по строковому представлению через cast
                search_conditions.append(func.cast(User.telegram_user_id, String).like(f"%{search}%"))

            query = query.where(or_(*search_conditions))

        # Фильтр по VIP статусу
        if is_vip is not None:
            query = query.where(User.is_vip == is_vip)

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
                    "email": user.email,
                    "is_vip": user.is_vip,
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
@limiter.limit("60/1minute")
async def get_user(
    request: Request, user_id: int, current_admin: Admin = Depends(get_current_admin), db: AsyncSession = Depends(get_db)
):
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
            "email": user.email,
            "is_vip": user.is_vip,
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


@router.patch("/{user_id}/vip")
@limiter.limit("60/1minute")
async def update_user_vip_status(
    request: Request,
    user_id: int,
    body: UpdateVIPStatusRequest = Body(...),
    current_admin: Admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Обновить VIP статус пользователя."""
    try:
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()

        if not user:
            raise HTTPException(status_code=404, detail="Пользователь не найден")

        user.is_vip = body.is_vip
        await db.commit()
        await db.refresh(user)

        logger.info(f"user_vip_status_updated: user_id={user_id}, is_vip={body.is_vip}, admin_id={current_admin.id}")

        return {"id": user.id, "telegram_user_id": user.telegram_user_id, "is_vip": user.is_vip}
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"error_updating_user_vip_status: user_id={user_id}, error={str(e)}")
        raise HTTPException(status_code=500, detail=f"Ошибка обновления VIP статуса: {str(e)}")
