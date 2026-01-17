"""API endpoints для работы с платежами."""

from fastapi import APIRouter, Request, HTTPException, status, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_, and_, String
from datetime import datetime, timedelta
from typing import Optional
import json
import sys
from pathlib import Path
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.utils.logger import get_logger
from app.utils.ip_checker import is_yookassa_ip, get_client_ip
from app.core.database import get_db
from app.models.shared import CrosspostingLink, User, TelegramChannel, MaxChannel
from app.api.auth import get_current_admin
from app.models.admin import Admin

router = APIRouter(tags=["payments"])
logger = get_logger(__name__)

# Rate limiter для payments endpoints
limiter = Limiter(key_func=get_remote_address)

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
@limiter.limit("100/1minute")
async def yookassa_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    """
    Обработка webhook от YooKassa.

    YooKassa отправляет уведомления о статусе платежей на этот endpoint.
    """
    try:
        # Проверяем IP-адрес отправителя
        client_ip = get_client_ip(request)
        if not is_yookassa_ip(client_ip):
            logger.warning(f"webhook_rejected_invalid_ip: ip={client_ip}")
            return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content={"error": "Forbidden: Invalid source IP"})

        # Получаем тело запроса
        body = await request.json()

        # Парсим webhook (ленивый импорт)
        parse_webhook = _get_parse_webhook()
        webhook_data = parse_webhook(body)
        if not webhook_data:
            logger.error(f"webhook_parsing_failed: ip={client_ip}")
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

            # Проверяем условия для предложения миграции (ДО изменения last_payment_date)
            # Условия: первая оплата (last_payment_date == None), не первая связь, миграция еще не предлагалась
            is_first_payment = link.last_payment_date is None
            should_offer_migration = is_first_payment and not link.is_first_link and not link.migration_offered

            # Активируем связь и продлеваем подписку
            # Определяем базовую дату, от которой будет отсчитываться продление
            # Если есть активная платная подписка, продлеваем от ее конца
            # Если есть активный бесплатный период (для первой связи), продлеваем от его конца
            # Иначе продлеваем от текущего момента
            now = datetime.utcnow()
            base_date = now
            if link.subscription_end_date and link.subscription_end_date > now:
                base_date = link.subscription_end_date
            elif link.is_first_link and link.free_trial_end_date and link.free_trial_end_date > now:
                base_date = link.free_trial_end_date

            new_end_date = base_date + timedelta(days=SUBSCRIPTION_PERIOD_DAYS)

            if user and user.is_vip:
                # VIP пользователи не должны платить, но если платеж пришел - активируем
                logger.warning(f"payment_for_vip_user: link_id={link_id}, user_id={user.id}")

            link.subscription_end_date = new_end_date
            link.subscription_status = "active"
            link.is_enabled = True
            link.payment_status = "succeeded"
            link.last_payment_date = now
            link.yookassa_payment_id = payment_id
            # Устанавливаем флаг, что миграция была предложена (если нужно)
            if should_offer_migration:
                link.migration_offered = True

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

                        # Ленивый импорт keyboards из основного приложения
                        import importlib.util

                        keyboards_path = _project_root / "app" / "bot" / "keyboards.py"
                        keyboards_spec = importlib.util.spec_from_file_location("keyboards", keyboards_path)
                        keyboards_module = importlib.util.module_from_spec(keyboards_spec)
                        keyboards_spec.loader.exec_module(keyboards_module)
                        get_main_keyboard = keyboards_module.get_main_keyboard

                        tg_result = await db.execute(
                            select(TelegramChannel).where(TelegramChannel.id == link.telegram_channel_id)
                        )
                        tg_ch = tg_result.scalar_one_or_none()
                        max_result = await db.execute(select(MaxChannel).where(MaxChannel.id == link.max_channel_id))
                        max_ch = max_result.scalar_one_or_none()

                        tg_name = tg_ch.channel_title or tg_ch.channel_username if tg_ch else "N/A"
                        max_name = max_ch.channel_title or max_ch.channel_username if max_ch else "N/A"

                        notification_text = (
                            f"✅ Платеж успешно обработан!\n\n"
                            f"📊 Связь #{link.id}\n"
                            f"Telegram: {tg_name}\n"
                            f"MAX: {max_name}\n\n"
                            f"📅 Подписка продлена до: {new_end_date.strftime('%d.%m.%Y %H:%M')}\n\n"
                            f"✅ Кросспостинг активирован."
                        )

                        await bot.send_message(
                            chat_id=user.telegram_user_id, text=notification_text, reply_markup=get_main_keyboard()
                        )

                        # Если это первая оплата для не первой связи, предлагаем миграцию
                        if should_offer_migration:
                            try:
                                # Используем уже загруженный модуль keyboards
                                get_migration_offer_keyboard = keyboards_module.get_migration_offer_keyboard

                                migration_text = "Перед началом работы вы можете один раз перенести последние 30 постов из Telegram-канала в MAX-канал."
                                migration_keyboard = get_migration_offer_keyboard(link.id)
                                await bot.send_message(
                                    chat_id=user.telegram_user_id, text=migration_text, reply_markup=migration_keyboard
                                )

                                logger.info(
                                    f"migration_offer_sent_after_payment: link_id={link.id}, user_id={user.id}, telegram_user_id={user.telegram_user_id}"
                                )
                            except Exception as migration_offer_error:
                                logger.error(
                                    f"failed_to_send_migration_offer: link_id={link.id}, user_id={user.id if user else None}, error={str(migration_offer_error)}",
                                    exc_info=True,
                                )

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


def _get_get_payment_status():
    """Ленивый импорт get_payment_status из основного приложения."""
    import importlib.util

    # Добавляем путь к основному приложению
    if str(_project_root) not in sys.path:
        sys.path.insert(0, str(_project_root))

    # Используем importlib для динамического импорта
    yookassa_client_path = _project_root / "app" / "payments" / "yookassa_client.py"
    spec = importlib.util.spec_from_file_location("yookassa_client", yookassa_client_path)
    yookassa_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(yookassa_module)

    return yookassa_module.get_payment_status


@router.get("")
@limiter.limit("60/1minute")
async def get_payments(
    request: Request,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    search: Optional[str] = None,
    status_filter: Optional[str] = None,
    current_admin: Admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Получить список платежей."""
    try:
        # Запрос для связей с платежами (yookassa_payment_id не NULL)
        query = select(CrosspostingLink).where(CrosspostingLink.yookassa_payment_id.isnot(None))

        # Поиск по ключевым полям
        if search:
            search_conditions = []

            # Поиск по yookassa_payment_id
            search_conditions.append(
                and_(
                    CrosspostingLink.yookassa_payment_id.isnot(None), CrosspostingLink.yookassa_payment_id.ilike(f"%{search}%")
                )
            )

            # Поиск по ID связи
            try:
                search_int = int(search)
                search_conditions.append(CrosspostingLink.id == search_int)
            except ValueError:
                search_conditions.append(func.cast(CrosspostingLink.id, String).like(f"%{search}%"))

            # Поиск по telegram_user_id пользователя (через подзапрос)
            try:
                search_int = int(search)
                # Создаем подзапрос для поиска по telegram_user_id
                user_subquery = select(User.id).where(User.telegram_user_id == search_int)
                search_conditions.append(CrosspostingLink.user_id.in_(user_subquery))
            except ValueError:
                # Поиск по username или email пользователя
                user_search_subquery = select(User.id).where(
                    or_(
                        and_(User.telegram_username.isnot(None), User.telegram_username.ilike(f"%{search}%")),
                        and_(User.email.isnot(None), User.email.ilike(f"%{search}%")),
                    )
                )
                search_conditions.append(CrosspostingLink.user_id.in_(user_search_subquery))

            query = query.where(or_(*search_conditions))

        # Фильтр по статусу платежа
        if status_filter:
            query = query.where(CrosspostingLink.payment_status == status_filter)

        # Общее количество
        count_result = await db.execute(select(func.count(CrosspostingLink.id)).select_from(query.subquery()))
        total = count_result.scalar() or 0

        # Данные с пагинацией, сортировка по дате последнего платежа (или created_at)
        query = (
            query.order_by(CrosspostingLink.last_payment_date.desc().nullslast(), CrosspostingLink.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await db.execute(query)
        links = result.scalars().all()

        # Формируем данные о платежах
        payments_data = []
        for link in links:
            # Получаем пользователя
            user_result = await db.execute(select(User).where(User.id == link.user_id))
            user = user_result.scalar_one_or_none()

            # Получаем каналы
            tg_channel_result = await db.execute(select(TelegramChannel).where(TelegramChannel.id == link.telegram_channel_id))
            tg_channel = tg_channel_result.scalar_one_or_none()

            max_channel_result = await db.execute(select(MaxChannel).where(MaxChannel.id == link.max_channel_id))
            max_channel = max_channel_result.scalar_one_or_none()

            payments_data.append(
                {
                    "id": link.id,
                    "yookassa_payment_id": link.yookassa_payment_id,
                    "payment_status": link.payment_status,
                    "last_payment_date": link.last_payment_date,
                    "user": (
                        {
                            "id": user.id if user else None,
                            "telegram_user_id": user.telegram_user_id if user else None,
                            "telegram_username": user.telegram_username if user else None,
                            "email": user.email if user else None,
                        }
                        if user
                        else None
                    ),
                    "link": {
                        "id": link.id,
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
                    },
                    "created_at": link.created_at,
                }
            )

        return {"total": total, "skip": skip, "limit": limit, "data": payments_data}
    except Exception as e:
        logger.error(f"error_getting_payments: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Ошибка получения платежей: {str(e)}")


@router.post("/{payment_id}/sync")
@limiter.limit("30/1minute")
async def sync_payment_status(
    request: Request,
    payment_id: str,
    current_admin: Admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Синхронизировать статус платежа с YooKassa."""
    try:
        # Находим связь по yookassa_payment_id
        result = await db.execute(select(CrosspostingLink).where(CrosspostingLink.yookassa_payment_id == payment_id))
        link = result.scalar_one_or_none()

        if not link:
            raise HTTPException(status_code=404, detail="Платеж не найден")

        # Получаем статус из YooKassa
        get_payment_status = _get_get_payment_status()
        payment_info = get_payment_status(payment_id)

        if not payment_info:
            raise HTTPException(status_code=404, detail="Не удалось получить информацию о платеже из YooKassa")

        # Обновляем статус в БД
        old_status = link.payment_status
        link.payment_status = payment_info["status"]

        # Если платеж успешен и еще не обработан, обновляем дату
        if payment_info["status"] == "succeeded" and not link.last_payment_date:
            link.last_payment_date = datetime.utcnow()

        await db.commit()
        await db.refresh(link)

        logger.info(
            f"payment_status_synced: payment_id={payment_id}, link_id={link.id}, "
            f"old_status={old_status}, new_status={payment_info['status']}, admin_id={current_admin.id}"
        )

        return {
            "payment_id": payment_id,
            "link_id": link.id,
            "old_status": old_status,
            "new_status": payment_info["status"],
            "payment_info": payment_info,
        }
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"error_syncing_payment_status: payment_id={payment_id}, error={str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Ошибка синхронизации статуса платежа: {str(e)}")


@router.post("/sync-all")
@limiter.limit("10/1minute")
async def sync_all_payments_manual(
    request: Request,
    current_admin: Admin = Depends(get_current_admin),
):
    """Запустить синхронизацию всех платежей вручную."""
    try:
        from app.tasks.payment_sync import sync_all_payments
        import asyncio

        # Запускаем синхронизацию в фоне
        asyncio.create_task(sync_all_payments())

        logger.info(f"manual_payment_sync_triggered: admin_id={current_admin.id}")

        return {"status": "ok", "message": "Синхронизация запущена"}
    except Exception as e:
        logger.error(f"error_triggering_manual_sync: error={str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Ошибка запуска синхронизации: {str(e)}")
