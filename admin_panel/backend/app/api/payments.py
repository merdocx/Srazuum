"""API endpoints для работы с платежами."""

from fastapi import APIRouter, Request, HTTPException, status, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timedelta
import json
import sys
from pathlib import Path

from app.utils.logger import get_logger
from app.core.database import get_db
from app.models.shared import CrosspostingLink, User

router = APIRouter(prefix="/payments", tags=["payments"])
logger = get_logger(__name__)

# Период подписки по умолчанию (в днях)
SUBSCRIPTION_PERIOD_DAYS = 30

# Путь к основному приложению
_project_root = Path(__file__).parent.parent.parent.parent.parent


def _get_parse_webhook():
    """Ленивый импорт parse_webhook из основного приложения."""
    # Добавляем путь к основному приложению
    if str(_project_root) not in sys.path:
        sys.path.insert(0, str(_project_root))

    # Импортируем parse_webhook
    from app.payments.yookassa_client import parse_webhook

    return parse_webhook


@router.post("/webhook")
async def yookassa_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    """
    Обработка webhook от YooKassa.

    YooKassa отправляет уведомления о статусе платежей на этот endpoint.
    """
    try:
        # Получаем тело запроса
        body = await request.json()

        # Парсим webhook (ленивый импорт)
        parse_webhook = _get_parse_webhook()
        webhook_data = parse_webhook(body)
        if not webhook_data:
            logger.error("webhook_parsing_failed", body=body)
            return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content={"error": "Invalid webhook data"})

        payment_id = webhook_data["payment_id"]
        payment_status = webhook_data["status"]
        metadata = webhook_data.get("metadata", {})
        link_id = metadata.get("link_id")
        user_id = metadata.get("user_id")

        logger.info("webhook_processed", payment_id=payment_id, status=payment_status, link_id=link_id, user_id=user_id)

        # Обрабатываем только успешные платежи
        if payment_status == "succeeded":
            if not link_id:
                logger.error("link_id_missing_in_webhook", payment_id=payment_id)
                return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content={"error": "link_id missing in metadata"})

            # Находим связь
            result = await db.execute(select(CrosspostingLink).where(CrosspostingLink.id == int(link_id)))
            link = result.scalar_one_or_none()

            if not link:
                logger.error("link_not_found", link_id=link_id, payment_id=payment_id)
                return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"error": "Link not found"})

            # Проверяем, что платеж еще не обработан
            if link.payment_status == "succeeded":
                logger.warning("payment_already_processed", link_id=link_id, payment_id=payment_id)
                return JSONResponse(status_code=status.HTTP_200_OK, content={"status": "already_processed"})

            # Загружаем пользователя для проверки VIP статуса
            user_result = await db.execute(select(User).where(User.id == link.user_id))
            user = user_result.scalar_one_or_none()

            if user and user.is_vip:
                # VIP пользователи не должны платить, но если платеж пришел - активируем
                logger.warning("payment_for_vip_user", link_id=link_id, user_id=user.id)

            # Активируем связь и продлеваем подписку
            # Если subscription_end_date уже установлена, прибавляем к ней
            # Если нет, устанавливаем новую дату
            now = datetime.utcnow()
            if link.subscription_end_date and link.subscription_end_date > now:
                # Прибавляем к текущей дате окончания
                new_end_date = link.subscription_end_date + timedelta(days=SUBSCRIPTION_PERIOD_DAYS)
            else:
                # Устанавливаем новую дату
                new_end_date = now + timedelta(days=SUBSCRIPTION_PERIOD_DAYS)

            link.subscription_end_date = new_end_date
            link.subscription_status = "active"
            link.is_enabled = True
            link.payment_status = "succeeded"
            link.last_payment_date = now
            link.yookassa_payment_id = payment_id

            await db.commit()

            logger.info(
                "subscription_activated",
                link_id=link.id,
                user_id=user.id if user else None,
                payment_id=payment_id,
                end_date=new_end_date,
            )

            # TODO: Отправить уведомление пользователю через бота об успешной оплате

        elif payment_status == "canceled":
            # Платеж отменен
            if link_id:
                result = await db.execute(select(CrosspostingLink).where(CrosspostingLink.id == int(link_id)))
                link = result.scalar_one_or_none()
                if link:
                    link.payment_status = "canceled"
                    await db.commit()
                    logger.info("payment_canceled", link_id=link_id, payment_id=payment_id)

        return JSONResponse(status_code=status.HTTP_200_OK, content={"status": "ok"})

    except Exception as e:
        logger.error("webhook_processing_error", error=str(e), exc_info=True)
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"error": "Internal server error"})
