"""Обработчики команд Telegram бота."""
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from typing import Optional

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
        "Для начала работы:\n"
        "1. Добавьте меня в ваш Telegram-канал как администратора\n"
        "2. Добавьте MAX-бота в ваш MAX-канал как администратора\n"
        "3. Используйте команду /add_channel для создания связи\n\n"
        "Доступные команды:\n"
        "/add_channel - Создать новую связь каналов\n"
        "/list_channels - Список всех связей\n"
        "/settings - Настройки\n"
        "/status - Проверка статуса\n"
        "/help - Справка"
    )
    
    await message.answer(text)
    logger.info("start_command", user_id=user.id, telegram_user_id=message.from_user.id)


@router.message(Command("help"))
async def cmd_help(message: Message):
    """Обработчик команды /help."""
    text = (
        "Доступные команды:\n\n"
        "/start - Начало работы\n"
        "/add_channel - Добавить новую связь каналов\n"
        "/list_channels - Список всех связей\n"
        "/settings - Настройки кросспостинга\n"
        "/status - Проверка статуса связей\n"
        "/status <link_id> - Детальный статус связи\n"
        "/enable <link_id> - Включить кросспостинг\n"
        "/disable <link_id> - Отключить кросспостинг\n"
        "/delete <link_id> - Удалить связь\n"
        "/test - Тестовая отправка сообщения"
    )
    await message.answer(text)


@router.message(Command("add_channel"))
async def cmd_add_channel(message: Message, state: FSMContext):
    """Обработчик команды /add_channel."""
    text = (
        "Для создания связи каналов:\n\n"
        "1. Перешлите любое сообщение из вашего Telegram-канала\n"
        "   или отправьте @username канала\n\n"
        "2. Затем отправьте ID или username вашего MAX-канала"
    )
    await message.answer(text)
    await state.set_state(AddChannelStates.waiting_telegram_channel)
    logger.info("add_channel_started", user_id=message.from_user.id)


@router.message(AddChannelStates.waiting_telegram_channel)
async def process_telegram_channel(message: Message, state: FSMContext):
    """Обработка Telegram канала."""
    channel_id = None
    channel_username = None
    channel_title = "Unknown"
    
    if message.forward_from_chat:
        channel_id = message.forward_from_chat.id
        channel_username = message.forward_from_chat.username
        channel_title = message.forward_from_chat.title or "Unknown"
    elif message.text and message.text.startswith("@"):
        channel_username = message.text[1:]
        channel_title = channel_username
        # Получаем ID канала по username через Bot API
        try:
            bot = get_bot()
            chat = await bot.get_chat(f"@{channel_username}")
            channel_id = chat.id
            channel_title = chat.title or channel_username
        except Exception as e:
            logger.warning(f"Не удалось получить информацию о канале @{channel_username}: {e}")
            channel_id = None
    else:
        await message.answer("Пожалуйста, перешлите сообщение из канала или укажите @username канала.")
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
                await message.answer("Не удалось определить ID канала. Попробуйте переслать сообщение из канала.")
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
                await message.answer("❌ Ошибка валидации данных Telegram канала.")
                return
            
            # Проверка прав бота в канале
            try:
                bot = get_bot()
                bot_id = get_bot_id()
                member = await bot.get_chat_member(chat_id=channel_id, user_id=bot_id)
                if member.status not in ['administrator', 'creator']:
                    await message.answer("❌ Бот не является администратором канала. Добавьте бота в канал с правами администратора.")
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
            "Теперь отправьте ID или username вашего MAX-канала."
        )


@router.message(AddChannelStates.waiting_max_channel)
async def process_max_channel(message: Message, state: FSMContext):
    """Обработка MAX канала."""
    max_channel_id = message.text.strip()
    
    if not max_channel_id:
        await message.answer("Пожалуйста, укажите ID или username MAX-канала.")
        return
    
    user = await get_or_create_user(message.from_user.id, message.from_user.username)
    data = await state.get_data()
    telegram_channel_id = data.get("telegram_channel_id")
    
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
                await message.answer("❌ Ошибка валидации данных MAX канала.")
                return
            
            # Пытаемся получить название канала через MAX API
            channel_title = max_channel_id
            try:
                from app.max_api.client import MaxAPIClient
                max_client = MaxAPIClient()
                chat_info = await max_client.get_chat(max_channel_id)
                if chat_info and 'title' in chat_info:
                    channel_title = chat_info['title']
                await max_client.close()
            except APIError as e:
                logger.debug("failed_to_get_max_chat_info", channel_id=max_channel_id, error=str(e))
            except Exception as e:
                logger.debug("failed_to_get_max_chat_info", channel_id=max_channel_id, error=str(e))
            
            max_channel = MaxChannel(
                user_id=user.id,
                channel_id=max_channel_id,
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
                f"Кросспостинг активирован."
            )
            logger.info(
                "crossposting_link_created",
                link_id=crossposting_link.id,
                user_id=user.id
            )
        except Exception as e:
            await message.answer(
                "❌ Ошибка при создании связи. Возможно, такая связь уже существует."
            )
            logger.error("failed_to_create_link", error=str(e))
        
        await state.clear()


@router.message(Command("list_channels"))
async def cmd_list_channels(message: Message):
    """Обработчик команды /list_channels."""
    user = await get_or_create_user(message.from_user.id, message.from_user.username)
    
    async with async_session_maker() as session:
        result = await session.execute(
            select(CrosspostingLink)
            .where(CrosspostingLink.user_id == user.id)
            .order_by(CrosspostingLink.created_at.desc())
        )
        links = result.scalars().all()
        
        if not links:
            await message.answer("У вас пока нет созданных связей. Используйте /add_channel для создания.")
            return
        
        text = "Ваши связи каналов:\n\n"
        for link in links:
            status = "✅ Активна" if link.is_enabled else "❌ Неактивна"
            text += (
                f"ID: {link.id}\n"
                f"Статус: {status}\n"
                f"Telegram: {link.telegram_channel.channel_title}\n"
                f"MAX: {link.max_channel.channel_title}\n\n"
            )
        
        await message.answer(text)


@router.message(Command("status"))
async def cmd_status(message: Message):
    """Обработчик команды /status."""
    user = await get_or_create_user(message.from_user.id, message.from_user.username)
    
    # Проверка, указан ли link_id
    command_parts = message.text.split()
    if len(command_parts) > 1:
        try:
            link_id = int(command_parts[1])
            await cmd_status_detail(message, user, link_id)
            return
        except ValueError:
            pass
    
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
            f"Используйте /status <link_id> для детальной информации о связи."
        )
        
        await message.answer(text)


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
