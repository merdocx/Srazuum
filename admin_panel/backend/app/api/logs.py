"""API для логов."""

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from datetime import datetime, timedelta
from typing import Optional
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.database import get_db
from app.api.auth import get_current_admin
from app.models.admin import Admin
from app.models.shared import MessageLog, FailedMessage, AuditLog, CrosspostingLink

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)


@router.get("/messages")
@limiter.limit("30/1minute")
async def get_message_logs(
    request: Request,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    link_id: Optional[int] = None,
    status: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    current_admin: Admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Получить логи сообщений."""
    try:
        # Фильтруем только логи с существующими связями
        query = select(MessageLog).join(CrosspostingLink, MessageLog.crossposting_link_id == CrosspostingLink.id)

        if link_id:
            query = query.where(MessageLog.crossposting_link_id == link_id)
        if status:
            query = query.where(MessageLog.status == status)
        if start_date:
            start = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
            query = query.where(MessageLog.created_at >= start)
        if end_date:
            end = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
            query = query.where(MessageLog.created_at <= end)

        # Общее количество
        count_result = await db.execute(select(func.count(MessageLog.id)).select_from(query.subquery()))
        total = count_result.scalar() or 0

        # Данные с пагинацией
        query = query.order_by(MessageLog.created_at.desc()).offset(skip).limit(limit)
        result = await db.execute(query)
        logs = result.scalars().all()

        logs_data = [
            {
                "id": log.id,
                "crossposting_link_id": log.crossposting_link_id,
                "telegram_message_id": log.telegram_message_id,
                "max_message_id": log.max_message_id,
                "status": log.status,
                "error_message": log.error_message,
                "message_type": log.message_type,
                "file_size": log.file_size,
                "processing_time_ms": log.processing_time_ms,
                "created_at": log.created_at,
                "sent_at": log.sent_at,
            }
            for log in logs
        ]

        return {"total": total, "skip": skip, "limit": limit, "data": logs_data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка получения логов: {str(e)}")


@router.get("/messages/{log_id}")
@limiter.limit("30/1minute")
async def get_message_log(
    request: Request, log_id: int, current_admin: Admin = Depends(get_current_admin), db: AsyncSession = Depends(get_db)
):
    """Получить детальную информацию о логе сообщения."""
    try:
        result = await db.execute(select(MessageLog).where(MessageLog.id == log_id))
        log = result.scalar_one_or_none()

        if not log:
            raise HTTPException(status_code=404, detail="Лог не найден")

        # Получаем связь
        link_result = await db.execute(select(CrosspostingLink).where(CrosspostingLink.id == log.crossposting_link_id))
        link = link_result.scalar_one_or_none()

        return {
            "id": log.id,
            "crossposting_link_id": log.crossposting_link_id,
            "telegram_message_id": log.telegram_message_id,
            "max_message_id": log.max_message_id,
            "status": log.status,
            "error_message": log.error_message,
            "message_type": log.message_type,
            "file_size": log.file_size,
            "processing_time_ms": log.processing_time_ms,
            "created_at": log.created_at,
            "sent_at": log.sent_at,
            "link": (
                {
                    "id": link.id,
                    "is_enabled": link.is_enabled,
                }
                if link
                else None
            ),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка получения лога: {str(e)}")


@router.get("/failed")
@limiter.limit("30/1minute")
async def get_failed_messages(
    request: Request,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    link_id: Optional[int] = None,
    resolved: Optional[bool] = None,
    current_admin: Admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Получить список неудачных сообщений."""
    try:
        # Фильтруем только логи с существующими связями
        query = select(FailedMessage).join(CrosspostingLink, FailedMessage.crossposting_link_id == CrosspostingLink.id)

        if link_id:
            query = query.where(FailedMessage.crossposting_link_id == link_id)
        if resolved is not None:
            if resolved:
                query = query.where(FailedMessage.resolved_at.isnot(None))
            else:
                query = query.where(FailedMessage.resolved_at.is_(None))

        # Общее количество
        count_result = await db.execute(select(func.count(FailedMessage.id)).select_from(query.subquery()))
        total = count_result.scalar() or 0

        # Данные с пагинацией
        query = query.order_by(FailedMessage.created_at.desc()).offset(skip).limit(limit)
        result = await db.execute(query)
        failed_messages = result.scalars().all()

        failed_data = [
            {
                "id": fm.id,
                "crossposting_link_id": fm.crossposting_link_id,
                "telegram_message_id": fm.telegram_message_id,
                "error_message": fm.error_message,
                "retry_count": fm.retry_count,
                "last_retry_at": fm.last_retry_at,
                "created_at": fm.created_at,
                "resolved_at": fm.resolved_at,
                "is_resolved": fm.resolved_at is not None,
            }
            for fm in failed_messages
        ]

        return {"total": total, "skip": skip, "limit": limit, "data": failed_data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка получения неудачных сообщений: {str(e)}")


@router.get("/audit")
@limiter.limit("30/1minute")
async def get_audit_logs(
    request: Request,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    user_id: Optional[int] = None,
    action: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    current_admin: Admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Получить логи аудита."""
    try:
        query = select(AuditLog)

        if user_id:
            query = query.where(AuditLog.user_id == user_id)
        if action:
            query = query.where(AuditLog.action == action)
        if start_date:
            start = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
            query = query.where(AuditLog.created_at >= start)
        if end_date:
            end = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
            query = query.where(AuditLog.created_at <= end)

        # Общее количество
        count_result = await db.execute(select(func.count(AuditLog.id)).select_from(query.subquery()))
        total = count_result.scalar() or 0

        # Данные с пагинацией
        query = query.order_by(AuditLog.created_at.desc()).offset(skip).limit(limit)
        result = await db.execute(query)
        logs = result.scalars().all()

        logs_data = [
            {
                "id": log.id,
                "user_id": log.user_id,
                "action": log.action,
                "entity_type": log.entity_type,
                "entity_id": log.entity_id,
                "details": log.details,
                "created_at": log.created_at,
            }
            for log in logs
        ]

        return {"total": total, "skip": skip, "limit": limit, "data": logs_data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка получения логов аудита: {str(e)}")
