"""Обработчики команд для работы с платежами и подписками."""

from aiogram import Router, F
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from datetime import datetime, timedelta
from typing import Optional
import asyncio
import concurrent.futures

from app.models.user import User
from app.models.crossposting_link import CrosspostingLink
from app.models.telegram_channel import TelegramChannel
from app.models.max_channel import MaxChannel
from app.payments.yookassa_client import create_payment
from config.database import async_session_maker
from config.settings import settings
from app.utils.logger import get_logger
from app.bot.keyboards import get_main_keyboard, get_cancel_keyboard

logger = get_logger(__name__)
router = Router()


async def format_subscription_info(
    link: CrosspostingLink, telegram_channel: Optional[TelegramChannel], max_channel: Optional[MaxChannel]
) -> str:
    """Форматировать информацию о подписке для пользователя."""
    tg_name = telegram_channel.channel_username or telegram_channel.channel_title if telegram_channel else "N/A"
    max_name = max_channel.channel_username or max_channel.channel_title if max_channel else "N/A"

    status_icons = {
        "vip": "⭐ VIP",
        "free_trial": "🆓 Бесплатный период",
        "active": "✅ Активна",
        "expired": "⚠️ Истекла",
        "cancelled": "❌ Отменена",
    }

    status_text = status_icons.get(link.subscription_status, link.subscription_status)

    info = f"📊 Связь #{link.id}\n\n"
    info += f"Telegram: {tg_name}\n"
    info += f"MAX: {max_name}\n\n"
    info += f"📅 Подписка:\n"
    info += f"Статус: {status_text}\n"

    if link.subscription_status == "vip":
        info += f"Тип: VIP (бесплатно)\n"
    elif link.is_first_link:
        info += f"Тип: Первая связь (бесплатно)\n"
    elif link.subscription_status in ("active", "free_trial") or link.payment_status == "succeeded":
        info += f"Тип: Платная\n"
    else:
        info += f"Тип: Не оплачено\n"

    # Определяем дату окончания
    end_date = link.subscription_end_date or link.free_trial_end_date
    if end_date:
        now = datetime.utcnow()
        if end_date > now:
            delta = end_date - now
            days = delta.days
            hours = delta.seconds // 3600
            if days > 0:
                info += f"Осталось: {days} дней\n"
            else:
                info += f"Осталось: {hours} часов\n"
            info += f"Окончание: {end_date.strftime('%d.%m.%Y %H:%M')}\n"
        else:
            delta = now - end_date
            days = delta.days
            info += f"Истекла {days} дней назад\n"
            info += f"Окончание: {end_date.strftime('%d.%m.%Y %H:%M')}\n"

    return info


@router.message(Command("my_subscriptions"))
async def cmd_my_subscriptions(message: Message, state: FSMContext):
    """Показать список всех связей с информацией о подписках."""
    async with async_session_maker() as session:
        # Находим пользователя
        result = await session.execute(select(User).where(User.telegram_user_id == message.from_user.id))
        user = result.scalar_one_or_none()

        if not user:
            await message.answer("❌ Пользователь не найден. Используйте /start для регистрации.")
            return

        # Находим все связи пользователя
        result = await session.execute(
            select(CrosspostingLink).where(CrosspostingLink.user_id == user.id).order_by(CrosspostingLink.created_at.desc())
        )
        links = result.scalars().all()

        if not links:
            await message.answer(
                "📋 У вас пока нет связей.\n\n" "Создайте связь через команду /create_link", reply_markup=get_main_keyboard()
            )
            return

        # Группируем по статусам
        active_links = [l for l in links if l.is_enabled and l.subscription_status in ("vip", "free_trial", "active")]
        expired_links = [l for l in links if not l.is_enabled or l.subscription_status == "expired"]

        response = "📋 Ваши подписки\n\n"

        if active_links:
            response += f"✅ Активные ({len(active_links)}):\n"
            for link in active_links:
                tg_result = await session.execute(
                    select(TelegramChannel).where(TelegramChannel.id == link.telegram_channel_id)
                )
                tg_ch = tg_result.scalar_one_or_none()
                max_result = await session.execute(select(MaxChannel).where(MaxChannel.id == link.max_channel_id))
                max_ch = max_result.scalar_one_or_none()

                tg_name = tg_ch.channel_username or tg_ch.channel_title if tg_ch else "N/A"
                max_name = max_ch.channel_username or max_ch.channel_title if max_ch else "N/A"

                end_date = link.subscription_end_date or link.free_trial_end_date
                if end_date:
                    now = datetime.utcnow()
                    if end_date > now:
                        delta = end_date - now
                        days = delta.days
                        response += f"  #{link.id}: {tg_name} → {max_name} (осталось {days} дней)\n"
                    else:
                        response += f"  #{link.id}: {tg_name} → {max_name} (истекла)\n"
                else:
                    response += f"  #{link.id}: {tg_name} → {max_name}\n"
            response += "\n"

        if expired_links:
            response += f"⚠️ Истекшие ({len(expired_links)}):\n"
            for link in expired_links:
                tg_result = await session.execute(
                    select(TelegramChannel).where(TelegramChannel.id == link.telegram_channel_id)
                )
                tg_ch = tg_result.scalar_one_or_none()
                max_result = await session.execute(select(MaxChannel).where(MaxChannel.id == link.max_channel_id))
                max_ch = max_result.scalar_one_or_none()

                tg_name = tg_ch.channel_username or tg_ch.channel_title if tg_ch else "N/A"
                max_name = max_ch.channel_username or max_ch.channel_title if max_ch else "N/A"
                response += f"  #{link.id}: {tg_name} → {max_name}\n"

        await message.answer(response, reply_markup=get_main_keyboard())


async def process_pay_link(user_id: int, link_id: int, message_or_callback, state: FSMContext) -> bool:
    """
    Общая функция для обработки оплаты/продления связи.
    Создает платеж.

    Args:
        user_id: ID пользователя Telegram
        link_id: ID связи
        message_or_callback: Message или CallbackQuery объект
        state: FSMContext для управления состоянием

    Returns:
        True если успешно, False если ошибка
    """
    async with async_session_maker() as session:
        # Находим пользователя
        result = await session.execute(select(User).where(User.telegram_user_id == user_id))
        user = result.scalar_one_or_none()

        if not user:
            if hasattr(message_or_callback, "answer"):
                await message_or_callback.answer("❌ Пользователь не найден. Используйте /start для регистрации.")
            return False

        # Проверяем VIP статус
        if user.is_vip:
            if hasattr(message_or_callback, "answer"):
                await message_or_callback.answer(
                    "⭐ Вы VIP пользователь!\n\n" "Все ваши связи активны бесплатно. Оплата не требуется.",
                    reply_markup=get_main_keyboard(),
                )
            return False

        # Находим связь
        result = await session.execute(
            select(CrosspostingLink).where(CrosspostingLink.id == link_id, CrosspostingLink.user_id == user.id)
        )
        link = result.scalar_one_or_none()

        if not link:
            if hasattr(message_or_callback, "answer"):
                await message_or_callback.answer(
                    f"❌ Связь #{link_id} не найдена.\n\n"
                    "Убедитесь, что вы указали правильный ID связи.\n"
                    "Используйте /my_subscriptions для просмотра ваших связей."
                )
            return False

        # Создаем платеж
        result = await create_payment_with_email(link_id, user_id)
        if result:
            payment_info, link, tg_ch, max_ch = result
            await send_payment_message(message_or_callback, payment_info, link, tg_ch, max_ch)
            return True
        else:
            if hasattr(message_or_callback, "answer"):
                await message_or_callback.answer("❌ Ошибка при создании платежа.", reply_markup=get_main_keyboard())
            return False


async def create_payment_with_email(link_id: int, telegram_user_id: int):
    """
    Создать платеж.

    Args:
        link_id: ID связи
        telegram_user_id: Telegram ID пользователя

    Returns:
        Tuple (payment_info, link, tg_ch, max_ch) или None
    """
    async with async_session_maker() as session:
        # Сначала находим пользователя по telegram_user_id
        user_result = await session.execute(select(User).where(User.telegram_user_id == telegram_user_id))
        user = user_result.scalar_one_or_none()
        if not user:
            logger.error(f"user_not_found: link_id={link_id}, telegram_user_id={telegram_user_id}")
            return None

        # Находим связь по внутреннему user.id
        result = await session.execute(
            select(CrosspostingLink).where(CrosspostingLink.id == link_id, CrosspostingLink.user_id == user.id)
        )
        link = result.scalar_one_or_none()

        if not link:
            logger.error(f"link_not_found: link_id={link_id}, user_id={user.id}, telegram_user_id={telegram_user_id}")
            return None

        # Загружаем каналы для отображения
        tg_result = await session.execute(select(TelegramChannel).where(TelegramChannel.id == link.telegram_channel_id))
        tg_ch = tg_result.scalar_one_or_none()
        max_result = await session.execute(select(MaxChannel).where(MaxChannel.id == link.max_channel_id))
        max_ch = max_result.scalar_one_or_none()

        # Создаем платеж
        try:
            # Получаем e-mail пользователя для отправки чека
            user_email = user.email if user.email else None

            loop = asyncio.get_event_loop()
            with concurrent.futures.ThreadPoolExecutor() as executor:
                payment_info = await loop.run_in_executor(executor, create_payment, link.id, user.id, None, user_email)

            # Сохраняем информацию о платеже
            link.yookassa_payment_id = payment_info["payment_id"]
            link.payment_status = "pending"
            await session.commit()

            # Формируем информацию о продлении
            current_end_date = link.subscription_end_date
            now = datetime.utcnow()
            if current_end_date and current_end_date > now:
                new_end_date = current_end_date + timedelta(days=settings.subscription_period_days)
                period_info = f"Текущее окончание: {current_end_date.strftime('%d.%m.%Y')}\nПосле оплаты подписка будет продлена до: {new_end_date.strftime('%d.%m.%Y')}"
            else:
                new_end_date = now + timedelta(days=settings.subscription_period_days)
                period_info = f"После оплаты подписка будет активирована до: {new_end_date.strftime('%d.%m.%Y')}"

            # Отправляем сообщение с ссылкой на оплату
            payment_keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="💳 Оплатить подписку", url=payment_info["confirmation_url"])],
                    [InlineKeyboardButton(text="❌ Отменить оплату", callback_data=f"cancel_payment_{link.id}")],
                ]
            )

            tg_name = tg_ch.channel_title or tg_ch.channel_username if tg_ch else "N/A"
            max_name = max_ch.channel_title or max_ch.channel_username if max_ch else "N/A"

            answer_text = (
                f"💳 Оплата подписки\n\n"
                f"Связь: #{link.id}\n"
                f"Telegram: {tg_name}\n"
                f"MAX: {max_name}\n\n"
                f"{period_info}\n\n"
                f"Сумма: {payment_info['amount']:.0f} ₽\n"
                f"Период: {settings.subscription_period_days} дней\n\n"
                f"Нажмите кнопку ниже для оплаты:\n\n"
                f"📄 <a href='https://srazuum.ru/docs/privacy_policy.html'>Политика конфиденциальности</a>\n"
                f"📄 <a href='https://srazuum.ru/docs/terms_of_service.html'>Пользовательское соглашение</a>"
            )

            return payment_info, link, tg_ch, max_ch
        except Exception as e:
            logger.error("payment_creation_error", error=str(e), link_id=link.id, telegram_user_id=telegram_user_id)
            return None


@router.callback_query(F.data.startswith("pay_link_"))
async def callback_pay_link(callback: CallbackQuery, state: FSMContext):
    """Обработчик callback-кнопки оплаты подписки."""
    import re

    match = re.search(r"pay_link_(\d+)", callback.data)
    if not match:
        await callback.answer("Ошибка: не удалось определить ID связи.", show_alert=True)
        return

    link_id = int(match.group(1))
    await process_pay_link(callback.from_user.id, link_id, callback, state)


@router.callback_query(F.data.startswith("renew_link_"))
async def callback_renew_link(callback: CallbackQuery, state: FSMContext):
    """Обработчик callback-кнопки продления подписки (то же, что и оплата)."""
    import re

    match = re.search(r"renew_link_(\d+)", callback.data)
    if not match:
        await callback.answer("Ошибка: не удалось определить ID связи.", show_alert=True)
        return

    link_id = int(match.group(1))
    await process_pay_link(callback.from_user.id, link_id, callback, state)


@router.callback_query(F.data.startswith("cancel_payment_"))
async def callback_cancel_payment(callback: CallbackQuery, state: FSMContext):
    """Обработчик callback-кнопки отмены оплаты."""
    import re
    from sqlalchemy import delete

    match = re.search(r"cancel_payment_(\d+)", callback.data)
    if not match:
        await callback.answer("Ошибка: не удалось определить ID связи.", show_alert=True)
        return

    link_id = int(match.group(1))

    async with async_session_maker() as session:
        # Находим пользователя
        result = await session.execute(select(User).where(User.telegram_user_id == callback.from_user.id))
        user = result.scalar_one_or_none()

        if not user:
            await callback.answer("❌ Пользователь не найден.", show_alert=True)
            return

        # Находим связь
        result = await session.execute(
            select(CrosspostingLink).where(CrosspostingLink.id == link_id, CrosspostingLink.user_id == user.id)
        )
        link = result.scalar_one_or_none()

        if not link:
            await callback.answer("❌ Связь не найдена.", show_alert=True)
            return

        # Проверяем, что платеж еще не оплачен
        if link.payment_status == "succeeded" or link.subscription_status == "active":
            await callback.answer("❌ Невозможно отменить оплаченную подписку.", show_alert=True)
            return

        # Удаляем связь, если она была создана только для оплаты (неактивна)
        if not link.is_enabled and link.subscription_status == "expired":
            # Удаляем связь
            await session.execute(delete(CrosspostingLink).where(CrosspostingLink.id == link_id))
            await session.commit()

            await callback.message.edit_text(
                "❌ Оплата отменена.\n\nСвязь удалена.\n\nВыберите действие:",
                reply_markup=None,
            )
            await callback.message.answer("Выберите действие:", reply_markup=get_main_keyboard())
            await callback.answer("Оплата отменена")
            logger.info(f"payment_cancelled_link_deleted: link_id={link_id}, user_id={user.id}")
        else:
            # Просто отменяем платеж, но оставляем связь
            link.payment_status = "canceled"
            await session.commit()

            await callback.message.edit_text(
                "❌ Оплата отменена.\n\nВыберите действие:",
                reply_markup=None,
            )
            await callback.message.answer("Выберите действие:", reply_markup=get_main_keyboard())
            await callback.answer("Оплата отменена")
            logger.info(f"payment_cancelled: link_id={link_id}, user_id={user.id}")

    await state.clear()


# Обработчики удалены


async def send_payment_message(message_or_callback, payment_info, link, tg_ch, max_ch):
    """Отправить сообщение с ссылкой на оплату."""
    try:
        current_end_date = link.subscription_end_date
        now = datetime.utcnow()
        if current_end_date and current_end_date > now:
            new_end_date = current_end_date + timedelta(days=settings.subscription_period_days)
            period_info = f"Текущее окончание: {current_end_date.strftime('%d.%m.%Y')}\nПосле оплаты подписка будет продлена до: {new_end_date.strftime('%d.%m.%Y')}"
        else:
            new_end_date = now + timedelta(days=settings.subscription_period_days)
            period_info = f"После оплаты подписка будет активирована до: {new_end_date.strftime('%d.%m.%Y')}"

        if not payment_info or "confirmation_url" not in payment_info:
            logger.error(f"invalid_payment_info: link_id={link.id}, payment_info={payment_info}")
            raise ValueError("Неверная информация о платеже")

        payment_keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="💳 Оплатить подписку", url=payment_info["confirmation_url"])],
                [InlineKeyboardButton(text="❌ Отменить оплату", callback_data=f"cancel_payment_{link.id}")],
            ]
        )

        tg_name = tg_ch.channel_title or tg_ch.channel_username if tg_ch else "N/A"
        max_name = max_ch.channel_title or max_ch.channel_username if max_ch else "N/A"

        answer_text = (
            f"💳 Оплата подписки\n\n"
            f"Связь: #{link.id}\n"
            f"Telegram: {tg_name}\n"
            f"MAX: {max_name}\n\n"
            f"{period_info}\n\n"
            f"Сумма: {payment_info['amount']:.0f} ₽\n"
            f"Период: {settings.subscription_period_days} дней\n\n"
            f"Нажмите кнопку ниже для оплаты:\n\n"
            f"📄 <a href='https://srazuum.ru/docs/privacy_policy.html'>Политика конфиденциальности</a>\n"
            f"📄 <a href='https://srazuum.ru/docs/terms_of_service.html'>Пользовательское соглашение</a>"
        )

        if hasattr(message_or_callback, "message"):  # CallbackQuery
            await message_or_callback.message.answer(answer_text, reply_markup=payment_keyboard, parse_mode="HTML")
            await message_or_callback.answer()
        else:  # Message
            await message_or_callback.answer(answer_text, reply_markup=payment_keyboard, parse_mode="HTML")
    except Exception as e:
        logger.error(f"send_payment_message_error: link_id={link.id}, error={str(e)}", exc_info=True)
        raise


@router.message(Command("pay_link"))
async def cmd_pay_link(message: Message, state: FSMContext):
    """Оплатить/продлить конкретную связь."""
    # Парсим link_id из команды
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer(
            "❌ Укажите ID связи.\n\n"
            "Использование: /pay_link [link_id]\n\n"
            "Пример: /pay_link 123\n\n"
            "Используйте /my_subscriptions для просмотра ваших связей."
        )
        return

    try:
        link_id = int(parts[1])
    except ValueError:
        await message.answer("❌ Неверный формат ID связи. ID должен быть числом.")
        return

    # Используем единую функцию process_pay_link для создания платежа
    await process_pay_link(message.from_user.id, link_id, message, state)


@router.message(Command("subscription_info"))
async def cmd_subscription_info(message: Message, state: FSMContext):
    """Показать детальную информацию о подписке конкретной связи."""
    # Парсим link_id из команды
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer(
            "❌ Укажите ID связи.\n\n" "Использование: /subscription_info [link_id]\n\n" "Пример: /subscription_info 123"
        )
        return

    try:
        link_id = int(parts[1])
    except ValueError:
        await message.answer("❌ Неверный формат ID связи. ID должен быть числом.")
        return

    async with async_session_maker() as session:
        # Находим пользователя
        result = await session.execute(select(User).where(User.telegram_user_id == message.from_user.id))
        user = result.scalar_one_or_none()

        if not user:
            await message.answer("❌ Пользователь не найден. Используйте /start для регистрации.")
            return

        # Находим связь
        result = await session.execute(
            select(CrosspostingLink).where(CrosspostingLink.id == link_id, CrosspostingLink.user_id == user.id)
        )
        link = result.scalar_one_or_none()

        if not link:
            await message.answer(f"❌ Связь #{link_id} не найдена.")
            return

        # Загружаем каналы
        tg_result = await session.execute(select(TelegramChannel).where(TelegramChannel.id == link.telegram_channel_id))
        tg_ch = tg_result.scalar_one_or_none()
        max_result = await session.execute(select(MaxChannel).where(MaxChannel.id == link.max_channel_id))
        max_ch = max_result.scalar_one_or_none()

        # Форматируем информацию
        info = await format_subscription_info(link, tg_ch, max_ch)

        # Добавляем кнопки действий
        keyboard_buttons = []
        if link.subscription_status in ("active", "free_trial") and not user.is_vip:
            keyboard_buttons.append([InlineKeyboardButton(text="🔄 Продлить подписку", callback_data=f"renew_link_{link.id}")])
        elif link.subscription_status == "expired" and not user.is_vip:
            keyboard_buttons.append([InlineKeyboardButton(text="💳 Оплатить подписку", callback_data=f"pay_link_{link.id}")])

        keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons) if keyboard_buttons else None

        await message.answer(info, reply_markup=keyboard)
