"""Фоновые задачи для управления подписками."""

import asyncio
from datetime import datetime, timedelta
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_
from sqlalchemy.orm import selectinload

from app.models.user import User
from app.models.crossposting_link import CrosspostingLink
from config.database import async_session_maker
from config.settings import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def check_expired_subscriptions():
    """Проверить и деактивировать истекшие подписки."""
    async with async_session_maker() as session:
        now = datetime.utcnow()

        # Находим связи с истекшими подписками (исключая VIP)
        # Ищем связи, где:
        # 1. subscription_status не 'vip'
        # 2. is_enabled = True
        # 3. (subscription_end_date < now ИЛИ free_trial_end_date < now)
        result = await session.execute(
            select(CrosspostingLink)
            .options(selectinload(CrosspostingLink.user))
            .where(
                CrosspostingLink.subscription_status != "vip",
                CrosspostingLink.is_enabled == True,
                or_(
                    and_(CrosspostingLink.subscription_end_date.isnot(None), CrosspostingLink.subscription_end_date < now),
                    and_(CrosspostingLink.free_trial_end_date.isnot(None), CrosspostingLink.free_trial_end_date < now),
                ),
            )
        )
        expired_links = result.scalars().all()

        if not expired_links:
            logger.info("no_expired_subscriptions")
            return

        deactivated_count = 0
        for link in expired_links:
            # Проверяем, что пользователь не VIP (на случай если статус изменился)
            if link.user and link.user.is_vip:
                logger.warning("skipping_vip_user_link", link_id=link.id, user_id=link.user.id)
                continue

            link.is_enabled = False
            link.subscription_status = "expired"
            deactivated_count += 1
            logger.info("subscription_deactivated", link_id=link.id, user_id=link.user_id)

        await session.commit()
        logger.info("expired_subscriptions_processed", count=deactivated_count)


async def send_renewal_notifications(bot_instance=None):
    """Отправить уведомления о необходимости продления подписки."""
    if not bot_instance:
        # Пытаемся получить бота из глобального контекста
        try:
            from app.bot.main import get_bot_instance

            bot_instance = get_bot_instance()
        except:
            logger.warning("bot_not_available_for_notifications")
            return

    if not bot_instance:
        logger.warning("bot_not_initialized")
        return

    async with async_session_maker() as session:
        now = datetime.utcnow()

        # Определяем временные метки для уведомлений
        notification_intervals = [timedelta(days=7), timedelta(days=3), timedelta(days=1), timedelta(hours=1)]

        notifications_sent = 0

        # Находим активные связи (не VIP, активные)
        result = await session.execute(
            select(CrosspostingLink)
            .options(selectinload(CrosspostingLink.user))
            .where(
                CrosspostingLink.subscription_status != "vip",
                CrosspostingLink.is_enabled == True,
                or_(CrosspostingLink.subscription_end_date.isnot(None), CrosspostingLink.free_trial_end_date.isnot(None)),
            )
        )
        links = result.scalars().all()

        for link in links:
            # Пропускаем VIP пользователей
            if link.user and link.user.is_vip:
                continue

            # Определяем дату окончания
            end_date = link.subscription_end_date or link.free_trial_end_date
            if not end_date:
                continue

            # Проверяем, нужно ли отправить уведомление
            time_until_expiry = end_date - now

            # Проверяем каждый интервал
            for interval in notification_intervals:
                # Если время до окончания попадает в интервал (с точностью до 5 минут)
                if timedelta(minutes=0) < time_until_expiry <= interval + timedelta(minutes=5):
                    # TODO: Проверять, не отправлялось ли уже уведомление для этого интервала
                    # Пока отправляем все уведомления

                    # Форматируем время до окончания
                    if time_until_expiry.days > 0:
                        time_text = f"{time_until_expiry.days} дней"
                    else:
                        hours = time_until_expiry.seconds // 3600
                        time_text = f"{hours} часов"

                    # Формируем сообщение
                    notification_text = (
                        f"📢 Напоминание о продлении подписки\n\n"
                        f"Связь: #{link.id}\n"
                        f"Истекает через: {time_text}\n\n"
                        f"Продлите подписку сейчас, чтобы не прерывать кросспостинг.\n\n"
                        f"💳 Продлить подписку - /pay_link {link.id}\n"
                        f"📋 Мои связи - /my_subscriptions"
                    )

                    try:
                        await bot_instance.send_message(chat_id=link.user.telegram_id, text=notification_text)
                        notifications_sent += 1
                        logger.info(
                            "renewal_notification_sent", link_id=link.id, user_id=link.user_id, time_until_expiry=time_text
                        )
                        # Отправляем только одно уведомление за раз
                        break
                    except Exception as e:
                        logger.error("renewal_notification_failed", link_id=link.id, user_id=link.user_id, error=str(e))

        logger.info("renewal_notifications_processed", count=notifications_sent)


async def subscription_tasks_worker(interval_seconds: int = 300, bot_instance=None):
    """
    Фоновый воркер для задач подписок.

    Args:
        interval_seconds: Интервал проверки в секундах (по умолчанию 5 минут)
        bot_instance: Экземпляр бота для отправки уведомлений
    """
    logger.info("subscription_tasks_worker_started", interval_seconds=interval_seconds)

    while True:
        try:
            # Проверяем истекшие подписки
            await check_expired_subscriptions()

            # Отправляем уведомления о продлении
            await send_renewal_notifications(bot_instance=bot_instance)

            # Ждем перед следующей проверкой
            await asyncio.sleep(interval_seconds)

        except Exception as e:
            logger.error("subscription_tasks_worker_error", error=str(e), exc_info=True)
            # В случае ошибки ждем перед повтором
            await asyncio.sleep(interval_seconds)
