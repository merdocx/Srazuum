"""Обработчики команд Telegram бота."""
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
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
from app.bot.keyboards import (
    get_main_keyboard,
    get_channels_list_keyboard,
    get_link_detail_keyboard,
    get_delete_confirm_keyboard,
    get_back_to_menu_keyboard,
    get_retry_keyboard
)
from config.database import async_session_maker
from config.settings import settings

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


async def get_or_create_user(telegram_user_id: int, username: Optional[str] = None) -> User:
    """Получить или создать пользователя."""
    async with async_session_maker() as session:
        result = await session.execute(
            select(User).where(User.telegram_user_id == telegram_user_id)
        )
        user = result.scalar_one_or_none()
        
        if not user:
            user = User(
                telegram_user_id=telegram_user_id,
                telegram_username=username
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
            logger.info("user_created", user_id=user.id, telegram_user_id=telegram_user_id)
        
        return user


async def log_audit(user_id: int, action: str, entity_type: str, entity_id: int, details: dict = None):
    """Логировать действие в аудит."""
    async with async_session_maker() as session:
        audit_log = AuditLog(
            user_id=user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            details=details
        )
        session.add(audit_log)
        await session.commit()


@router.message(CommandStart())
async def cmd_start(message: Message):
    """Обработчик команды /start."""
    user = await get_or_create_user(message.from_user.id, message.from_user.username)
    
    text = (
        "Привет! Я помогу вам настроить кросспостинг из Telegram в MAX.\n\n"
        "Используйте кнопку «➕ Добавить связь» для создания связи между каналами в Telegram и MAX.\n\n"
        "Выберите действие:"
    )
    
    await message.answer(text, reply_markup=get_main_keyboard())
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


@router.callback_query(F.data == "help")
async def callback_help(callback: CallbackQuery):
    """Обработчик кнопки помощи."""
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
    await callback.message.edit_text(text, reply_markup=get_back_to_menu_keyboard())
    await callback.answer()


@router.callback_query(F.data == "main_menu")
async def callback_main_menu(callback: CallbackQuery, state: FSMContext):
    """Обработчик кнопки главного меню."""
    await state.clear()
    text = (
        "Привет! Я помогу вам настроить кросспостинг из Telegram в MAX.\n\n"
        "Используйте кнопку «➕ Добавить связь» для создания связи между каналами в Telegram и MAX.\n\n"
        "Выберите действие:"
    )
    await callback.message.edit_text(text, reply_markup=get_main_keyboard())
    await callback.answer()
    logger.info("main_menu_opened", user_id=callback.from_user.id)


@router.callback_query(F.data.startswith("retry_"))
async def callback_retry(callback: CallbackQuery, state: FSMContext):
    """Обработчик кнопки повтора."""
    retry_state = callback.data.replace("retry_", "")
    
    if retry_state == "telegram_channel":
        await state.set_state(AddChannelStates.waiting_telegram_channel)
        text = (
            "📋 Создание связи каналов\n\n"
            "⚠️ ВАЖНО! Перед началом убедитесь, что:\n\n"
            "1. ✅ Бот (@srazuum\\_bot) добавлен в ваш Telegram-канал в качестве администратора\n"
            "2. ✅ Вы зашли в [бот в MAX](https://max.ru/id9725096017_bot) и нажали /start\n"
            "3. ✅ [Бот в MAX](https://max.ru/id9725096017_bot) добавлен в ваш MAX-канал в качестве администратора (сначала его необходимо добавить в подписчики канала, затем назначить администратором)\n\n"
            "📝 Для создания связи:\n\n"
            "Шаг 1: Отправьте данные Telegram-канала одним из способов:\n"
            "• Перешлите любое сообщение из канала, или\n"
            "• Отправьте @username канала, или\n"
            "• Отправьте ссылку: https://t.me/username\n\n"
            "Шаг 2: Отправьте данные MAX-канала одним из способов:\n"
            "• Отправьте ID канала (число), или\n"
            "• Отправьте username канала, или\n"
            "• Отправьте cсылку на канал"
        )
        await callback.message.edit_text(text, reply_markup=get_back_to_menu_keyboard(), parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)
    elif retry_state == "max_channel":
        await state.set_state(AddChannelStates.waiting_max_channel)
        text = "Отправьте ID или username вашего MAX-канала."
        await callback.message.edit_text(text, reply_markup=get_back_to_menu_keyboard())
    elif retry_state == "add_channel":
        await state.set_state(AddChannelStates.waiting_telegram_channel)
        text = (
            "📋 Создание связи каналов\n\n"
            "⚠️ ВАЖНО! Перед началом убедитесь, что:\n\n"
            "1. ✅ Бот (@srazuum\\_bot) добавлен в ваш Telegram-канал в качестве администратора\n"
            "2. ✅ Вы зашли в [бот в MAX](https://max.ru/id9725096017_bot) и нажали /start\n"
            "3. ✅ [Бот в MAX](https://max.ru/id9725096017_bot) добавлен в ваш MAX-канал в качестве администратора (сначала его необходимо добавить в подписчики канала, затем назначить администратором)\n\n"
            "📝 Для создания связи:\n\n"
            "Шаг 1: Отправьте данные Telegram-канала одним из способов:\n"
            "• Перешлите любое сообщение из канала, или\n"
            "• Отправьте @username канала, или\n"
            "• Отправьте ссылку: https://t.me/username\n\n"
            "Шаг 2: Отправьте данные MAX-канала одним из способов:\n"
            "• Отправьте ID канала (число), или\n"
            "• Отправьте username канала, или\n"
            "• Отправьте cсылку на канал"
        )
        await callback.message.edit_text(text, reply_markup=get_back_to_menu_keyboard(), parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)
    else:
        await callback.answer("Неизвестное действие", show_alert=True)
        return
    
    await callback.answer()
    logger.info("retry_action", state=retry_state, user_id=callback.from_user.id)


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
        "Шаг 1: Отправьте данные Telegram-канала одним из способов:\n"
        "• Перешлите любое сообщение из канала, или\n"
        "• Отправьте @username канала, или\n"
        "• Отправьте ссылку: https://t.me/username\n\n"
        "Шаг 2: Отправьте данные MAX-канала одним из способов:\n"
        "• Отправьте ID канала (число), или\n"
        "• Отправьте username канала, или\n"
        "• Отправьте cсылку на канал"
    )
    await message.answer(text, reply_markup=get_back_to_menu_keyboard(), parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)
    await state.set_state(AddChannelStates.waiting_telegram_channel)
    logger.info("add_channel_started", user_id=message.from_user.id)


@router.callback_query(F.data == "add_channel")
async def callback_add_channel(callback: CallbackQuery, state: FSMContext):
    """Обработчик кнопки добавления связи."""
    text = (
        "📋 Создание связи каналов\n\n"
        "⚠️ ВАЖНО! Перед началом убедитесь, что:\n\n"
        "1. ✅ Бот (@srazuum\\_bot) добавлен в ваш Telegram-канал в качестве администратора\n"
        "2. ✅ Вы зашли в [бот в MAX](https://max.ru/id9725096017_bot) и нажали /start\n"
        "3. ✅ [Бот в MAX](https://max.ru/id9725096017_bot) добавлен в ваш MAX-канал в качестве администратора (сначала его необходимо добавить в подписчики канала, затем назначить администратором)\n\n"
        "📝 Для создания связи:\n\n"
        "Шаг 1: Отправьте данные Telegram-канала одним из способов:\n"
        "• Перешлите любое сообщение из канала, или\n"
        "• Отправьте @username канала, или\n"
        "• Отправьте ссылку: https://t.me/username\n\n"
        "Шаг 2: Отправьте данные MAX-канала одним из способов:\n"
        "• Отправьте ID канала (число), или\n"
        "• Отправьте username канала, или\n"
        "• Отправьте cсылку на канал"
    )
    await callback.message.edit_text(text, reply_markup=get_back_to_menu_keyboard(), parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)
    await state.set_state(AddChannelStates.waiting_telegram_channel)
    await callback.answer()
    logger.info("add_channel_started", user_id=callback.from_user.id)


@router.message(AddChannelStates.waiting_telegram_channel)
async def process_telegram_channel(message: Message, state: FSMContext):
    """Обработка Telegram канала."""
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
    
    # Вариант 2: Текст с username или ссылкой
    elif message.text:
        text = message.text.strip()
        
        # Извлекаем username из различных форматов
        username_match = None
        
        # Формат: @username
        if text.startswith("@"):
            username_match = text[1:]
        # Формат: username (без @) - минимум 5 символов, максимум 32
        elif re.match(r'^[a-zA-Z0-9_]{5,32}$', text):
            username_match = text
        # Формат: https://t.me/username или t.me/username или telegram.me/username
        elif re.match(r'^(https?://)?(www\.)?(t\.me|telegram\.me)/', text, re.IGNORECASE):
            # Извлекаем username из ссылки
            parts = text.split("/")
            potential_username = parts[-1].split("?")[0]  # Убираем query параметры
            # Пропускаем joinchat ссылки (приватные каналы) и другие служебные пути
            if (potential_username and 
                potential_username != "joinchat" and 
                not potential_username.startswith("+") and
                re.match(r'^[a-zA-Z0-9_]{5,32}$', potential_username)):
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
            except Exception as e:
                logger.warning(f"Не удалось получить информацию о канале @{channel_username}: {e}")
                channel_id = None
        else:
            await message.answer(
                "❌ Не удалось распознать канал.\n\n"
                "Поддерживаемые форматы:\n"
                "• Пересылка сообщения из канала\n"
                "• @username или username\n"
                "• https://t.me/username",
                reply_markup=get_retry_keyboard("telegram_channel")
            )
            return
    else:
        await message.answer(
            "❌ Пожалуйста, используйте один из способов:\n\n"
            "• Перешлите сообщение из канала\n"
            "• Отправьте @username или username\n"
            "• Отправьте ссылку https://t.me/username",
            reply_markup=get_retry_keyboard("telegram_channel")
        )
        return
    
    user = await get_or_create_user(message.from_user.id, message.from_user.username)
    
    async with async_session_maker() as session:
        # Проверка существования канала
        if channel_id:
            result = await session.execute(
                select(TelegramChannel).where(TelegramChannel.channel_id == channel_id)
            )
        else:
            result = await session.execute(
                select(TelegramChannel).where(TelegramChannel.channel_username == channel_username)
            )
        
        telegram_channel = result.scalar_one_or_none()
        
        if not telegram_channel:
            if not channel_id:
                await message.answer(
                    "Не удалось определить ID канала. Попробуйте переслать сообщение из канала.",
                    reply_markup=get_retry_keyboard("telegram_channel")
                )
                return
            
            # Валидация входных данных
            try:
                telegram_input = TelegramChannelInput(
                    channel_id=channel_id,
                    channel_username=channel_username,
                    channel_title=channel_title
                )
            except Exception as e:
                logger.warning("validation_error", error=str(e))
                await message.answer(
                    "❌ Ошибка валидации данных Telegram канала.",
                    reply_markup=get_retry_keyboard("telegram_channel")
                )
                return
            
            # Проверка прав бота в канале
            try:
                bot = get_bot()
                bot_id = get_bot_id()
                member = await bot.get_chat_member(chat_id=channel_id, user_id=bot_id)
                if member.status not in ['administrator', 'creator']:
                    await message.answer(
                        "❌ Бот не является администратором канала. Добавьте бота в канал с правами администратора.",
                        reply_markup=get_retry_keyboard("telegram_channel")
                    )
                    return
            except Exception as e:
                logger.warning(f"Не удалось проверить права бота в канале: {e}")
            
            telegram_channel = TelegramChannel(
                user_id=user.id,
                channel_id=telegram_input.channel_id,
                channel_username=telegram_input.channel_username,
                channel_title=telegram_input.channel_title
            )
            session.add(telegram_channel)
            await session.commit()
            await session.refresh(telegram_channel)
        
        await state.update_data(telegram_channel_id=telegram_channel.id)
        await state.set_state(AddChannelStates.waiting_max_channel)
        
        await message.answer(
            f"Telegram-канал '{channel_title}' добавлен.\n\n"
            "Теперь отправьте ID или username вашего MAX-канала.",
            reply_markup=get_back_to_menu_keyboard()
        )


@router.message(AddChannelStates.waiting_max_channel)
async def process_max_channel(message: Message, state: FSMContext):
    """Обработка MAX канала."""
    import re
    
    user_input = message.text.strip() if message.text else ""
    
    if not user_input:
        await message.answer(
            "❌ Пожалуйста, укажите MAX-канал одним из способов:\n\n"
            "• ID канала (число)\n"
            "• Username канала\n"
            "• Ссылка на канал",
            reply_markup=get_retry_keyboard("max_channel")
        )
        return
    
    user = await get_or_create_user(message.from_user.id, message.from_user.username)
    data = await state.get_data()
    telegram_channel_id = data.get("telegram_channel_id")
    
    # Извлекаем идентификатор канала из различных форматов
    max_channel_id = None
    channel_username = None
    is_from_link = False
    
    # Проверяем, является ли это числовым ID
    try:
        numeric_id = int(user_input)
        max_channel_id = str(numeric_id)  # Сохраняем как строку для единообразия
        logger.info("max_channel_numeric_id", channel_id=max_channel_id)
    except ValueError:
        # Не числовой ID, проверяем другие форматы
        # Формат: ссылка (https://max.ru/... или другие варианты)
        if re.match(r'https?://', user_input, re.IGNORECASE):
            is_from_link = True
            # Извлекаем ID или username из ссылки
            # Поддерживаем форматы:
            # - https://max.ru/username
            # - https://max.ru/channel/username
            # - https://max.ru/channel/1234567890
            # - https://max.ru/id1234567890_bot (боты)
            
            # Парсим URL
            url_parts = user_input.split("/")
            # Убираем query параметры и якоря
            last_part = url_parts[-1].split("?")[0].split("#")[0]
            
            # Если последняя часть - это "channel", берем предыдущую
            if last_part == "channel" and len(url_parts) >= 4:
                last_part = url_parts[-2]
            
            # Пробуем как числовой ID
            try:
                numeric_id = int(last_part)
                max_channel_id = str(numeric_id)
                logger.info("max_channel_id_from_link", channel_id=max_channel_id, link=user_input)
            except ValueError:
                # Не ID, значит username
                # Убираем префикс "id" если есть (для ботов)
                if last_part.startswith("id") and last_part.endswith("_bot"):
                    # Это бот, не канал
                    await message.answer(
                        "❌ Это ссылка на бота, а не на канал.\n\n"
                        "Пожалуйста, укажите ссылку на MAX канал.",
                        reply_markup=get_retry_keyboard("max_channel")
                    )
                    return
                
                channel_username = last_part
                max_channel_id = last_part  # Используем как есть для поиска
                logger.info("max_channel_username_from_link", username=channel_username, link=user_input)
        else:
            # Простой username или ID в виде строки
            max_channel_id = user_input.lstrip('@')
            channel_username = max_channel_id
            logger.info("max_channel_username_or_string_id", value=user_input)
    
    async with async_session_maker() as session:
        # Создание или получение MAX канала
        result = await session.execute(
            select(MaxChannel).where(MaxChannel.channel_id == max_channel_id)
        )
        max_channel = result.scalar_one_or_none()
        
        if not max_channel:
            # Валидация входных данных
            try:
                max_input = MaxChannelInput(channel_id=max_channel_id)
            except Exception as e:
                logger.warning("validation_error", error=str(e))
                await message.answer(
                    "❌ Ошибка валидации данных MAX канала.",
                    reply_markup=get_retry_keyboard("max_channel")
                )
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
                logger.info("available_chats_received", 
                          count=len(available_chats),
                          chats_preview=[dict(chat) for chat in available_chats[:5]])  # Полная структура первых 5
                
                # Логируем все username из доступных чатов
                all_usernames = []
                for chat in available_chats:
                    username = None
                    if 'username' in chat and chat['username']:
                        username = chat['username']
                    elif 'name' in chat and chat['name']:
                        username = chat['name']
                    if username:
                        all_usernames.append(username)
                logger.info("available_chats_usernames", usernames=all_usernames, search_for=max_channel_id)
                
                found_chat = None
                
                # Если это числовой ID, ищем по ID
                if max_channel_id.isdigit():
                    for chat in available_chats:
                        chat_id = None
                        if 'id' in chat:
                            chat_id = str(chat['id'])
                        elif 'chat_id' in chat:
                            chat_id = str(chat['chat_id'])
                        
                        if chat_id == max_channel_id:
                            found_chat = chat
                            logger.info("max_channel_found_by_id", channel_id=max_channel_id, found_id=chat_id)
                            break
                    
                    # Если не нашли в списке, пробуем прямой запрос
                    if not found_chat:
                        try:
                            chat_info = await max_client.get_chat(max_channel_id)
                            if chat_info:
                                found_chat = chat_info
                                logger.info("max_channel_found_by_direct_request", channel_id=max_channel_id)
                        except APIError:
                            # Если прямой запрос не сработал, продолжаем с поиском в списке
                            pass
                else:
                    # Если это username, ищем в списке доступных чатов
                    search_username = max_channel_id.lstrip('@').lower()
                    logger.info("searching_chat_by_username", 
                              search_username=search_username,
                              available_chats_count=len(available_chats))
                    
                    for idx, chat in enumerate(available_chats):
                        # Проверяем все возможные поля для username
                        chat_username = None
                        chat_username_raw = None
                        match_found = False
                        
                        # 1. Проверяем поле 'username' (если есть)
                        if 'username' in chat and chat['username']:
                            chat_username_raw = chat['username']
                            chat_username = str(chat['username']).lstrip('@').lower()
                            match_found = (chat_username == search_username)
                        
                        # 2. Проверяем поле 'name' (если есть)
                        if not match_found and 'name' in chat and chat['name']:
                            chat_username_raw = chat['name']
                            chat_username = str(chat['name']).lstrip('@').lower()
                            match_found = (chat_username == search_username)
                        
                        # 3. Проверяем поле 'slug' (если есть)
                        if not match_found and 'slug' in chat and chat['slug']:
                            chat_username_raw = chat['slug']
                            chat_username = str(chat['slug']).lstrip('@').lower()
                            match_found = (chat_username == search_username)
                        
                        # 4. Извлекаем username из поля 'link' (https://max.ru/username)
                        if not match_found and 'link' in chat and chat['link']:
                            import re
                            link = chat['link']
                            # Извлекаем username из ссылки вида https://max.ru/username
                            link_match = re.search(r'https?://(?:www\.)?max\.ru/([^/?#]+)', link, re.IGNORECASE)
                            if link_match:
                                link_username = link_match.group(1).lower()
                                # Пропускаем служебные пути (id, channel и т.д.)
                                if not link_username.startswith('id') and link_username != 'channel':
                                    chat_username_raw = link_match.group(1)
                                    chat_username = link_username
                                    match_found = (chat_username == search_username)
                        
                        # Логируем сравнение для отладки
                        logger.info("comparing_usernames", 
                                    chat_index=idx,
                                    search=search_username,
                                    chat_username_raw=chat_username_raw,
                                    chat_username_normalized=chat_username,
                                    chat_link=chat.get('link'),
                                    chat_keys=list(chat.keys()),
                                    match=match_found)
                        
                        if match_found:
                            found_chat = chat
                            logger.info("max_channel_found_by_username", 
                                      search_username=search_username,
                                      found_username=chat_username_raw,
                                      chat_id=chat.get('id') or chat.get('chat_id'),
                                      chat_link=chat.get('link'))
                            break
                
                if found_chat:
                    # Если нашли канал, извлекаем все данные
                    # MAX API использует 'chat_id', а не 'id'
                    if 'chat_id' in found_chat:
                        actual_channel_id = str(found_chat['chat_id'])
                    elif 'id' in found_chat:
                        actual_channel_id = str(found_chat['id'])
                    
                    if 'title' in found_chat:
                        channel_title = found_chat['title']
                    elif 'name' in found_chat:
                        channel_title = found_chat['name']
                    
                    # Извлекаем username из разных источников
                    if 'username' in found_chat and found_chat['username']:
                        channel_username = str(found_chat['username']).lstrip('@')
                    elif 'link' in found_chat and found_chat['link']:
                        # Извлекаем username из ссылки https://max.ru/username
                        import re
                        link = found_chat['link']
                        link_match = re.search(r'https?://(?:www\.)?max\.ru/([^/?#]+)', link, re.IGNORECASE)
                        if link_match:
                            extracted_username = link_match.group(1)
                            # Пропускаем служебные пути
                            if not extracted_username.startswith('id') and extracted_username != 'channel':
                                channel_username = extracted_username
                    elif 'slug' in found_chat and found_chat['slug']:
                        channel_username = str(found_chat['slug']).lstrip('@')
                    
                    logger.info("max_channel_found", 
                              original_input=max_channel_id,
                              channel_id=actual_channel_id,
                              title=channel_title,
                              username=channel_username,
                              is_from_link=is_from_link)
                else:
                    # Не нашли в списке доступных чатов
                    logger.warning("chat_not_found_in_available", 
                                 input=max_channel_id,
                                 is_link=is_from_link,
                                 available_chats_count=len(available_chats))
                    await max_client.close()
                    
                    if is_from_link:
                        error_msg = (
                            f"❌ Не удалось найти канал по ссылке '{user_input}'.\n\n"
                            "Возможные причины:\n"
                            "• Бот не добавлен в канал как администратор\n"
                            "• Ссылка указана неверно\n"
                            "• Канал не существует или недоступен\n\n"
                            "Убедитесь, что:\n"
                            "1. Бот добавлен в канал как администратор\n"
                            "2. Ссылка на канал указана правильно\n"
                            "3. Канал существует в MAX"
                        )
                    else:
                        error_msg = (
                            f"❌ Не удалось найти канал '{max_channel_id}'.\n\n"
                            "Проверьте:\n"
                            "• Правильность username или ID\n"
                            "• Что бот добавлен в канал как администратор\n"
                            "• Что канал существует и доступен боту"
                        )
                    
                    await message.answer(error_msg, reply_markup=get_retry_keyboard("max_channel"))
                    return
                
                await max_client.close()
                logger.info("max_channel_info_retrieved", channel_id=actual_channel_id, title=channel_title, username=channel_username)
            except APIError as e:
                logger.warning("failed_to_get_max_chat_info", channel_id=max_channel_id, error=str(e))
                # Если не удалось получить информацию, но это числовой ID, продолжаем
                if not max_channel_id.isdigit():
                    await message.answer(
                        f"❌ Не удалось найти канал '{max_channel_id}'.\n\n"
                        "Проверьте:\n"
                        "• Правильность ID или username\n"
                        "• Что бот добавлен в канал как администратор\n"
                        "• Что канал существует",
                        reply_markup=get_retry_keyboard("max_channel")
                    )
                    return
            except Exception as e:
                logger.warning("failed_to_get_max_chat_info", channel_id=max_channel_id, error=str(e))
                # Если не удалось получить информацию, но это числовой ID, продолжаем
                if not max_channel_id.isdigit():
                    await message.answer(
                        f"❌ Ошибка при получении информации о канале '{max_channel_id}'.\n\n"
                        "Попробуйте использовать числовой ID канала.",
                        reply_markup=get_retry_keyboard("max_channel")
                    )
                    return
            
            # Используем actual_channel_id для сохранения
            max_channel = MaxChannel(
                user_id=user.id,
                channel_id=actual_channel_id,
                channel_username=channel_username,
                channel_title=channel_title
            )
            session.add(max_channel)
            await session.commit()
            await session.refresh(max_channel)
        
        # Создание связи
        try:
            crossposting_link = CrosspostingLink(
                user_id=user.id,
                telegram_channel_id=telegram_channel_id,
                max_channel_id=max_channel.id,
                is_enabled=True
            )
            session.add(crossposting_link)
            await session.commit()
            await session.refresh(crossposting_link)
            
            await log_audit(
                user.id,
                AuditAction.CREATE_LINK.value,
                "crossposting_link",
                crossposting_link.id,
                {
                    "telegram_channel_id": telegram_channel_id,
                    "max_channel_id": max_channel.id
                }
            )
            
            await message.answer(
                f"✅ Связь создана успешно!\n\n"
                f"ID связи: {crossposting_link.id}\n"
                f"Кросспостинг активирован.",
                reply_markup=get_main_keyboard()
            )
            logger.info(
                "crossposting_link_created",
                link_id=crossposting_link.id,
                user_id=user.id
            )
        except Exception as e:
            await message.answer(
                "❌ Ошибка при создании связи. Возможно, такая связь уже существует.",
                reply_markup=get_retry_keyboard("add_channel")
            )
            logger.error("failed_to_create_link", error=str(e))
        
        await state.clear()


@router.message(Command("list_channels"))
async def cmd_list_channels(message: Message):
    """Обработчик команды /list_channels."""
    await show_channels_list(message)


@router.callback_query(F.data == "list_channels")
async def callback_list_channels(callback: CallbackQuery):
    """Обработчик кнопки списка связей."""
    await show_channels_list(callback.message, callback=callback)


async def show_channels_list(message: Message, callback: Optional[CallbackQuery] = None):
    """Показать список связей с клавиатурой."""
    # Получаем user_id из callback, если он есть, иначе из message
    if callback:
        telegram_user_id = callback.from_user.id
        username = callback.from_user.username
    else:
        telegram_user_id = message.from_user.id
        username = message.from_user.username
    
    user = await get_or_create_user(telegram_user_id, username)
    
    async with async_session_maker() as session:
        result = await session.execute(
            select(CrosspostingLink)
            .options(
                selectinload(CrosspostingLink.telegram_channel),
                selectinload(CrosspostingLink.max_channel)
            )
            .where(CrosspostingLink.user_id == user.id)
            .order_by(CrosspostingLink.created_at.desc())
        )
        links = result.scalars().all()
        
        if not links:
            text = "У вас пока нет созданных связей. Используйте кнопку «➕ Добавить связь» для создания."
            if callback:
                await callback.message.edit_text(text, reply_markup=get_back_to_menu_keyboard())
                await callback.answer()
            else:
                await message.answer(text, reply_markup=get_back_to_menu_keyboard())
            return
        
        # Подготовка данных для клавиатуры
        links_data = []
        for link in links:
            links_data.append({
                "id": link.id,
                "telegram_title": link.telegram_channel.channel_title,
                "max_title": link.max_channel.channel_title,
                "is_enabled": link.is_enabled
            })
        
        text = "📋 Ваши связи каналов:\n\nВыберите связь для управления:"
        keyboard = get_channels_list_keyboard(links_data, page=0)
        
        if callback:
            await callback.message.edit_text(text, reply_markup=keyboard)
            await callback.answer()
        else:
            await message.answer(text, reply_markup=keyboard)


@router.callback_query(F.data.startswith("list_channels_page_"))
async def callback_list_channels_page(callback: CallbackQuery):
    """Обработчик пагинации списка связей."""
    try:
        page = int(callback.data.split("_")[-1])
    except ValueError:
        await callback.answer("Ошибка пагинации")
        return
    
    user = await get_or_create_user(callback.from_user.id, callback.from_user.username)
    
    async with async_session_maker() as session:
        result = await session.execute(
            select(CrosspostingLink)
            .options(
                selectinload(CrosspostingLink.telegram_channel),
                selectinload(CrosspostingLink.max_channel)
            )
            .where(CrosspostingLink.user_id == user.id)
            .order_by(CrosspostingLink.created_at.desc())
        )
        links = result.scalars().all()
        
        links_data = []
        for link in links:
            links_data.append({
                "id": link.id,
                "telegram_title": link.telegram_channel.channel_title,
                "max_title": link.max_channel.channel_title,
                "is_enabled": link.is_enabled
            })
        
        text = "📋 Ваши связи каналов:\n\nВыберите связь для управления:"
        keyboard = get_channels_list_keyboard(links_data, page=page)
        
        await callback.message.edit_text(text, reply_markup=keyboard)
        await callback.answer()


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


@router.callback_query(F.data == "status")
async def callback_status(callback: CallbackQuery):
    """Обработчик кнопки статуса."""
    await show_status(callback.message, callback=callback)


async def show_status(message: Message, callback: Optional[CallbackQuery] = None):
    """Показать общий статус кросспостинга."""
    # Получаем user_id из callback, если он есть, иначе из message
    if callback:
        telegram_user_id = callback.from_user.id
        username = callback.from_user.username
    else:
        telegram_user_id = message.from_user.id
        username = message.from_user.username
    
    user = await get_or_create_user(telegram_user_id, username)
    
    async with async_session_maker() as session:
        result = await session.execute(
            select(CrosspostingLink)
            .where(CrosspostingLink.user_id == user.id)
        )
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
        
        if callback:
            await callback.message.edit_text(text, reply_markup=get_back_to_menu_keyboard())
            await callback.answer()
        else:
            await message.answer(text, reply_markup=get_back_to_menu_keyboard())


async def cmd_status_detail(message: Message, user: User, link_id: int):
    """Детальный статус связи."""
    async with async_session_maker() as session:
        result = await session.execute(
            select(CrosspostingLink)
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
            .where(CrosspostingLink.id == link_id)
            .where(CrosspostingLink.user_id == user.id)
        )
        link = result.scalar_one_or_none()
        
        if not link:
            await message.answer("Связь не найдена.")
            return
        
        link.is_enabled = True
        await session.commit()
        
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
            .where(CrosspostingLink.id == link_id)
            .where(CrosspostingLink.user_id == user.id)
        )
        link = result.scalar_one_or_none()
        
        if not link:
            await message.answer("Связь не найдена.")
            return
        
        link.is_enabled = False
        await session.commit()
        
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
            select(CrosspostingLink)
            .where(CrosspostingLink.id == link_id)
            .where(CrosspostingLink.user_id == user.id)
        )
        link = result.scalar_one_or_none()
        
        if not link:
            await message.answer("Связь не найдена.")
            return
        
        await session.delete(link)
        await session.commit()
        
        await log_audit(user.id, AuditAction.DELETE_LINK.value, "crossposting_link", link_id)
        
        await message.answer(f"🗑️ Связь #{link_id} удалена.")
        logger.info("link_deleted", link_id=link_id, user_id=user.id)

# ============================================================================
# Обработчики callback_query для кнопок управления связями
# ============================================================================

@router.callback_query(F.data.startswith("link_detail_"))
async def callback_link_detail(callback: CallbackQuery):
    """Обработчик кнопки детальной информации о связи."""
    try:
        link_id = int(callback.data.split("_")[-1])
    except ValueError:
        await callback.answer("Ошибка: неверный ID связи")
        return
    
    user = await get_or_create_user(callback.from_user.id, callback.from_user.username)
    
    async with async_session_maker() as session:
        result = await session.execute(
            select(CrosspostingLink)
            .options(
                selectinload(CrosspostingLink.telegram_channel),
                selectinload(CrosspostingLink.max_channel)
            )
            .where(CrosspostingLink.id == link_id)
            .where(CrosspostingLink.user_id == user.id)
        )
        link = result.scalar_one_or_none()
        
        if not link:
            await callback.answer("Связь не найдена", show_alert=True)
            return
        
        status_icon = "✅" if link.is_enabled else "❌"
        text = (
            f"{status_icon} Связь #{link.id}\n\n"
            f"Telegram: {link.telegram_channel.channel_title}\n"
            f"MAX: {link.max_channel.channel_title}\n"
            f"Статус: {'Активна' if link.is_enabled else 'Неактивна'}\n"
            f"Создана: {link.created_at.strftime('%Y-%m-%d %H:%M')}"
        )
        
        keyboard = get_link_detail_keyboard(link_id, link.is_enabled)
        await callback.message.edit_text(text, reply_markup=keyboard)
        await callback.answer()


@router.callback_query(F.data.startswith("enable_"))
async def callback_enable(callback: CallbackQuery):
    """Обработчик кнопки включения связи."""
    try:
        link_id = int(callback.data.split("_")[-1])
    except ValueError:
        await callback.answer("Ошибка: неверный ID связи", show_alert=True)
        return
    
    user = await get_or_create_user(callback.from_user.id, callback.from_user.username)
    
    async with async_session_maker() as session:
        result = await session.execute(
            select(CrosspostingLink)
            .options(
                selectinload(CrosspostingLink.telegram_channel),
                selectinload(CrosspostingLink.max_channel)
            )
            .where(CrosspostingLink.id == link_id)
            .where(CrosspostingLink.user_id == user.id)
        )
        link = result.scalar_one_or_none()
        
        if not link:
            await callback.answer("Связь не найдена", show_alert=True)
            return
        
        if link.is_enabled:
            await callback.answer("Связь уже включена")
            return
        
        link.is_enabled = True
        await session.commit()
        
        await log_audit(user.id, AuditAction.ENABLE_LINK.value, "crossposting_link", link_id)
        
        # Обновляем сообщение
        status_icon = "✅"
        text = (
            f"{status_icon} Связь #{link.id}\n\n"
            f"Telegram: {link.telegram_channel.channel_title}\n"
            f"MAX: {link.max_channel.channel_title}\n"
            f"Статус: Активна\n"
            f"Создана: {link.created_at.strftime('%Y-%m-%d %H:%M')}"
        )
        
        keyboard = get_link_detail_keyboard(link_id, True)
        await callback.message.edit_text(text, reply_markup=keyboard)
        await callback.answer("✅ Кросспостинг включен")
        logger.info("link_enabled", link_id=link_id, user_id=user.id)


@router.callback_query(F.data.startswith("disable_"))
async def callback_disable(callback: CallbackQuery):
    """Обработчик кнопки отключения связи."""
    try:
        link_id = int(callback.data.split("_")[-1])
    except ValueError:
        await callback.answer("Ошибка: неверный ID связи", show_alert=True)
        return
    
    user = await get_or_create_user(callback.from_user.id, callback.from_user.username)
    
    async with async_session_maker() as session:
        result = await session.execute(
            select(CrosspostingLink)
            .options(
                selectinload(CrosspostingLink.telegram_channel),
                selectinload(CrosspostingLink.max_channel)
            )
            .where(CrosspostingLink.id == link_id)
            .where(CrosspostingLink.user_id == user.id)
        )
        link = result.scalar_one_or_none()
        
        if not link:
            await callback.answer("Связь не найдена", show_alert=True)
            return
        
        if not link.is_enabled:
            await callback.answer("Связь уже отключена")
            return
        
        link.is_enabled = False
        await session.commit()
        
        await log_audit(user.id, AuditAction.DISABLE_LINK.value, "crossposting_link", link_id)
        
        # Обновляем сообщение
        status_icon = "❌"
        text = (
            f"{status_icon} Связь #{link.id}\n\n"
            f"Telegram: {link.telegram_channel.channel_title}\n"
            f"MAX: {link.max_channel.channel_title}\n"
            f"Статус: Неактивна\n"
            f"Создана: {link.created_at.strftime('%Y-%m-%d %H:%M')}"
        )
        
        keyboard = get_link_detail_keyboard(link_id, False)
        await callback.message.edit_text(text, reply_markup=keyboard)
        await callback.answer("❌ Кросспостинг отключен")
        logger.info("link_disabled", link_id=link_id, user_id=user.id)


@router.callback_query(F.data.startswith("delete_confirm_"))
async def callback_delete_confirm(callback: CallbackQuery):
    """Обработчик кнопки подтверждения удаления."""
    try:
        link_id = int(callback.data.split("_")[-1])
    except ValueError:
        await callback.answer("Ошибка: неверный ID связи", show_alert=True)
        return
    
    user = await get_or_create_user(callback.from_user.id, callback.from_user.username)
    
    async with async_session_maker() as session:
        result = await session.execute(
            select(CrosspostingLink)
            .options(
                selectinload(CrosspostingLink.telegram_channel),
                selectinload(CrosspostingLink.max_channel)
            )
            .where(CrosspostingLink.id == link_id)
            .where(CrosspostingLink.user_id == user.id)
        )
        link = result.scalar_one_or_none()
        
        if not link:
            await callback.answer("Связь не найдена", show_alert=True)
            return
        
        text = (
            f"⚠️ Подтвердите удаление связи #{link_id}\n\n"
            f"Telegram: {link.telegram_channel.channel_title}\n"
            f"MAX: {link.max_channel.channel_title}\n\n"
            f"Это действие нельзя отменить!"
        )
        
        keyboard = get_delete_confirm_keyboard(link_id)
        await callback.message.edit_text(text, reply_markup=keyboard)
        await callback.answer()


@router.callback_query(F.data.startswith("delete_yes_"))
async def callback_delete_yes(callback: CallbackQuery):
    """Обработчик подтвержденного удаления связи."""
    try:
        link_id = int(callback.data.split("_")[-1])
    except ValueError:
        await callback.answer("Ошибка: неверный ID связи", show_alert=True)
        return
    
    user = await get_or_create_user(callback.from_user.id, callback.from_user.username)
    
    async with async_session_maker() as session:
        result = await session.execute(
            select(CrosspostingLink)
            .where(CrosspostingLink.id == link_id)
            .where(CrosspostingLink.user_id == user.id)
        )
        link = result.scalar_one_or_none()
        
        if not link:
            await callback.answer("Связь не найдена", show_alert=True)
            return
        
        await session.delete(link)
        await session.commit()
        
        await log_audit(user.id, AuditAction.DELETE_LINK.value, "crossposting_link", link_id)
        
        text = f"🗑️ Связь #{link_id} удалена."
        keyboard = get_back_to_menu_keyboard()
        await callback.message.edit_text(text, reply_markup=keyboard)
        await callback.answer("Связь удалена")
        logger.info("link_deleted", link_id=link_id, user_id=user.id)


@router.callback_query(F.data.startswith("status_detail_"))
async def callback_status_detail(callback: CallbackQuery):
    """Обработчик кнопки детального статуса связи."""
    try:
        link_id = int(callback.data.split("_")[-1])
    except ValueError:
        await callback.answer("Ошибка: неверный ID связи", show_alert=True)
        return
    
    user = await get_or_create_user(callback.from_user.id, callback.from_user.username)
    
    # Используем существующую функцию cmd_status_detail
    # Но нужно адаптировать её для callback
    async with async_session_maker() as session:
        result = await session.execute(
            select(CrosspostingLink)
            .options(
                selectinload(CrosspostingLink.telegram_channel),
                selectinload(CrosspostingLink.max_channel)
            )
            .where(CrosspostingLink.id == link_id)
            .where(CrosspostingLink.user_id == user.id)
        )
        link = result.scalar_one_or_none()
        
        if not link:
            await callback.answer("Связь не найдена", show_alert=True)
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
            f"{status_icon} Детальный статус связи #{link.id}\n\n"
            f"Telegram: {link.telegram_channel.channel_title}\n"
            f"MAX: {link.max_channel.channel_title}\n"
            f"Статус: {'Активна' if link.is_enabled else 'Неактивна'}\n\n"
            f"📊 Статистика:\n"
            f"Успешных: {success_count.scalar() or 0}\n"
            f"Неудачных: {failed_count.scalar() or 0}\n\n"
        )
        
        if last_success_msg:
            text += f"Последняя отправка: {last_success_msg.sent_at.strftime('%Y-%m-%d %H:%M:%S')}\n"
        
        if last_error_msg:
            text += f"\nПоследняя ошибка:\n{last_error_msg.error_message[:200]}\n"
        
        keyboard = get_link_detail_keyboard(link_id, link.is_enabled)
        await callback.message.edit_text(text, reply_markup=keyboard)
        await callback.answer()


