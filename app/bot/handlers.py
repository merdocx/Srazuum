"""Обработчики команд Telegram бота."""

import asyncio
import re
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command, CommandStart
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from typing import Optional, List

from app.models.user import User
from app.models.telegram_channel import TelegramChannel
from app.models.max_channel import MaxChannel
from app.models.crossposting_link import CrosspostingLink
from app.models.message_log import MessageLog
from app.models.audit_log import AuditLog
from app.utils.logger import get_logger
from app.utils.enums import MessageStatus, MessageType, AuditAction
from app.utils.validators import TelegramChannelInput, MaxChannelInput
from app.utils.exceptions import ValidationError, PermissionError, ChannelNotFoundError, APIError
from aiogram.exceptions import TelegramBadRequest, TelegramNotFound
from app.bot.keyboards import (
    get_main_keyboard,
    get_channels_list_keyboard,
    get_link_detail_keyboard,
    get_delete_confirm_keyboard,
    get_back_to_menu_keyboard,
    get_retry_keyboard,
    get_migrate_links_keyboard,
    get_migration_offer_keyboard,
    get_cancel_keyboard,
    get_stop_migration_keyboard,
)
from config.database import async_session_maker
from config.settings import settings
from app.utils.cache import delete_cache
from app.payments.yookassa_client import create_payment

logger = get_logger(__name__)
router = Router()

# Глобальный экземпляр бота и его ID
_bot_instance: Optional[Bot] = None
_bot_id: Optional[int] = None


def set_bot_instance(bot: Bot, bot_id: int) -> None:
    """Установить глобальный экземпляр бота."""
    global _bot_instance, _bot_id
    _bot_instance = bot
    _bot_id = bot_id


def get_bot() -> Bot:
    """Получить глобальный экземпляр бота."""
    if _bot_instance is None:
        raise RuntimeError("Bot instance not initialized")
    return _bot_instance


def get_bot_id() -> int:
    """Получить ID бота."""
    if _bot_id is None:
        raise RuntimeError("Bot ID not initialized")
    return _bot_id


class AddChannelStates(StatesGroup):
    """Состояния для добавления канала."""

    waiting_telegram_channel = State()
    waiting_max_channel = State()


class LinkManagementStates(StatesGroup):
    """Состояния для управления связями."""

    viewing_link_detail = State()  # Хранит link_id
    viewing_channels_list = State()  # Хранит page
    confirming_delete = State()  # Хранит link_id


class MigrateStates(StatesGroup):
    """Состояния для миграции постов."""

    selecting_link = State()  # Выбор связи для миграции
    migrating = State()  # Процесс миграции активен


async def get_or_create_user(telegram_user_id: int, username: Optional[str] = None) -> User:
    """Получить или создать пользователя."""
    async with async_session_maker() as session:
        result = await session.execute(select(User).where(User.telegram_user_id == telegram_user_id))
        user = result.scalar_one_or_none()

        if not user:
            user = User(telegram_user_id=telegram_user_id, telegram_username=username)
            session.add(user)
            await session.commit()
            await session.refresh(user)
            logger.info("user_created", user_id=user.id, telegram_user_id=telegram_user_id)

        return user


async def log_audit(user_id: int, action: str, entity_type: str, entity_id: int, details: dict = None):
    """Логировать действие в аудит."""
    async with async_session_maker() as session:
        audit_log = AuditLog(user_id=user_id, action=action, entity_type=entity_type, entity_id=entity_id, details=details)
        session.add(audit_log)
        await session.commit()


# КРИТИЧНО: Обработчики для состояния confirming_delete должны быть зарегистрированы ПЕРВЫМИ
# и использовать специфичные фильтры для приоритета
@router.message(LinkManagementStates.confirming_delete, F.text == "✅ Да, удалить")
async def message_delete_yes_handler(message: Message, state: FSMContext):
    """Обработчик кнопки 'Да, удалить' в состоянии confirming_delete."""
    data = await state.get_data()
    link_id = data.get("delete_link_id")

    logger.info(
        "delete_yes_handler_called", user_id=message.from_user.id, message_text=message.text, link_id=link_id, state_data=data
    )

    if link_id:
        await _process_delete_yes(message, state, link_id)
    else:
        await message.answer("Ошибка: не найдена связь для удаления.")
        await state.clear()


@router.message(LinkManagementStates.confirming_delete, F.text == "❌ Отмена")
async def message_delete_cancel_handler(message: Message, state: FSMContext):
    """Обработчик кнопки 'Отмена' в состоянии confirming_delete."""
    data = await state.get_data()
    link_id = data.get("delete_link_id")

    logger.info("delete_cancel_handler_called", user_id=message.from_user.id, message_text=message.text, link_id=link_id)

    await _process_delete_cancel(message, state, link_id)


async def _process_delete_yes(message: Message, state: FSMContext, link_id: int):
    """Внутренняя функция для обработки подтвержденного удаления связи."""
    logger.info("delete_yes_processing", user_id=message.from_user.id, link_id=link_id)

    if not link_id:
        await message.answer("Ошибка: не найдена связь для удаления.")
        await state.clear()
        return

    user = await get_or_create_user(message.from_user.id, message.from_user.username)

    async with async_session_maker() as session:
        result = await session.execute(
            select(CrosspostingLink)
            .options(selectinload(CrosspostingLink.telegram_channel))
            .where(CrosspostingLink.id == link_id)
            .where(CrosspostingLink.user_id == user.id)
        )
        link = result.scalar_one_or_none()

        if not link:
            await message.answer("Связь не найдена.")
            await state.clear()
            return

        # КРИТИЧНО: Сохраняем channel_id перед удалением для очистки кэша
        telegram_channel_id_for_cache = None
        if link.telegram_channel:
            telegram_channel_id_for_cache = link.telegram_channel.channel_id

        # Сохраняем ID каналов для проверки после удаления
        telegram_channel_id_for_cleanup = link.telegram_channel_id
        max_channel_id_for_cleanup = link.max_channel_id

        await session.delete(link)
        await session.commit()

        # КРИТИЧНО: Очищаем кэш для канала при удалении связи
        if telegram_channel_id_for_cache:
            cache_key = f"channel_links:{telegram_channel_id_for_cache}"
            await delete_cache(cache_key)
            logger.info("cache_cleared_on_link_delete", channel_id=telegram_channel_id_for_cache, link_id=link_id)

        # Очистка неиспользуемых каналов после удаления связи
        async with async_session_maker() as cleanup_session:
            # Проверяем, есть ли еще связи у Telegram канала
            telegram_links_count = await cleanup_session.execute(
                select(func.count(CrosspostingLink.id)).where(
                    CrosspostingLink.telegram_channel_id == telegram_channel_id_for_cleanup
                )
            )
            if telegram_links_count.scalar() == 0:
                # Нет больше связей - удаляем Telegram канал
                result_tg = await cleanup_session.execute(
                    select(TelegramChannel).where(TelegramChannel.id == telegram_channel_id_for_cleanup)
                )
                tg_channel = result_tg.scalar_one_or_none()
                if tg_channel:
                    await cleanup_session.delete(tg_channel)
                    logger.info("telegram_channel_cleaned_up", channel_id=tg_channel.id, title=tg_channel.channel_title)

            # Проверяем, есть ли еще связи у MAX канала
            max_links_count = await cleanup_session.execute(
                select(func.count(CrosspostingLink.id)).where(CrosspostingLink.max_channel_id == max_channel_id_for_cleanup)
            )
            if max_links_count.scalar() == 0:
                # Нет больше связей - удаляем MAX канал
                result_max = await cleanup_session.execute(
                    select(MaxChannel).where(MaxChannel.id == max_channel_id_for_cleanup)
                )
                max_channel = result_max.scalar_one_or_none()
                if max_channel:
                    await cleanup_session.delete(max_channel)
                    logger.info("max_channel_cleaned_up", channel_id=max_channel.id, title=max_channel.channel_title)

            await cleanup_session.commit()

        await log_audit(user.id, AuditAction.DELETE_LINK.value, "crossposting_link", link_id)

        text = f"🗑️ Связь #{link_id} удалена."
        keyboard = get_back_to_menu_keyboard()
        await message.answer(text, reply_markup=keyboard)
        await state.clear()
        logger.info("link_deleted", link_id=link_id, user_id=user.id)


async def _process_delete_cancel(message: Message, state: FSMContext, link_id: int):
    """Внутренняя функция для обработки отмены удаления."""
    logger.info("delete_cancel_processing", user_id=message.from_user.id, link_id=link_id)

    if link_id:
        # Возвращаемся к деталям связи
        await show_link_detail(message, state, link_id)
    else:
        # Если link_id не найден, возвращаемся к списку
        data = await state.get_data()
        current_page = data.get("channels_list_page", 0)
        await show_channels_list(message, state, page=current_page)


@router.message(CommandStart())
async def cmd_start(message: Message):
    """Обработчик команды /start."""
    user = await get_or_create_user(message.from_user.id, message.from_user.username)

    text = (
        "Привет! Я помогу вам настроить кросспостинг из Telegram в MAX.\n\n"
        "Используйте кнопку «➕ Добавить связь» для создания связи между каналами в Telegram и MAX.\n\n"
        "📄 Документы:\n"
        "• <a href='https://srazuum.ru/docs/privacy_policy.html'>Политика конфиденциальности</a>\n"
        "• <a href='https://srazuum.ru/docs/terms_of_service.html'>Пользовательское соглашение</a>\n\n"
        "Выберите действие:"
    )

    await message.answer(text, reply_markup=get_main_keyboard(), parse_mode=ParseMode.HTML)
    logger.info("start_command", user_id=user.id, telegram_user_id=message.from_user.id)


@router.message(Command("help"))
async def cmd_help(message: Message):
    """Обработчик команды /help."""
    text = (
        "📖 Помощь по использованию бота:\n\n"
        "Используйте кнопки для управления кросспостингом:\n\n"
        "➕ Добавить связь - Создать новую связь каналов\n"
        "📋 Список связей - Просмотр всех ваших связей\n"
        "📊 Статус - Общая статистика кросспостинга\n"
        "⚙️ Настройки - Настройки бота\n\n"
        "Для управления конкретной связью:\n"
        "1. Откройте список связей\n"
        "2. Выберите нужную связь\n"
        "3. Используйте кнопки для управления"
    )
    await message.answer(text, reply_markup=get_back_to_menu_keyboard())


@router.message(F.text == "💬 Связаться с поддержкой")
async def message_support(message: Message, state: FSMContext):
    """Обработчик кнопки связи с поддержкой."""
    await state.clear()

    text = (
        "💬 Связаться с поддержкой\n\n"
        "Если у вас возникли вопросы или проблемы, напишите нашей поддержке:\n\n"
        "👉 @vee_support"
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="💬 Написать в поддержку", url="https://t.me/vee_support")]]
    )
    await message.answer(text, reply_markup=keyboard)


@router.message(F.text == "🏠 Главное меню")
async def message_main_menu(message: Message, state: FSMContext):
    """Обработчик кнопки главного меню."""
    await state.clear()
    text = (
        "Привет! Я помогу вам настроить кросспостинг из Telegram в MAX.\n\n"
        "Используйте кнопку «➕ Добавить связь» для создания связи между каналами в Telegram и MAX.\n\n"
        "📄 Документы:\n"
        "• <a href='https://srazuum.ru/docs/privacy_policy.html'>Политика конфиденциальности</a>\n"
        "• <a href='https://srazuum.ru/docs/terms_of_service.html'>Пользовательское соглашение</a>\n\n"
        "Выберите действие:"
    )
    await message.answer(text, reply_markup=get_main_keyboard(), parse_mode=ParseMode.HTML)
    logger.info("main_menu_opened", user_id=message.from_user.id)


@router.message(AddChannelStates.waiting_telegram_channel, F.text == "❌ Отмена")
@router.message(AddChannelStates.waiting_max_channel, F.text == "❌ Отмена")
async def message_cancel_add_channel(message: Message, state: FSMContext):
    """Обработчик кнопки 'Отмена' - отменяет процесс создания связи."""
    await state.clear()
    text = "❌ Создание связи отменено.\n\n" "Выберите действие:"
    await message.answer(text, reply_markup=get_main_keyboard())
    logger.info("add_channel_cancelled", user_id=message.from_user.id)


@router.message(F.text == "🔄 Повторить")
async def message_retry(message: Message, state: FSMContext):
    """Обработчик кнопки повтора."""
    data = await state.get_data()
    retry_state = data.get("retry_state", "add_channel")

    if retry_state == "telegram_channel":
        await state.set_state(AddChannelStates.waiting_telegram_channel)
        text = (
            "📋 Создание связи каналов\n\n"
            "⚠️ ВАЖНО! Перед началом убедитесь, что:\n\n"
            "1. ✅ Бот (@srazuum\\_bot) добавлен в ваш Telegram-канал в качестве администратора\n"
            "2. ✅ Вы зашли в [бот в MAX](https://max.ru/id9725096017_bot) и нажали /start\n"
            "3. ✅ [Бот в MAX](https://max.ru/id9725096017_bot) добавлен в ваш MAX-канал в качестве администратора (сначала его необходимо добавить в подписчики канала, затем назначить администратором)\n\n"
            "📝 Для создания связи:\n\n"
            "Шаг 1: Отправьте ссылку на Telegram-канал (пример: https://t.me/username)"
        )
        await message.answer(
            text, reply_markup=get_cancel_keyboard(), parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True
        )
    elif retry_state == "max_channel":
        await state.set_state(AddChannelStates.waiting_max_channel)
        text = "Отправьте ссылку на MAX-канал (пример: https://max.ru/username)"
        await message.answer(text, reply_markup=get_cancel_keyboard())
    else:
        await state.set_state(AddChannelStates.waiting_telegram_channel)
        text = (
            "📋 Создание связи каналов\n\n"
            "⚠️ ВАЖНО! Перед началом убедитесь, что:\n\n"
            "1. ✅ Бот (@srazuum\\_bot) добавлен в ваш Telegram-канал в качестве администратора\n"
            "2. ✅ Вы зашли в [бот в MAX](https://max.ru/id9725096017_bot) и нажали /start\n"
            "3. ✅ [Бот в MAX](https://max.ru/id9725096017_bot) добавлен в ваш MAX-канал в качестве администратора (сначала его необходимо добавить в подписчики канала, затем назначить администратором)\n\n"
            "📝 Для создания связи:\n\n"
            "Шаг 1: Отправьте ссылку на Telegram-канал (пример: https://t.me/username)"
        )
        await message.answer(
            text, reply_markup=get_cancel_keyboard(), parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True
        )

    logger.info("retry_action", state=retry_state, user_id=message.from_user.id)


@router.message(Command("add_channel"))
async def cmd_add_channel(message: Message, state: FSMContext):
    """Обработчик команды /add_channel."""
    text = (
        "📋 Создание связи каналов\n\n"
        "⚠️ ВАЖНО! Перед началом убедитесь, что:\n\n"
        "1. ✅ Бот (@srazuum\\_bot) добавлен в ваш Telegram-канал в качестве администратора\n"
        "2. ✅ Вы зашли в [бот в MAX](https://max.ru/id9725096017_bot) и нажали /start\n"
        "3. ✅ [Бот в MAX](https://max.ru/id9725096017_bot) добавлен в ваш MAX-канал в качестве администратора (сначала его необходимо добавить в подписчики канала, затем назначить администратором)\n\n"
        "📝 Для создания связи:\n\n"
        "Шаг 1: Отправьте ссылку на Telegram-канал (пример: https://t.me/username)"
    )
    await message.answer(
        text, reply_markup=get_cancel_keyboard(), parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True
    )
    await state.set_state(AddChannelStates.waiting_telegram_channel)
    logger.info("add_channel_started", user_id=message.from_user.id)


@router.message(F.text == "➕ Добавить связь")
async def message_add_channel(message: Message, state: FSMContext):
    """Обработчик кнопки добавления связи."""
    text = (
        "📋 Создание связи каналов\n\n"
        "⚠️ ВАЖНО! Перед началом убедитесь, что:\n\n"
        "1. ✅ Бот (@srazuum\\_bot) добавлен в ваш Telegram-канал в качестве администратора\n"
        "2. ✅ Вы зашли в [бот в MAX](https://max.ru/id9725096017_bot) и нажали /start\n"
        "3. ✅ [Бот в MAX](https://max.ru/id9725096017_bot) добавлен в ваш MAX-канал в качестве администратора (сначала его необходимо добавить в подписчики канала, затем назначить администратором)\n\n"
        "📝 Для создания связи:\n\n"
        "Шаг 1: Отправьте ссылку на Telegram-канал (пример: https://t.me/username)"
    )
    await message.answer(
        text, reply_markup=get_cancel_keyboard(), parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True
    )
    await state.set_state(AddChannelStates.waiting_telegram_channel)
    logger.info("add_channel_started", user_id=message.from_user.id)


@router.message(AddChannelStates.waiting_telegram_channel)
async def process_telegram_channel(message: Message, state: FSMContext):
    """Обработка Telegram канала. Принимаем только ссылки."""
    import re

    channel_id = None
    channel_username = None
    channel_title = "Unknown"

    # Вариант 1: Пересылка сообщения из канала
    if message.forward_from_chat:
        channel_id = message.forward_from_chat.id
        channel_username = message.forward_from_chat.username
        channel_title = message.forward_from_chat.title or "Unknown"
        logger.info("telegram_channel_from_forward", channel_id=channel_id, username=channel_username)

    # Вариант 2: Текст со ссылкой или username
    elif message.text:
        text = message.text.strip()

        # Извлекаем username из различных форматов
        username_match = None

        # Формат: @username
        if text.startswith("@"):
            username_match = text[1:]
        # Формат: https://t.me/username или t.me/username или telegram.me/username
        elif re.match(r"^(https?://)?(www\.)?(t\.me|telegram\.me)/", text, re.IGNORECASE):
            # Извлекаем username из ссылки
            parts = text.split("/")
            potential_username = parts[-1].split("?")[0]  # Убираем query параметры
            # Пропускаем joinchat ссылки (приватные каналы) и другие служебные пути
            if (
                potential_username
                and potential_username != "joinchat"
                and not potential_username.startswith("+")
                and re.match(r"^[a-zA-Z0-9_]{5,32}$", potential_username)
            ):
                username_match = potential_username

        if username_match:
            channel_username = username_match
            channel_title = channel_username
            # Получаем ID канала по username через Bot API
            try:
                bot = get_bot()
                chat = await bot.get_chat(f"@{channel_username}")
                channel_id = chat.id
                channel_title = chat.title or channel_username
                logger.info("telegram_channel_from_username", channel_id=channel_id, username=channel_username)
            except (TelegramBadRequest, TelegramNotFound, ValueError) as e:
                logger.warning(
                    "telegram_channel_info_error", username=channel_username, error=str(e), error_type=type(e).__name__
                )
                channel_id = None
            except Exception as e:
                logger.error(
                    "unexpected_error_getting_channel_info",
                    username=channel_username,
                    error=str(e),
                    error_type=type(e).__name__,
                    exc_info=True,
                )
                channel_id = None
        else:
            await message.answer(
                "❌ Не удалось распознать канал.\n\n"
                "Поддерживаемые форматы:\n"
                "• Пересылка сообщения из канала\n"
                "• @username\n"
                "• https://t.me/username\n\n"
                "⚠️ Добавление по ID не поддерживается. Используйте ссылку или username.",
                reply_markup=get_retry_keyboard("telegram_channel"),
            )
            return
    else:
        await state.update_data(retry_state="telegram_channel")
        await message.answer(
            "❌ Пожалуйста, используйте один из способов:\n\n"
            "• Перешлите сообщение из канала\n"
            "• Отправьте @username\n"
            "• Отправьте ссылку https://t.me/username\n\n"
            "⚠️ Добавление по ID не поддерживается.",
            reply_markup=get_retry_keyboard("telegram_channel"),
        )
        return

    user = await get_or_create_user(message.from_user.id, message.from_user.username)

    async with async_session_maker() as session:
        # Проверка существования канала
        if channel_id:
            result = await session.execute(select(TelegramChannel).where(TelegramChannel.channel_id == channel_id))
        else:
            result = await session.execute(select(TelegramChannel).where(TelegramChannel.channel_username == channel_username))

        telegram_channel = result.scalar_one_or_none()

        if not telegram_channel:
            if not channel_id:
                await message.answer(
                    "Не удалось определить ID канала. Попробуйте переслать сообщение из канала.",
                    reply_markup=get_retry_keyboard("telegram_channel"),
                )
                return

            # Валидация входных данных
            try:
                telegram_input = TelegramChannelInput(
                    channel_id=channel_id, channel_username=channel_username, channel_title=channel_title
                )
            except Exception as e:
                logger.warning("validation_error", error=str(e))
                await message.answer(
                    "❌ Ошибка валидации данных Telegram канала.", reply_markup=get_retry_keyboard("telegram_channel")
                )
                return

            # Проверка прав бота в канале
            try:
                bot = get_bot()
                bot_id = get_bot_id()
                member = await bot.get_chat_member(chat_id=channel_id, user_id=bot_id)
                if member.status not in ["administrator", "creator"]:
                    await message.answer(
                        "❌ Бот не является администратором канала. Добавьте бота в канал с правами администратора.",
                        reply_markup=get_retry_keyboard("telegram_channel"),
                    )
                    return
            except Exception as e:
                logger.warning(f"Не удалось проверить права бота в канале: {e}")

            telegram_channel = TelegramChannel(
                user_id=user.id,
                channel_id=telegram_input.channel_id,
                channel_username=telegram_input.channel_username,
                channel_title=telegram_input.channel_title,
            )
            session.add(telegram_channel)
            await session.commit()
            await session.refresh(telegram_channel)

        await state.update_data(telegram_channel_id=telegram_channel.id)
        await state.set_state(AddChannelStates.waiting_max_channel)

        await message.answer(
            f"Telegram-канал '{channel_title}' добавлен.\n\n"
            "Шаг 2: Отправьте ссылку на MAX-канал (пример: https://max.ru/username)",
            reply_markup=get_cancel_keyboard(),
            disable_web_page_preview=True,
        )


@router.message(AddChannelStates.waiting_max_channel)
async def process_max_channel(message: Message, state: FSMContext):
    """Обработка MAX канала."""
    import re

    user_input = message.text.strip() if message.text else ""

    if not user_input:
        await message.answer(
            "❌ Пожалуйста, укажите ссылку на MAX-канал.\n\n"
            "Формат: https://max.ru/username\n\n"
            "⚠️ Добавление по ID не поддерживается. Используйте ссылку.",
            reply_markup=get_retry_keyboard("max_channel"),
        )
        return

    user = await get_or_create_user(message.from_user.id, message.from_user.username)
    data = await state.get_data()
    telegram_channel_id = data.get("telegram_channel_id")

    # Извлекаем username из ссылки (только ссылки поддерживаются)
    max_channel_id = None
    channel_username = None
    is_from_link = False

    # Проверяем, является ли это ссылкой
    if re.match(r"https?://", user_input, re.IGNORECASE):
        is_from_link = True
        # Извлекаем username из ссылки
        # Поддерживаем форматы:
        # - https://max.ru/username
        # - https://max.ru/channel/username

        # Парсим URL
        url_parts = user_input.split("/")
        # Убираем query параметры и якоря
        last_part = url_parts[-1].split("?")[0].split("#")[0]

        # Если последняя часть - это "channel", берем предыдущую
        if last_part == "channel" and len(url_parts) >= 4:
            last_part = url_parts[-2]

        # Проверяем, не бот ли это (только если заканчивается на _bot)
        if last_part.endswith("_bot"):
            # Это бот, не канал
            await message.answer(
                "❌ Это ссылка на бота, а не на канал.\n\n" "Пожалуйста, укажите ссылку на MAX канал.",
                reply_markup=get_retry_keyboard("max_channel"),
            )
            return

        # Сохраняем полную ссылку для сравнения
        channel_username = last_part
        max_channel_id = last_part  # Используем для поиска
        # Нормализуем ссылку для сравнения (убираем протокол и www)
        normalized_user_link = re.sub(r"^https?://(?:www\.)?", "", user_input.lower()).rstrip("/")
        logger.info("max_channel_from_link", username=channel_username, link=user_input, normalized_link=normalized_user_link)
    else:
        # Не ссылка - отклоняем
        await message.answer(
            "❌ Пожалуйста, укажите ссылку на MAX-канал.\n\n"
            "Формат: https://max.ru/username\n\n"
            "⚠️ Добавление по ID или username без ссылки не поддерживается.",
            reply_markup=get_retry_keyboard("max_channel"),
        )
        return

    async with async_session_maker() as session:
        # Создание или получение MAX канала
        result = await session.execute(select(MaxChannel).where(MaxChannel.channel_id == max_channel_id))
        max_channel = result.scalar_one_or_none()

        if not max_channel:
            # Валидация входных данных
            try:
                max_input = MaxChannelInput(channel_id=max_channel_id)
            except Exception as e:
                logger.warning("validation_error", error=str(e))
                await message.answer("❌ Ошибка валидации данных MAX канала.", reply_markup=get_retry_keyboard("max_channel"))
                return

            # Пытаемся получить информацию о канале через MAX API
            channel_title = max_channel_id
            actual_channel_id = max_channel_id  # ID, который будем сохранять

            try:
                from app.max_api.client import MaxAPIClient

                max_client = MaxAPIClient()

                # Сначала пытаемся получить список доступных чатов
                # Это работает для всех случаев (и для ID, и для username)
                logger.info("getting_available_chats_for_channel", input=max_channel_id, is_link=is_from_link)
                available_chats = await max_client.get_available_chats()

                # Логируем полную структуру первых чатов для отладки
                logger.info(
                    "available_chats_received",
                    count=len(available_chats),
                    chats_preview=[dict(chat) for chat in available_chats[:5]],
                )  # Полная структура первых 5

                # Логируем все username из доступных чатов
                all_usernames = []
                for chat in available_chats:
                    username = None
                    if "username" in chat and chat["username"]:
                        username = chat["username"]
                    elif "name" in chat and chat["name"]:
                        username = chat["name"]
                    if username:
                        all_usernames.append(username)
                logger.info("available_chats_usernames", usernames=all_usernames, search_for=max_channel_id)

                found_chat = None

                # Ищем канал только по ссылке из поля 'link'
                # Сравниваем полные ссылки (нормализованные)
                # Нормализуем пользовательскую ссылку: убираем протокол, www, trailing slash
                normalized_user_link = re.sub(r"^https?://(?:www\.)?", "", user_input.lower()).rstrip("/")
                # Извлекаем последнюю часть (username/id) из пользовательской ссылки
                user_link_part = normalized_user_link.split("/")[-1].split("?")[0].split("#")[0].lower()

                found_username_from_link = None
                logger.info(
                    "searching_chat_by_link",
                    user_link=user_input,
                    normalized_user_link=normalized_user_link,
                    user_link_part=user_link_part,
                    available_chats_count=len(available_chats),
                )

                for idx, chat in enumerate(available_chats):
                    match_found = False
                    chat_username_raw = None

                    # Ищем только по полю 'link' - сравниваем полные ссылки или последнюю часть
                    if "link" in chat and chat["link"]:
                        chat_link = chat["link"]
                        # Нормализуем ссылку из API (убираем протокол и www)
                        normalized_chat_link = re.sub(r"^https?://(?:www\.)?", "", chat_link.lower()).rstrip("/")
                        # Извлекаем последнюю часть из ссылки API
                        chat_link_part = normalized_chat_link.split("/")[-1].split("?")[0].split("#")[0].lower()

                        # Сравниваем либо полные нормализованные ссылки, либо последнюю часть URL
                        match_found = (normalized_user_link == normalized_chat_link) or (user_link_part == chat_link_part)

                        # Извлекаем username/id из ссылки для логирования и сохранения
                        link_match = re.search(r"https?://(?:www\.)?max\.ru/([^/?#]+)", chat_link, re.IGNORECASE)
                        if link_match:
                            chat_username_raw = link_match.group(1)

                        # Логируем сравнение для отладки
                        logger.info(
                            "comparing_by_link",
                            chat_index=idx,
                            user_link=user_input,
                            chat_link=chat.get("link"),
                            normalized_user=normalized_user_link,
                            normalized_chat=normalized_chat_link if "link" in chat and chat["link"] else None,
                            user_part=user_link_part,
                            chat_part=chat_link_part if "link" in chat and chat["link"] else None,
                            match=match_found,
                        )

                        if match_found:
                            found_chat = chat
                            found_username_from_link = chat_username_raw
                            logger.info(
                                "max_channel_found_by_link",
                                user_link=user_input,
                                found_link=chat.get("link"),
                                found_username=found_username_from_link,
                                chat_id=chat.get("id") or chat.get("chat_id"),
                            )
                            break

                if found_chat:
                    # Если нашли канал, извлекаем все данные
                    # MAX API использует 'chat_id', а не 'id'
                    if "chat_id" in found_chat:
                        actual_channel_id = str(found_chat["chat_id"])
                    elif "id" in found_chat:
                        actual_channel_id = str(found_chat["id"])

                    if "title" in found_chat:
                        channel_title = found_chat["title"]
                    elif "name" in found_chat:
                        channel_title = found_chat["name"]

                    # Извлекаем username из поля 'link' (https://max.ru/username или https://max.ru/id123_biz)
                    # Это единственный надежный источник для сравнения
                    if "link" in found_chat and found_chat["link"]:
                        link = found_chat["link"]
                        link_match = re.search(r"https?://(?:www\.)?max\.ru/([^/?#]+)", link, re.IGNORECASE)
                        if link_match:
                            extracted_username = link_match.group(1)
                            # Пропускаем только служебные пути, но не id*_biz или id*_bot (это валидные каналы)
                            if extracted_username != "channel":
                                channel_username = extracted_username
                                logger.info("username_extracted_from_link", username=channel_username, link=link)

                    # Если username не был извлечен из link, используем найденный при поиске
                    if not channel_username and found_username_from_link:
                        channel_username = found_username_from_link
                    elif not channel_username:
                        channel_username = max_channel_id

                    logger.info(
                        "max_channel_found",
                        original_input=max_channel_id,
                        channel_id=actual_channel_id,
                        title=channel_title,
                        username=channel_username,
                        is_from_link=is_from_link,
                    )
                else:
                    # Не нашли в списке доступных чатов
                    logger.warning(
                        "chat_not_found_in_available",
                        input=max_channel_id,
                        link=user_input,
                        available_chats_count=len(available_chats),
                    )
                    await max_client.close()

                    error_msg = (
                        f"❌ Не удалось найти канал по ссылке '{user_input}'.\n\n"
                        "Возможные причины:\n"
                        "• Бот не добавлен в канал как администратор\n"
                        "• Ссылка указана неверно\n"
                        "• Канал не существует или недоступен\n\n"
                        "Убедитесь, что:\n"
                        "1. Бот добавлен в канал как администратор\n"
                        "2. Ссылка на канал указана правильно (https://max.ru/username)\n"
                        "3. Канал существует в MAX"
                    )

                    await message.answer(error_msg, reply_markup=get_retry_keyboard("max_channel"))
                    return

                await max_client.close()
                logger.info(
                    "max_channel_info_retrieved", channel_id=actual_channel_id, title=channel_title, username=channel_username
                )
            except APIError as e:
                logger.warning("failed_to_get_max_chat_info", channel_id=max_channel_id, error=str(e))
                await message.answer(
                    f"❌ Не удалось найти канал по ссылке '{user_input}'.\n\n"
                    "Проверьте:\n"
                    "• Правильность ссылки (https://max.ru/username)\n"
                    "• Что бот добавлен в канал как администратор\n"
                    "• Что канал существует",
                    reply_markup=get_retry_keyboard("max_channel"),
                )
                return
            except Exception as e:
                logger.warning("failed_to_get_max_chat_info", channel_id=max_channel_id, error=str(e))
                await message.answer(
                    f"❌ Ошибка при получении информации о канале '{user_input}'.\n\n"
                    "Проверьте правильность ссылки на канал.",
                    reply_markup=get_retry_keyboard("max_channel"),
                )
                return

            # Используем actual_channel_id для сохранения
            max_channel = MaxChannel(
                user_id=user.id, channel_id=actual_channel_id, channel_username=channel_username, channel_title=channel_title
            )
            session.add(max_channel)
            await session.commit()
            await session.refresh(max_channel)

        # Создание связи
        try:
            # КРИТИЧНО: Загружаем telegram_channel из базы для получения channel_id
            telegram_channel_result = await session.execute(
                select(TelegramChannel).where(TelegramChannel.id == telegram_channel_id)
            )
            telegram_channel = telegram_channel_result.scalar_one_or_none()

            if not telegram_channel:
                await message.answer(
                    "❌ Ошибка: Telegram канал не найден в базе данных.", reply_markup=get_retry_keyboard("add_channel")
                )
                logger.error("telegram_channel_not_found_in_db", telegram_channel_id=telegram_channel_id)
                return

            # Проверяем, является ли это первой связью пользователя
            from datetime import datetime, timedelta

            links_count_result = await session.execute(
                select(func.count(CrosspostingLink.id)).where(CrosspostingLink.user_id == user.id)
            )
            links_count = links_count_result.scalar() or 0
            is_first_link = links_count == 0

            # Определяем статус подписки в зависимости от VIP статуса и номера связи
            if user.is_vip:
                # VIP пользователи - все связи бесплатные
                subscription_status = "vip"
                free_trial_end_date = None
                subscription_end_date = None
                is_enabled = True
            elif is_first_link:
                # Первая связь - бесплатный период 30 дней
                subscription_status = "free_trial"
                free_trial_end_date = datetime.utcnow() + timedelta(days=30)
                subscription_end_date = None
                is_enabled = True
            else:
                # Последующие связи - требуют оплаты
                subscription_status = "expired"
                free_trial_end_date = None
                subscription_end_date = None
                is_enabled = False  # Неактивна до оплаты

            crossposting_link = CrosspostingLink(
                user_id=user.id,
                telegram_channel_id=telegram_channel_id,
                max_channel_id=max_channel.id,
                is_enabled=is_enabled,
                subscription_status=subscription_status,
                free_trial_end_date=free_trial_end_date,
                subscription_end_date=subscription_end_date,
                is_first_link=is_first_link,
            )
            session.add(crossposting_link)
            await session.commit()
            await session.refresh(crossposting_link)

            # КРИТИЧНО: Очищаем кэш для канала при создании связи
            # Используем channel_id из загруженного telegram_channel
            if telegram_channel and telegram_channel.channel_id:
                cache_key = f"channel_links:{telegram_channel.channel_id}"
                await delete_cache(cache_key)
                logger.info(
                    "cache_cleared_on_link_creation", channel_id=telegram_channel.channel_id, link_id=crossposting_link.id
                )

            await log_audit(
                user.id,
                AuditAction.CREATE_LINK.value,
                "crossposting_link",
                crossposting_link.id,
                {"telegram_channel_id": telegram_channel_id, "max_channel_id": max_channel.id},
            )

            # Формируем сообщение в зависимости от статуса подписки
            if user.is_vip:
                # VIP пользователи
                await message.answer(
                    f"✅ Связь создана успешно! ⭐ VIP\n\n"
                    f"Telegram: {telegram_channel.channel_username or telegram_channel.channel_title}\n"
                    f"MAX: {max_channel.channel_username or max_channel.channel_title}\n\n"
                    f"Кросспостинг активирован.",
                    reply_markup=get_main_keyboard(),
                )
            elif is_first_link:
                # Первая связь - бесплатный период
                free_trial_end = free_trial_end_date.strftime("%d.%m.%Y %H:%M") if free_trial_end_date else "N/A"
                await message.answer(
                    f"✅ Связь создана успешно!\n\n"
                    f"Telegram: {telegram_channel.channel_username or telegram_channel.channel_title}\n"
                    f"MAX: {max_channel.channel_username or max_channel.channel_title}\n\n"
                    f"📅 Бесплатный период: до {free_trial_end}\n"
                    f"✅ Кросспостинг активирован.",
                    reply_markup=get_main_keyboard(),
                )
            else:
                # Последующие связи - требуют оплаты
                # Создаем платеж в YooKassa
                import concurrent.futures

                try:
                    loop = asyncio.get_event_loop()
                    with concurrent.futures.ThreadPoolExecutor() as executor:
                        payment_info = await loop.run_in_executor(executor, create_payment, crossposting_link.id, user.id)

                    # Сохраняем информацию о платеже
                    crossposting_link.yookassa_payment_id = payment_info["payment_id"]
                    crossposting_link.payment_status = "pending"
                    await session.commit()

                    # Отправляем сообщение с ссылкой на оплату
                    payment_keyboard = InlineKeyboardMarkup(
                        inline_keyboard=[
                            [InlineKeyboardButton(text="💳 Оплатить подписку", url=payment_info["confirmation_url"])]
                        ]
                    )

                    await message.answer(
                        f"📊 Связь создана\n\n"
                        f"Telegram: {telegram_channel.channel_username or telegram_channel.channel_title}\n"
                        f"MAX: {max_channel.channel_username or max_channel.channel_title}\n\n"
                        f"⚠️ Для активации связи требуется оплата подписки.\n\n"
                        f"Сумма: {payment_info['amount']:.0f} ₽\n"
                        f"Период: 30 дней\n\n"
                        f"После оплаты связь будет активирована на 30 дней.",
                        reply_markup=payment_keyboard,
                    )
                except Exception as e:
                    logger.error("payment_creation_error", error=str(e), link_id=crossposting_link.id, user_id=user.id)
                    await message.answer(
                        f"📊 Связь создана\n\n"
                        f"Telegram: {telegram_channel.channel_username or telegram_channel.channel_title}\n"
                        f"MAX: {max_channel.channel_username or max_channel.channel_title}\n\n"
                        f"⚠️ Для активации связи требуется оплата подписки.\n\n"
                        f"Сумма: 200 ₽\n"
                        f"Период: 30 дней\n\n"
                        f"❌ Ошибка при создании платежа. Попробуйте позже через команду /pay_link {crossposting_link.id}",
                        reply_markup=get_main_keyboard(),
                    )

            # Отправляем предложение миграции только для активных связей
            if is_enabled:
                migration_text = (
                    "Перед началом работы вы можете один раз перенести последние 30 постов из Telegram-канала в MAX-канал."
                )
                migration_keyboard = get_migration_offer_keyboard(crossposting_link.id)
                await message.answer(migration_text, reply_markup=migration_keyboard)

            logger.info("crossposting_link_created", link_id=crossposting_link.id, user_id=user.id)
        except Exception as e:
            error_message = str(e)
            error_type = type(e).__name__

            # Безопасно получаем ID каналов для логирования
            tg_ch_id = telegram_channel_id if "telegram_channel_id" in locals() else None
            max_ch_id = max_channel.id if "max_channel" in locals() else None

            # Определяем тип ошибки для более информативного сообщения
            if (
                "uq_telegram_max_channels" in error_message
                or "unique constraint" in error_message.lower()
                or "duplicate" in error_message.lower()
            ):
                user_message = (
                    "❌ Такая связь уже существует.\n\n"
                    "Эта комбинация Telegram и MAX каналов уже связана.\n"
                    "Используйте /list_channels для просмотра существующих связей."
                )
            elif "foreign key" in error_message.lower() or "constraint" in error_message.lower():
                user_message = "❌ Ошибка при создании связи.\n\n" "Проверьте, что оба канала существуют в системе."
            else:
                user_message = (
                    f"❌ Ошибка при создании связи.\n\n"
                    f"Тип ошибки: {error_type}\n"
                    "Попробуйте позже или обратитесь в поддержку."
                )

            await message.answer(user_message, reply_markup=get_retry_keyboard("add_channel"))
            logger.error(
                "failed_to_create_link",
                error=error_message,
                error_type=error_type,
                telegram_channel_id=tg_ch_id,
                max_channel_id=max_ch_id,
                exc_info=True,
            )

        await state.clear()


@router.message(Command("list_channels"))
async def cmd_list_channels(message: Message, state: FSMContext):
    """Обработчик команды /list_channels."""
    await show_channels_list(message, state)


@router.message(F.text == "📋 Список связей")
async def message_list_channels(message: Message, state: FSMContext):
    """Обработчик кнопки списка связей."""
    await state.update_data(channels_list_page=0)
    await show_channels_list(message, state)


async def show_channels_list(message: Message, state: FSMContext = None, page: int = 0):
    """Показать список связей с клавиатурой."""
    telegram_user_id = message.from_user.id
    username = message.from_user.username

    user = await get_or_create_user(telegram_user_id, username)

    async with async_session_maker() as session:
        result = await session.execute(
            select(CrosspostingLink)
            .options(selectinload(CrosspostingLink.telegram_channel), selectinload(CrosspostingLink.max_channel))
            .where(CrosspostingLink.user_id == user.id)
            .order_by(CrosspostingLink.created_at.desc())
        )
        links = result.scalars().all()

        if not links:
            text = "У вас пока нет созданных связей. Используйте кнопку «➕ Добавить связь» для создания."
            await message.answer(text, reply_markup=get_back_to_menu_keyboard())
            return

        # Подготовка данных для клавиатуры
        links_data = []
        button_to_link_id = {}  # Маппинг текста кнопки -> link_id
        for link in links:
            telegram_title = link.telegram_channel.channel_title
            max_title = link.max_channel.channel_title
            status_icon = "✅" if link.is_enabled else "❌"
            # Формируем текст кнопки так же, как в keyboards.py
            telegram_short = telegram_title[:20] + "..." if len(telegram_title) > 20 else telegram_title
            max_short = max_title[:20] + "..." if len(max_title) > 20 else max_title
            button_text = f"{status_icon} {telegram_short} - {max_short}"

            links_data.append(
                {"id": link.id, "telegram_title": telegram_title, "max_title": max_title, "is_enabled": link.is_enabled}
            )
            button_to_link_id[button_text] = link.id

        text = "📋 Ваши связи каналов:\n\nВыберите связь для управления:"
        keyboard = get_channels_list_keyboard(links_data, page=page)

        if state:
            await state.set_state(LinkManagementStates.viewing_channels_list)
            await state.update_data(channels_list_page=page, links_data=links_data, button_to_link_id=button_to_link_id)
            logger.info(
                "channels_list_shown",
                user_id=message.from_user.id,
                page=page,
                total_links=len(links),
                mapping_size=len(button_to_link_id),
                sample_keys=list(button_to_link_id.keys())[:3] if button_to_link_id else [],
            )

        await message.answer(text, reply_markup=keyboard)


@router.message(F.text.in_(["◀️ Назад", "Вперед ▶️"]))
async def message_list_channels_nav(message: Message, state: FSMContext):
    """Обработчик навигации по списку связей."""
    data = await state.get_data()
    current_page = data.get("channels_list_page", 0)
    links_data = data.get("links_data", [])

    if not links_data:
        await message.answer(
            "Список связей не найден. Используйте кнопку «📋 Список связей».", reply_markup=get_main_keyboard()
        )
        return

    per_page = 5
    if message.text == "◀️ Назад":
        new_page = max(0, current_page - 1)
    else:  # "Вперед ▶️"
        new_page = min((len(links_data) - 1) // per_page, current_page + 1)

    await state.update_data(channels_list_page=new_page)
    await show_channels_list(message, state, page=new_page)


async def show_link_detail(message: Message, state: FSMContext, link_id: int):
    """Показать детали связи."""
    from datetime import datetime, timedelta
    from app.bot.handlers_payments import format_subscription_info

    user = await get_or_create_user(message.from_user.id, message.from_user.username)

    async with async_session_maker() as session:
        result = await session.execute(
            select(CrosspostingLink)
            .options(selectinload(CrosspostingLink.telegram_channel), selectinload(CrosspostingLink.max_channel))
            .where(CrosspostingLink.id == link_id)
            .where(CrosspostingLink.user_id == user.id)
        )
        link = result.scalar_one_or_none()

        if not link:
            await message.answer("Связь не найдена.")
            return

        # Статистика по связи
        success_count = await session.execute(
            select(func.count(MessageLog.id))
            .where(MessageLog.crossposting_link_id == link.id)
            .where(MessageLog.status == MessageStatus.SUCCESS.value)
        )
        failed_count = await session.execute(
            select(func.count(MessageLog.id))
            .where(MessageLog.crossposting_link_id == link.id)
            .where(MessageLog.status == MessageStatus.FAILED.value)
        )

        # Последняя успешная отправка
        last_success = await session.execute(
            select(MessageLog)
            .where(MessageLog.crossposting_link_id == link.id)
            .where(MessageLog.status == MessageStatus.SUCCESS.value)
            .order_by(MessageLog.sent_at.desc())
            .limit(1)
        )
        last_success_msg = last_success.scalar_one_or_none()

        status_icon = "✅" if link.is_enabled else "❌"

        # Формируем информацию о подписке
        status_icons = {
            "vip": "⭐ VIP",
            "free_trial": "🆓 Бесплатный период",
            "active": "✅ Активна",
            "expired": "⚠️ Истекла",
            "cancelled": "❌ Отменена",
        }
        status_text = status_icons.get(link.subscription_status, link.subscription_status)

        subscription_type_text = ""
        if link.subscription_status == "vip":
            subscription_type_text = "VIP (бесплатно)"
        elif link.is_first_link:
            subscription_type_text = "Первая связь (бесплатно)"
        else:
            subscription_type_text = "Платная подписка"

        # Определяем дату окончания
        end_date = link.subscription_end_date or link.free_trial_end_date
        subscription_details = ""
        if end_date:
            now = datetime.utcnow()
            if end_date > now:
                delta = end_date - now
                days = delta.days
                hours = delta.seconds // 3600
                if days > 0:
                    subscription_details = f"Осталось: {days} дней\n"
                else:
                    subscription_details = f"Осталось: {hours} часов\n"
                subscription_details += f"Окончание: {end_date.strftime('%d.%m.%Y %H:%M')}\n"
            else:
                delta = now - end_date
                days = delta.days
                subscription_details = f"Истекла {days} дней назад\n"
                subscription_details += f"Окончание: {end_date.strftime('%d.%m.%Y %H:%M')}\n"

        text = (
            f"{status_icon} Связь #{link.id}\n\n"
            f"Telegram: {link.telegram_channel.channel_title}\n"
            f"MAX: {link.max_channel.channel_title}\n"
            f"Статус: {'Активна' if link.is_enabled else 'Неактивна'}\n"
            f"Создана: {link.created_at.strftime('%Y-%m-%d %H:%M')}\n"
            f"Подписка: {status_text}\n"
            f"Тип подписки: {subscription_type_text}\n"
            f"{subscription_details}\n"
            f"📊 Статистика:\n"
            f"Успешных: {success_count.scalar() or 0}\n"
            f"Неудачных: {failed_count.scalar() or 0}"
        )

        if last_success_msg:
            text += f"\n\nПоследняя отправка: {last_success_msg.sent_at.strftime('%Y-%m-%d %H:%M:%S')}"

        # Создаем комбинированную клавиатуру: ReplyKeyboardMarkup + InlineKeyboardMarkup
        reply_keyboard = get_link_detail_keyboard(link_id, link.is_enabled)

        # Добавляем инлайн-кнопки для продления/оплаты подписки
        inline_buttons = []
        if link.subscription_status in ("active", "free_trial") and not user.is_vip:
            inline_buttons.append([InlineKeyboardButton(text="🔄 Продлить подписку", callback_data=f"renew_link_{link.id}")])
        elif link.subscription_status == "expired" and not user.is_vip:
            inline_buttons.append([InlineKeyboardButton(text="💳 Оплатить подписку", callback_data=f"pay_link_{link.id}")])

        inline_keyboard = InlineKeyboardMarkup(inline_keyboard=inline_buttons) if inline_buttons else None

        await state.set_state(LinkManagementStates.viewing_link_detail)
        await state.update_data(current_link_id=link_id)

        # Отправляем сообщение с инлайн-кнопками, если есть
        if inline_keyboard:
            await message.answer(text, reply_markup=inline_keyboard)
            # Отправляем reply-клавиатуру отдельным сообщением
            await message.answer("Действия:", reply_markup=reply_keyboard)
        else:
            await message.answer(text, reply_markup=reply_keyboard)

        logger.info("link_detail_shown", link_id=link_id, user_id=user.id)


@router.message(LinkManagementStates.viewing_channels_list, F.text.startswith("✅") | F.text.startswith("❌"))
async def message_link_selected(message: Message, state: FSMContext):
    """Обработчик выбора связи из списка."""
    logger.info("message_link_selected_called", user_id=message.from_user.id, message_text=message.text)

    # Проверяем, что текст содержит " - " (формат кнопки связи)
    if not message.text or " - " not in message.text:
        logger.info("message_link_selected_skipped_no_dash", user_id=message.from_user.id, message_text=message.text)
        return

    data = await state.get_data()
    button_to_link_id = data.get("button_to_link_id", {})

    logger.info(
        "link_selection_attempt",
        user_id=message.from_user.id,
        message_text=message.text,
        has_mapping=bool(button_to_link_id),
        mapping_keys=list(button_to_link_id.keys())[:3] if button_to_link_id else [],
    )

    if not button_to_link_id:
        # Если маппинг не найден, возможно пользователь не в списке связей
        logger.warning("link_selection_no_mapping", user_id=message.from_user.id, message_text=message.text)
        return

    # Ищем link_id по тексту кнопки
    link_id = button_to_link_id.get(message.text)

    if not link_id:
        # Текст не соответствует ни одной кнопке из списка
        logger.warning(
            "link_selection_not_found",
            user_id=message.from_user.id,
            message_text=message.text,
            available_keys=list(button_to_link_id.keys())[:5],
        )
        return

    logger.info("link_selected", user_id=message.from_user.id, link_id=link_id, message_text=message.text)
    await show_link_detail(message, state, link_id)


@router.message(Command("status"))
async def cmd_status(message: Message):
    """Обработчик команды /status."""
    # Проверка, указан ли link_id
    command_parts = message.text.split()
    if len(command_parts) > 1:
        try:
            link_id = int(command_parts[1])
            user = await get_or_create_user(message.from_user.id, message.from_user.username)
            await cmd_status_detail(message, user, link_id)
            return
        except ValueError:
            pass

    await show_status(message)


@router.message(F.text == "📊 Статус")
async def message_status(message: Message):
    """Обработчик кнопки статуса."""
    await show_status(message)


async def show_status(message: Message):
    """Показать общий статус кросспостинга."""
    telegram_user_id = message.from_user.id
    username = message.from_user.username

    user = await get_or_create_user(telegram_user_id, username)

    async with async_session_maker() as session:
        result = await session.execute(select(CrosspostingLink).where(CrosspostingLink.user_id == user.id))
        links = result.scalars().all()

        active_count = sum(1 for link in links if link.is_enabled)
        inactive_count = len(links) - active_count

        # Подсчет статистики отправок
        success_count = await session.execute(
            select(func.count(MessageLog.id))
            .join(CrosspostingLink)
            .where(CrosspostingLink.user_id == user.id)
            .where(MessageLog.status == MessageStatus.SUCCESS.value)
        )
        failed_count = await session.execute(
            select(func.count(MessageLog.id))
            .join(CrosspostingLink)
            .where(CrosspostingLink.user_id == user.id)
            .where(MessageLog.status == MessageStatus.FAILED.value)
        )

        text = (
            f"📊 Статус кросспостинга:\n\n"
            f"Активных связей: {active_count}\n"
            f"Неактивных связей: {inactive_count}\n"
            f"Всего связей: {len(links)}\n\n"
            f"Успешных отправок: {success_count.scalar() or 0}\n"
            f"Неудачных отправок: {failed_count.scalar() or 0}\n\n"
            f"Используйте список связей для детальной информации."
        )

        await message.answer(text, reply_markup=get_back_to_menu_keyboard())


async def cmd_status_detail(message: Message, user: User, link_id: int):
    """Детальный статус связи."""
    async with async_session_maker() as session:
        result = await session.execute(
            select(CrosspostingLink).where(CrosspostingLink.id == link_id).where(CrosspostingLink.user_id == user.id)
        )
        link = result.scalar_one_or_none()

        if not link:
            await message.answer("Связь не найдена.")
            return

        # Статистика по связи
        success_count = await session.execute(
            select(func.count(MessageLog.id))
            .where(MessageLog.crossposting_link_id == link.id)
            .where(MessageLog.status == MessageStatus.SUCCESS.value)
        )
        failed_count = await session.execute(
            select(func.count(MessageLog.id))
            .where(MessageLog.crossposting_link_id == link.id)
            .where(MessageLog.status == MessageStatus.FAILED.value)
        )

        # Последняя успешная отправка
        last_success = await session.execute(
            select(MessageLog)
            .where(MessageLog.crossposting_link_id == link.id)
            .where(MessageLog.status == MessageStatus.SUCCESS.value)
            .order_by(MessageLog.sent_at.desc())
            .limit(1)
        )
        last_success_msg = last_success.scalar_one_or_none()

        # Последняя ошибка
        last_error = await session.execute(
            select(MessageLog)
            .where(MessageLog.crossposting_link_id == link.id)
            .where(MessageLog.status == MessageStatus.FAILED.value)
            .order_by(MessageLog.created_at.desc())
            .limit(1)
        )
        last_error_msg = last_error.scalar_one_or_none()

        status_icon = "✅" if link.is_enabled else "❌"
        text = (
            f"{status_icon} Связь #{link.id}\n\n"
            f"Telegram: {link.telegram_channel.channel_title}\n"
            f"MAX: {link.max_channel.channel_title}\n"
            f"Статус: {'Активна' if link.is_enabled else 'Неактивна'}\n\n"
            f"Статистика:\n"
            f"Успешных: {success_count.scalar() or 0}\n"
            f"Неудачных: {failed_count.scalar() or 0}\n\n"
        )

        if last_success_msg:
            text += f"Последняя отправка: {last_success_msg.sent_at.strftime('%Y-%m-%d %H:%M:%S')}\n"

        if last_error_msg:
            text += f"\nПоследняя ошибка:\n{last_error_msg.error_message[:200]}\n"

        await message.answer(text)


@router.message(Command("enable"))
async def cmd_enable(message: Message):
    """Включить кросспостинг для связи."""
    command_parts = message.text.split()
    if len(command_parts) < 2:
        await message.answer("Использование: /enable <link_id>")
        return

    try:
        link_id = int(command_parts[1])
    except ValueError:
        await message.answer("Неверный формат ID связи.")
        return

    user = await get_or_create_user(message.from_user.id, message.from_user.username)

    async with async_session_maker() as session:
        result = await session.execute(
            select(CrosspostingLink)
            .options(selectinload(CrosspostingLink.telegram_channel))
            .where(CrosspostingLink.id == link_id)
            .where(CrosspostingLink.user_id == user.id)
        )
        link = result.scalar_one_or_none()

        if not link:
            await message.answer("Связь не найдена.")
            return

        # КРИТИЧНО: Сохраняем channel_id перед изменением для очистки кэша
        telegram_channel_id_for_cache = None
        if link.telegram_channel:
            telegram_channel_id_for_cache = link.telegram_channel.channel_id

        link.is_enabled = True
        await session.commit()

        # КРИТИЧНО: Очищаем кэш для канала при изменении статуса связи
        if telegram_channel_id_for_cache:
            cache_key = f"channel_links:{telegram_channel_id_for_cache}"
            await delete_cache(cache_key)
            logger.info("cache_cleared_on_link_enable", channel_id=telegram_channel_id_for_cache, link_id=link_id)

        await log_audit(user.id, AuditAction.ENABLE_LINK.value, "crossposting_link", link_id)

        await message.answer(f"✅ Кросспостинг для связи #{link_id} включен.")
        logger.info("link_enabled", link_id=link_id, user_id=user.id)


@router.message(Command("disable"))
async def cmd_disable(message: Message):
    """Отключить кросспостинг для связи."""
    command_parts = message.text.split()
    if len(command_parts) < 2:
        await message.answer("Использование: /disable <link_id>")
        return

    try:
        link_id = int(command_parts[1])
    except ValueError:
        await message.answer("Неверный формат ID связи.")
        return

    user = await get_or_create_user(message.from_user.id, message.from_user.username)

    async with async_session_maker() as session:
        result = await session.execute(
            select(CrosspostingLink)
            .options(selectinload(CrosspostingLink.telegram_channel))
            .where(CrosspostingLink.id == link_id)
            .where(CrosspostingLink.user_id == user.id)
        )
        link = result.scalar_one_or_none()

        if not link:
            await message.answer("Связь не найдена.")
            return

        # КРИТИЧНО: Сохраняем channel_id перед изменением для очистки кэша
        telegram_channel_id_for_cache = None
        if link.telegram_channel:
            telegram_channel_id_for_cache = link.telegram_channel.channel_id

        link.is_enabled = False
        await session.commit()

        # КРИТИЧНО: Очищаем кэш для канала при изменении статуса связи
        if telegram_channel_id_for_cache:
            cache_key = f"channel_links:{telegram_channel_id_for_cache}"
            await delete_cache(cache_key)
            logger.info("cache_cleared_on_link_disable", channel_id=telegram_channel_id_for_cache, link_id=link_id)

        await log_audit(user.id, AuditAction.DISABLE_LINK.value, "crossposting_link", link_id)

        await message.answer(f"❌ Кросспостинг для связи #{link_id} отключен.")
        logger.info("link_disabled", link_id=link_id, user_id=user.id)


@router.message(Command("delete"))
async def cmd_delete(message: Message):
    """Удалить связь каналов."""
    command_parts = message.text.split()
    if len(command_parts) < 2:
        await message.answer("Использование: /delete <link_id>")
        return

    try:
        link_id = int(command_parts[1])
    except ValueError:
        await message.answer("Неверный формат ID связи.")
        return

    user = await get_or_create_user(message.from_user.id, message.from_user.username)

    async with async_session_maker() as session:
        result = await session.execute(
            select(CrosspostingLink).where(CrosspostingLink.id == link_id).where(CrosspostingLink.user_id == user.id)
        )
        link = result.scalar_one_or_none()

        if not link:
            await message.answer("Связь не найдена.")
            return

        # КРИТИЧНО: Сохраняем channel_id перед удалением для очистки кэша
        telegram_channel_id_for_cache = None
        if link.telegram_channel:
            await session.refresh(link.telegram_channel)
            telegram_channel_id_for_cache = link.telegram_channel.channel_id

        # Сохраняем ID каналов для проверки после удаления
        telegram_channel_id_for_cleanup = link.telegram_channel_id
        max_channel_id_for_cleanup = link.max_channel_id

        await session.delete(link)
        await session.commit()

        # КРИТИЧНО: Очищаем кэш для канала при удалении связи
        if telegram_channel_id_for_cache:
            cache_key = f"channel_links:{telegram_channel_id_for_cache}"
            await delete_cache(cache_key)
            logger.info("cache_cleared_on_link_delete", channel_id=telegram_channel_id_for_cache, link_id=link_id)

        # Очистка неиспользуемых каналов после удаления связи
        async with async_session_maker() as cleanup_session:
            # Проверяем, есть ли еще связи у Telegram канала
            telegram_links_count = await cleanup_session.execute(
                select(func.count(CrosspostingLink.id)).where(
                    CrosspostingLink.telegram_channel_id == telegram_channel_id_for_cleanup
                )
            )
            if telegram_links_count.scalar() == 0:
                # Нет больше связей - удаляем Telegram канал
                result_tg = await cleanup_session.execute(
                    select(TelegramChannel).where(TelegramChannel.id == telegram_channel_id_for_cleanup)
                )
                tg_channel = result_tg.scalar_one_or_none()
                if tg_channel:
                    await cleanup_session.delete(tg_channel)
                    logger.info("telegram_channel_cleaned_up", channel_id=tg_channel.id, title=tg_channel.channel_title)

            # Проверяем, есть ли еще связи у MAX канала
            max_links_count = await cleanup_session.execute(
                select(func.count(CrosspostingLink.id)).where(CrosspostingLink.max_channel_id == max_channel_id_for_cleanup)
            )
            if max_links_count.scalar() == 0:
                # Нет больше связей - удаляем MAX канал
                result_max = await cleanup_session.execute(
                    select(MaxChannel).where(MaxChannel.id == max_channel_id_for_cleanup)
                )
                max_channel = result_max.scalar_one_or_none()
                if max_channel:
                    await cleanup_session.delete(max_channel)
                    logger.info("max_channel_cleaned_up", channel_id=max_channel.id, title=max_channel.channel_title)

            await cleanup_session.commit()

        await log_audit(user.id, AuditAction.DELETE_LINK.value, "crossposting_link", link_id)

        await message.answer(f"🗑️ Связь #{link_id} удалена.")
        logger.info("link_deleted", link_id=link_id, user_id=user.id)


# ============================================================================
# Обработчики message для кнопок управления связями
# ============================================================================


@router.message(LinkManagementStates.viewing_link_detail, F.text == "▶️ Включить")
async def message_enable(message: Message, state: FSMContext):
    """Обработчик кнопки включения связи."""
    data = await state.get_data()
    link_id = data.get("current_link_id")

    if not link_id:
        await message.answer("Ошибка: не найдена текущая связь.")
        return

    user = await get_or_create_user(message.from_user.id, message.from_user.username)

    async with async_session_maker() as session:
        result = await session.execute(
            select(CrosspostingLink)
            .options(selectinload(CrosspostingLink.telegram_channel), selectinload(CrosspostingLink.max_channel))
            .where(CrosspostingLink.id == link_id)
            .where(CrosspostingLink.user_id == user.id)
        )
        link = result.scalar_one_or_none()

        if not link:
            await message.answer("Связь не найдена.")
            return

        if link.is_enabled:
            await message.answer("Связь уже включена.")
            return

        # КРИТИЧНО: Сохраняем channel_id перед изменением для очистки кэша
        telegram_channel_id_for_cache = None
        if link.telegram_channel:
            telegram_channel_id_for_cache = link.telegram_channel.channel_id

        link.is_enabled = True
        await session.commit()

        # КРИТИЧНО: Очищаем кэш для канала при изменении статуса связи
        if telegram_channel_id_for_cache:
            cache_key = f"channel_links:{telegram_channel_id_for_cache}"
            await delete_cache(cache_key)
            logger.info("cache_cleared_on_link_enable", channel_id=telegram_channel_id_for_cache, link_id=link_id)

        await log_audit(user.id, AuditAction.ENABLE_LINK.value, "crossposting_link", link_id)

        # Обновляем сообщение
        status_icon = "✅"
        text = (
            f"{status_icon} Связь {link.telegram_channel.channel_title} - {link.max_channel.channel_title}\n\n"
            f"✅ Кросспостинг включен\n\n"
            f"Telegram: {link.telegram_channel.channel_title}\n"
            f"MAX: {link.max_channel.channel_title}\n"
            f"Статус: Активна\n"
            f"Создана: {link.created_at.strftime('%Y-%m-%d %H:%M')}"
        )

        keyboard = get_link_detail_keyboard(link_id, True)
        await message.answer(text, reply_markup=keyboard)
        logger.info("link_enabled", link_id=link_id, user_id=user.id)


@router.message(LinkManagementStates.viewing_link_detail, F.text == "⏸ Отключить")
async def message_disable(message: Message, state: FSMContext):
    """Обработчик кнопки отключения связи."""
    data = await state.get_data()
    link_id = data.get("current_link_id")

    if not link_id:
        await message.answer("Ошибка: не найдена текущая связь.")
        return

    user = await get_or_create_user(message.from_user.id, message.from_user.username)

    async with async_session_maker() as session:
        result = await session.execute(
            select(CrosspostingLink)
            .options(selectinload(CrosspostingLink.telegram_channel), selectinload(CrosspostingLink.max_channel))
            .where(CrosspostingLink.id == link_id)
            .where(CrosspostingLink.user_id == user.id)
        )
        link = result.scalar_one_or_none()

        if not link:
            await message.answer("Связь не найдена.")
            return

        if not link.is_enabled:
            await message.answer("Связь уже отключена.")
            return

        # КРИТИЧНО: Сохраняем channel_id перед изменением для очистки кэша
        telegram_channel_id_for_cache = None
        if link.telegram_channel:
            telegram_channel_id_for_cache = link.telegram_channel.channel_id

        link.is_enabled = False
        await session.commit()

        # КРИТИЧНО: Очищаем кэш для канала при изменении статуса связи
        if telegram_channel_id_for_cache:
            cache_key = f"channel_links:{telegram_channel_id_for_cache}"
            await delete_cache(cache_key)
            logger.info("cache_cleared_on_link_disable", channel_id=telegram_channel_id_for_cache, link_id=link_id)

        await log_audit(user.id, AuditAction.DISABLE_LINK.value, "crossposting_link", link_id)

        # Обновляем сообщение
        status_icon = "❌"
        text = (
            f"{status_icon} Связь {link.telegram_channel.channel_title} - {link.max_channel.channel_title}\n\n"
            f"❌ Кросспостинг отключен\n\n"
            f"Telegram: {link.telegram_channel.channel_title}\n"
            f"MAX: {link.max_channel.channel_title}\n"
            f"Статус: Неактивна\n"
            f"Создана: {link.created_at.strftime('%Y-%m-%d %H:%M')}"
        )

        keyboard = get_link_detail_keyboard(link_id, False)
        await message.answer(text, reply_markup=keyboard)
        logger.info("link_disabled", link_id=link_id, user_id=user.id)


@router.message(LinkManagementStates.viewing_link_detail, F.text == "🗑 Удалить")
async def message_delete_confirm(message: Message, state: FSMContext):
    """Обработчик кнопки подтверждения удаления."""
    data = await state.get_data()
    link_id = data.get("current_link_id")

    logger.info("delete_confirm_clicked", user_id=message.from_user.id, link_id=link_id)

    if not link_id:
        await message.answer("Ошибка: не найдена текущая связь.")
        return

    user = await get_or_create_user(message.from_user.id, message.from_user.username)

    async with async_session_maker() as session:
        result = await session.execute(
            select(CrosspostingLink)
            .options(selectinload(CrosspostingLink.telegram_channel), selectinload(CrosspostingLink.max_channel))
            .where(CrosspostingLink.id == link_id)
            .where(CrosspostingLink.user_id == user.id)
        )
        link = result.scalar_one_or_none()

        if not link:
            await message.answer("Связь не найдена.")
            return

        await state.update_data(delete_link_id=link_id)
        await state.set_state(LinkManagementStates.confirming_delete)

        # Проверяем, что состояние установлено
        verify_state = await state.get_state()
        verify_data = await state.get_data()
        logger.info(
            "delete_confirm_state_set",
            user_id=user.id,
            link_id=link_id,
            state_set=str(verify_state),
            expected_state=str(LinkManagementStates.confirming_delete),
            state_data=verify_data,
        )

        text = (
            f"⚠️ Подтвердите удаление связи #{link_id}\n\n"
            f"Telegram: {link.telegram_channel.channel_title}\n"
            f"MAX: {link.max_channel.channel_title}\n\n"
            f"Это действие нельзя отменить!"
        )

        keyboard = get_delete_confirm_keyboard(link_id)
        await message.answer(text, reply_markup=keyboard)
        logger.info("delete_confirm_shown", user_id=user.id, link_id=link_id)


async def message_delete_yes(message: Message, state: FSMContext):
    """Обработчик подтвержденного удаления связи."""
    data = await state.get_data()
    link_id = data.get("delete_link_id")

    logger.info("delete_yes_clicked", user_id=message.from_user.id, link_id=link_id, state_data=data)

    if not link_id:
        await message.answer("Ошибка: не найдена связь для удаления.")
        await state.clear()
        return

    user = await get_or_create_user(message.from_user.id, message.from_user.username)

    async with async_session_maker() as session:
        result = await session.execute(
            select(CrosspostingLink).where(CrosspostingLink.id == link_id).where(CrosspostingLink.user_id == user.id)
        )
        link = result.scalar_one_or_none()

        if not link:
            await message.answer("Связь не найдена.")
            await state.clear()
            return

        # КРИТИЧНО: Сохраняем channel_id перед удалением для очистки кэша
        telegram_channel_id_for_cache = None
        if link.telegram_channel:
            await session.refresh(link.telegram_channel)
            telegram_channel_id_for_cache = link.telegram_channel.channel_id

        # Сохраняем ID каналов для проверки после удаления
        telegram_channel_id_for_cleanup = link.telegram_channel_id
        max_channel_id_for_cleanup = link.max_channel_id

        await session.delete(link)
        await session.commit()

        # КРИТИЧНО: Очищаем кэш для канала при удалении связи
        if telegram_channel_id_for_cache:
            cache_key = f"channel_links:{telegram_channel_id_for_cache}"
            await delete_cache(cache_key)
            logger.info("cache_cleared_on_link_delete", channel_id=telegram_channel_id_for_cache, link_id=link_id)

        # Очистка неиспользуемых каналов после удаления связи
        async with async_session_maker() as cleanup_session:
            # Проверяем, есть ли еще связи у Telegram канала
            telegram_links_count = await cleanup_session.execute(
                select(func.count(CrosspostingLink.id)).where(
                    CrosspostingLink.telegram_channel_id == telegram_channel_id_for_cleanup
                )
            )
            if telegram_links_count.scalar() == 0:
                # Нет больше связей - удаляем Telegram канал
                result_tg = await cleanup_session.execute(
                    select(TelegramChannel).where(TelegramChannel.id == telegram_channel_id_for_cleanup)
                )
                tg_channel = result_tg.scalar_one_or_none()
                if tg_channel:
                    await cleanup_session.delete(tg_channel)
                    logger.info("telegram_channel_cleaned_up", channel_id=tg_channel.id, title=tg_channel.channel_title)

            # Проверяем, есть ли еще связи у MAX канала
            max_links_count = await cleanup_session.execute(
                select(func.count(CrosspostingLink.id)).where(CrosspostingLink.max_channel_id == max_channel_id_for_cleanup)
            )
            if max_links_count.scalar() == 0:
                # Нет больше связей - удаляем MAX канал
                result_max = await cleanup_session.execute(
                    select(MaxChannel).where(MaxChannel.id == max_channel_id_for_cleanup)
                )
                max_channel = result_max.scalar_one_or_none()
                if max_channel:
                    await cleanup_session.delete(max_channel)
                    logger.info("max_channel_cleaned_up", channel_id=max_channel.id, title=max_channel.channel_title)

            await cleanup_session.commit()

        await log_audit(user.id, AuditAction.DELETE_LINK.value, "crossposting_link", link_id)

        text = f"🗑️ Связь #{link_id} удалена."
        keyboard = get_back_to_menu_keyboard()
        await message.answer(text, reply_markup=keyboard)
        await state.clear()
        logger.info("link_deleted", link_id=link_id, user_id=user.id)


async def message_delete_cancel(message: Message, state: FSMContext):
    """Обработчик кнопки 'Отмена' при подтверждении удаления."""
    data = await state.get_data()
    link_id = data.get("delete_link_id")

    logger.info("delete_cancelled", user_id=message.from_user.id, link_id=link_id)

    if link_id:
        # Возвращаемся к деталям связи
        await show_link_detail(message, state, link_id)
    else:
        # Если link_id не найден, возвращаемся к списку
        current_page = data.get("channels_list_page", 0)
        await show_channels_list(message, state, page=current_page)


@router.message(LinkManagementStates.viewing_link_detail, F.text == "🔙 Назад к списку")
async def message_back_to_list(message: Message, state: FSMContext):
    """Обработчик кнопки 'Назад к списку'."""
    data = await state.get_data()
    current_page = data.get("channels_list_page", 0)
    await show_channels_list(message, state, page=current_page)
    logger.info("back_to_list", user_id=message.from_user.id)


@router.callback_query(F.data.startswith("migrate_link_"))
async def callback_migrate_link(callback: CallbackQuery, state: FSMContext):
    """Обработчик инлайн-кнопки 'Перенести старые посты'."""
    # Извлекаем ID связи из callback_data
    match = re.search(r"migrate_link_(\d+)", callback.data)
    if not match:
        await callback.answer("Ошибка: не удалось определить ID связи.", show_alert=True)
        return

    link_id = int(match.group(1))
    user = await get_or_create_user(callback.from_user.id, callback.from_user.username)

    # Проверяем, что связь принадлежит пользователю
    async with async_session_maker() as session:
        result = await session.execute(
            select(CrosspostingLink)
            .options(selectinload(CrosspostingLink.telegram_channel), selectinload(CrosspostingLink.max_channel))
            .where(CrosspostingLink.id == link_id)
            .where(CrosspostingLink.user_id == user.id)
        )
        link = result.scalar_one_or_none()

        if not link:
            await callback.answer("Связь не найдена или у вас нет доступа к ней.", show_alert=True)
            return

    # Удаляем сообщение с кнопками
    try:
        await callback.message.delete()
    except Exception as e:
        logger.warning("failed_to_delete_migration_offer_message", error=str(e))

    # Подтверждаем нажатие кнопки
    await callback.answer()

    # Запускаем миграцию в фоне
    await state.set_state(MigrateStates.migrating)
    await state.update_data(migrate_link_id=link_id)

    # Отправляем уведомление о начале
    from app.bot.handlers_migration import start_migration

    start_text = (
        f"⚠️ Начинается перенос старых постов\n\n"
        f"Telegram: {link.telegram_channel.channel_title}\n"
        f"MAX: {link.max_channel.channel_title}\n\n"
        f"📋 Важно:\n"
        f"• Не публикуйте новые посты в Telegram-канале до окончания переноса\n"
        f"• В зависимости от количества постов перенос может занять некоторое время\n\n"
        f"⏳ Начинаю перенос, вы получите уведомление по окончании переноса"
    )
    start_message = await callback.message.answer(start_text, reply_markup=get_stop_migration_keyboard())
    await state.update_data(migration_start_message_id=start_message.message_id)

    # Запускаем миграцию в фоне
    asyncio.create_task(start_migration(link_id, callback.from_user.id, callback.message.chat.id, start_message.message_id))


@router.callback_query(F.data == "migrate_dismiss")
async def callback_migrate_dismiss(callback: CallbackQuery):
    """Обработчик инлайн-кнопки 'Не нужно' - удаляет сообщение."""
    try:
        await callback.message.delete()
        await callback.answer()
    except Exception as e:
        logger.warning("failed_to_delete_migration_offer_message", error=str(e))
        await callback.answer("Сообщение удалено.")
