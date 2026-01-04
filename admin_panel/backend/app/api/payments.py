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

router = APIRouter(tags=["payments"])
logger = get_logger(__name__)

# Период подписки по умолчанию (в днях)
SUBSCRIPTION_PERIOD_DAYS = 30

# Путь к основному приложению
_project_root = Path(__file__).parent.parent.parent.parent.parent


def _get_parse_webhook():
    """Ленивый импорт parse_webhook из основного приложения."""
    import importlib.util

    # Добавляем путь к основному приложению
    if str(_project_root) not in sys.path:
        sys.path.insert(0, str(_project_root))

    # Используем importlib для динамического импорта
    yookassa_client_path = _project_root / "app" / "payments" / "yookassa_client.py"
    spec = importlib.util.spec_from_file_location("yookassa_client", yookassa_client_path)
    yookassa_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(yookassa_module)

    return yookassa_module.parse_webhook


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
            logger.error(f"webhook_parsing_failed: body={body}")
            return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content={"error": "Invalid webhook data"})

        payment_id = webhook_data["payment_id"]
        payment_status = webhook_data["status"]
        metadata = webhook_data.get("metadata", {})
        link_id = metadata.get("link_id")
        user_id = metadata.get("user_id")

        logger.info(
            f"webhook_processed: payment_id={payment_id}, status={payment_status}, link_id={link_id}, user_id={user_id}"
        )

        # Обрабатываем только успешные платежи
        if payment_status == "succeeded":
            if not link_id:
                logger.error(f"link_id_missing_in_webhook: payment_id={payment_id}")
                return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content={"error": "link_id missing in metadata"})

            # Находим связь
            result = await db.execute(select(CrosspostingLink).where(CrosspostingLink.id == int(link_id)))
            link = result.scalar_one_or_none()

            if not link:
                logger.error(f"link_not_found: link_id={link_id}, payment_id={payment_id}")
                return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"error": "Link not found"})

            # Проверяем, что платеж еще не обработан
            if link.payment_status == "succeeded":
                logger.warning(f"payment_already_processed: link_id={link_id}, payment_id={payment_id}")
                return JSONResponse(status_code=status.HTTP_200_OK, content={"status": "already_processed"})

            # Загружаем пользователя для проверки VIP статуса
            user_result = await db.execute(select(User).where(User.id == link.user_id))
            user = user_result.scalar_one_or_none()

            if user and user.is_vip:
                # VIP пользователи не должны платить, но если платеж пришел - активируем
                logger.warning(f"payment_for_vip_user: link_id={link_id}, user_id={user.id}")

                # Активируем связь и продлеваем подписку
                # Если subscription_end_date уже установлена, прибавляем к ней
                # Если нет, но есть free_trial_end_date (для первой связи), прибавляем к ней
                # Иначе устанавливаем новую дату от now
                now = datetime.utcnow()
                if link.subscription_end_date and link.subscription_end_date > now:
                    # Прибавляем к текущей дате окончания платной подписки
                    new_end_date = link.subscription_end_date + timedelta(days=SUBSCRIPTION_PERIOD_DAYS)
                elif link.free_trial_end_date and link.free_trial_end_date > now:
                    # Для первой связи: прибавляем к дате окончания бесплатного периода
                    new_end_date = link.free_trial_end_date + timedelta(days=SUBSCRIPTION_PERIOD_DAYS)
                else:
                    # Устанавливаем новую дату от текущего момента
                    new_end_date = now + timedelta(days=SUBSCRIPTION_PERIOD_DAYS)

            link.subscription_end_date = new_end_date
            link.subscription_status = "active"
            link.is_enabled = True
            link.payment_status = "succeeded"
            link.last_payment_date = now
            link.yookassa_payment_id = payment_id

            await db.commit()

            logger.info(
                f"subscription_activated: link_id={link.id}, user_id={user.id if user else None}, payment_id={payment_id}, end_date={new_end_date}"
            )

            # Отправляем уведомление пользователю через бота об успешной оплате
            if user:
                try:
                    # Импортируем Bot и settings для отправки уведомления
                    # Добавляем путь к основному приложению для импорта settings
                    if str(_project_root) not in sys.path:
                        sys.path.insert(0, str(_project_root))

                    from aiogram import Bot
                    from config.settings import settings as app_settings

                    if not app_settings.telegram_bot_token:
                        logger.error(f"telegram_bot_token_not_configured: link_id={link.id}, user_id={user.id}")
                    else:
                        bot = Bot(token=app_settings.telegram_bot_token)

                        # Загружаем информацию о каналах для сообщения
                        from app.models.shared import TelegramChannel, MaxChannel

                        tg_result = await db.execute(
                            select(TelegramChannel).where(TelegramChannel.id == link.telegram_channel_id)
                        )
                        tg_ch = tg_result.scalar_one_or_none()
                        max_result = await db.execute(select(MaxChannel).where(MaxChannel.id == link.max_channel_id))
                        max_ch = max_result.scalar_one_or_none()

                        tg_name = tg_ch.channel_username or tg_ch.channel_title if tg_ch else "N/A"
                        max_name = max_ch.channel_username or max_ch.channel_title if max_ch else "N/A"

                        notification_text = (
                            f"✅ Платеж успешно обработан!\n\n"
                            f"📊 Связь #{link.id}\n"
                            f"Telegram: {tg_name}\n"
                            f"MAX: {max_name}\n\n"
                            f"📅 Подписка продлена до: {new_end_date.strftime('%d.%m.%Y %H:%M')}\n\n"
                            f"Кросспостинг активирован."
                        )

                        await bot.send_message(chat_id=user.telegram_user_id, text=notification_text)
                        await bot.session.close()

                        logger.info(
                            f"payment_notification_sent: link_id={link.id}, user_id={user.id}, telegram_user_id={user.telegram_user_id}"
                        )
                except Exception as notify_error:
                    logger.error(
                        f"failed_to_send_payment_notification: link_id={link.id}, user_id={user.id if user else None}, telegram_user_id={user.telegram_user_id if user else None}, error={str(notify_error)}",
                        exc_info=True,
                    )

        elif payment_status == "canceled":
            # Платеж отменен
            if link_id:
                result = await db.execute(select(CrosspostingLink).where(CrosspostingLink.id == int(link_id)))
                link = result.scalar_one_or_none()
                if link:
                    link.payment_status = "canceled"
                    await db.commit()
                    logger.info(f"payment_canceled: link_id={link_id}, payment_id={payment_id}")

        return JSONResponse(status_code=status.HTTP_200_OK, content={"status": "ok"})

    except Exception as e:
        logger.error(f"webhook_processing_error: {str(e)}", exc_info=True)
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"error": "Internal server error"})
