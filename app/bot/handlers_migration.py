"""Обработчики для миграции старых постов."""

from aiogram import Router, F, Bot
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from pyrogram import Client
from typing import Optional
import os
import asyncio

from app.models.crossposting_link import CrosspostingLink
from app.models.user import User
from app.core.post_migrator import PostMigrator
from app.core.message_processor import MessageProcessor
from app.core.migration_queue import migration_queue
from app.bot.handlers import get_or_create_user, router
from app.bot.handlers import MigrateStates
from app.bot.keyboards import (
    get_main_keyboard,
    get_migrate_links_keyboard,
    get_back_to_menu_keyboard,
    get_stop_migration_keyboard,
)
from config.database import async_session_maker
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def show_migrate_links_list(message: Message, state: FSMContext):
    """Показать список активных связей для миграции."""
    try:
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
                text = "У вас нет созданных связей. Используйте кнопку «➕ Добавить связь» для создания."
                await message.answer(text, reply_markup=get_back_to_menu_keyboard())
                return

            # Подготовка данных для клавиатуры
            links_data = []
            for link in links:
                links_data.append(
                    {
                        "id": link.id,
                        "telegram_title": link.telegram_channel.channel_title,
                        "max_title": link.max_channel.channel_title,
                        "is_enabled": link.is_enabled,
                    }
                )

            text = "📥 Перенос старых постов\n\nВыберите связь для переноса:"
            keyboard = get_migrate_links_keyboard(links_data)

            await state.update_data(migrate_links_data=links_data)
            await state.set_state(MigrateStates.selecting_link)

            await message.answer(text, reply_markup=keyboard)

    except Exception as e:
        logger.error("error_showing_migrate_links", error=str(e), exc_info=True)
        await message.answer(
            "❌ Ошибка при получении списка связей. Попробуйте позже.", reply_markup=get_back_to_menu_keyboard()
        )


@router.message(F.text == "📥 Перенести старые посты")
async def message_migrate_posts(message: Message, state: FSMContext):
    """Обработчик кнопки миграции постов."""
    await show_migrate_links_list(message, state)


@router.message(MigrateStates.selecting_link, F.text.regexp(r"^[✅❌]\s*Связь\s*#\d+$"))
async def message_migrate_link(message: Message, state: FSMContext):
    """Обработчик выбора связи для миграции."""
    import re

    # Извлекаем ID из текста "✅ Связь #1" или "❌ Связь #2"
    match = re.search(r"#(\d+)", message.text)
    if not match:
        await message.answer("Ошибка: не удалось определить ID связи.")
        return

    link_id = int(match.group(1))
    user = await get_or_create_user(message.from_user.id, message.from_user.username)

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
            await message.answer("Связь не найдена или у вас нет доступа к ней.")
            return

        # Запускаем миграцию в фоне
        await state.set_state(MigrateStates.migrating)

        # Отправляем уведомление о начале и сохраняем message_id
        start_text = (
            f"⚠️ Начинается перенос старых постов\n\n"
            f"Telegram: {link.telegram_channel.channel_title}\n"
            f"MAX: {link.max_channel.channel_title}\n\n"
            f"📋 Важно:\n"
            f"• Не публикуйте новые посты в Telegram-канале до окончания переноса\n"
            f"• В зависимости от количества постов перенос может занять некоторое время\n\n"
            f"⏳ Начинаю перенос, вы получите уведомление по окончании переноса"
        )
        start_message = await message.answer(start_text, reply_markup=get_stop_migration_keyboard())

        await state.update_data(migrate_link_id=link_id, migration_start_message_id=start_message.message_id)

        # Запускаем миграцию в фоне
        asyncio.create_task(start_migration(link_id, message.from_user.id, message.chat.id, start_message.message_id))


@router.message(F.text == "⏹ Остановить миграцию")
async def message_stop_migration(message: Message, state: FSMContext):
    """Обработчик кнопки 'Остановить миграцию'."""
    user = await get_or_create_user(message.from_user.id, message.from_user.username)

    # Получаем link_id из состояния
    data = await state.get_data()
    link_id = data.get("migrate_link_id")

    if not link_id:
        await message.answer("❌ Не найдена активная миграция.", reply_markup=get_main_keyboard())
        await state.clear()
        return

    async with async_session_maker() as session:
        result = await session.execute(
            select(CrosspostingLink)
            .options(selectinload(CrosspostingLink.telegram_channel), selectinload(CrosspostingLink.max_channel))
            .where(CrosspostingLink.id == link_id)
            .where(CrosspostingLink.user_id == user.id)
        )
        link = result.scalar_one_or_none()

        if not link:
            await message.answer("❌ Связь не найдена или у вас нет доступа к ней.", reply_markup=get_main_keyboard())
            await state.clear()
            return

    # Останавливаем миграцию
    await migration_queue.stop_migration(link_id)

    # Включаем кросспостинг (по аналогии с окончанием миграции)
    # Во время миграции связь отключается, поэтому включаем её обратно
    telegram_channel_db_id = link.telegram_channel.id

    if not link.is_enabled:
        # Включаем кросспостинг, если он был отключен во время миграции
        link.is_enabled = True
        await session.commit()
        logger.info("link_enabled_after_stopping_migration", link_id=link_id, is_enabled=link.is_enabled)

        # Пересоздаем кэш
        if telegram_channel_db_id:
            from app.utils.cache import set_cache, delete_cache, get_cache

            cache_key = f"channel_links:{telegram_channel_db_id}"

            async with async_session_maker() as new_session:
                result = await new_session.execute(
                    select(CrosspostingLink)
                    .where(CrosspostingLink.telegram_channel_id == telegram_channel_db_id)
                    .where(CrosspostingLink.is_enabled == True)
                )
                active_links = result.scalars().all()

                if active_links:
                    link_ids = [link.id for link in active_links]
                    await delete_cache(cache_key)
                    await set_cache(cache_key, link_ids)
                    logger.info(
                        "cache_recreated_after_stopping_migration", cache_key=cache_key, link_ids=link_ids, link_id=link_id
                    )

    # ВАЖНО: Перезапускаем MTProto receiver после остановки миграции
    # чтобы убедиться, что он продолжает получать сообщения
    try:
        import subprocess

        result = subprocess.run(
            ["systemctl", "restart", "crossposting-mtproto.service"], capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            logger.info("mtproto_receiver_restarted_after_stopping_migration", link_id=link_id)
        else:
            logger.warning("mtproto_receiver_restart_failed_after_stopping_migration", link_id=link_id, error=result.stderr)
    except Exception as e:
        logger.error(
            "failed_to_restart_mtproto_receiver_after_stopping_migration", link_id=link_id, error=str(e), exc_info=True
        )

    await message.answer("✅ Миграция остановлена. Кросспостинг включен.", reply_markup=get_main_keyboard())
    await state.clear()
    logger.info("migration_stopped_by_user", link_id=link_id, user_id=user.id)


async def start_migration(link_id: int, user_id: int, chat_id: int, start_message_id: Optional[int] = None):
    """
    Запустить миграцию постов в фоне.

    Args:
        link_id: ID связи для миграции
        user_id: ID пользователя Telegram
        chat_id: ID чата для отправки уведомлений
        start_message_id: ID сообщения о начале миграции (для редактирования клавиатуры)
    """
    pyrogram_client = None
    bot = None

    try:
        # Получаем бота для отправки уведомлений
        from app.bot.handlers import get_bot

        try:
            bot = get_bot()
        except RuntimeError:
            # Если бот не инициализирован, создаем новый экземпляр
            from aiogram import Bot
            from config.settings import settings

            bot = Bot(token=settings.telegram_bot_token)

        # Создаем Pyrogram клиент для миграции
        # Пытаемся загрузить session_string из файла
        session_string = None
        session_file_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "session_string.txt")

        if os.path.exists(session_file_path):
            with open(session_file_path, "r") as f:
                session_string = f.read().strip()
            logger.info("session_string_loaded_from_file")

        # Создаем клиент
        # ВАЖНО: Создаем уникальное имя сессии для каждой миграции, чтобы избежать конфликтов
        # при параллельных миграциях разных пользователей
        unique_session_name = f"migration_{link_id}_{user_id}"

        if session_string:
            pyrogram_client = Client(
                unique_session_name,
                session_string=session_string,
                api_id=os.getenv("TELEGRAM_API_ID"),
                api_hash=os.getenv("TELEGRAM_API_HASH"),
            )
        else:
            # Используем уникальное имя сессии для миграции
            pyrogram_client = Client(
                unique_session_name, api_id=os.getenv("TELEGRAM_API_ID"), api_hash=os.getenv("TELEGRAM_API_HASH")
            )

        # Подключаемся к Telegram
        await pyrogram_client.connect()

        # Проверяем авторизацию
        me = await pyrogram_client.get_me()
        logger.info("pyrogram_client_connected", user_id=me.id, username=me.username)

        # Создаем процессоры
        message_processor = MessageProcessor()
        migrator = PostMigrator(pyrogram_client, message_processor)

        # Начинаем миграцию
        await migration_queue.start_migration(link_id)

        # Callback для обновления прогресса
        async def progress_callback(processed: int, success: int, skipped: int, failed: int):
            """Отправлять промежуточные обновления прогресса."""
            try:
                progress_text = (
                    f"⏳ Прогресс миграции для связи #{link_id}:\n\n"
                    f"Обработано: {processed}\n"
                    f"Успешно: {success}\n"
                    f"Пропущено: {skipped}\n"
                    f"Ошибок: {failed}"
                )
                await bot.send_message(chat_id, progress_text)
            except Exception as e:
                logger.error("failed_to_send_progress_update", error=str(e))

        # Запускаем миграцию
        result = await migrator.migrate_link_posts(link_id, progress_callback)

        # Логируем результат для отладки
        logger.info("migration_result_received", link_id=link_id, result=result)

        # Формируем финальное сообщение
        duration = result.get("duration", 0)
        duration_minutes = int(duration / 60) if duration else 0
        duration_seconds = int(duration % 60) if duration else 0
        duration_text = f"{duration_minutes} мин {duration_seconds} сек" if duration_minutes > 0 else f"{duration_seconds} сек"

        skipped = result.get("skipped", 0)
        skipped_empty = result.get("skipped_empty", 0)
        skipped_duplicate = result.get("skipped_duplicate", 0)
        skipped_unsupported = result.get("skipped_unsupported", 0)

        skipped_lines = []
        if skipped_empty > 0:
            skipped_lines.append(f"• Пропущено (пустые): {skipped_empty}")
        if skipped_duplicate > 0:
            skipped_lines.append(f"• Пропущено (уже были): {skipped_duplicate}")
        if skipped_unsupported > 0:
            skipped_lines.append(f"• Пропущено (неподдерживаемые): {skipped_unsupported}")

        skipped_text = "\n".join(skipped_lines) if skipped_lines else ""

        final_text = (
            f"✅ Перенос старых постов завершен\n\n"
            f"📊 Статистика:\n"
            f"• Всего постов: {result.get('total', 0)}\n"
            f"• Успешно перенесено: {result.get('success', 0)}\n"
            + (f"{skipped_text}\n" if skipped_text else "")
            + f"• Не удалось перенести: {result.get('failed', 0)}\n\n"
            f"⏱ Время переноса: {duration_text}"
        )

        try:
            # Сначала редактируем клавиатуру исходного сообщения, если есть его ID
            if start_message_id:
                try:
                    await bot.edit_message_reply_markup(chat_id=chat_id, message_id=start_message_id, reply_markup=None)
                except Exception as edit_error:
                    # Если не удалось отредактировать (например, сообщение было удалено), игнорируем ошибку
                    logger.debug("failed_to_edit_start_message_keyboard", error=str(edit_error))

            await bot.send_message(chat_id, final_text, reply_markup=get_main_keyboard())
            logger.info("migration_completed_notification_sent", link_id=link_id, result=result)
        except Exception as send_error:
            logger.error("failed_to_send_completion_notification", link_id=link_id, error=str(send_error), exc_info=True)
            # Пытаемся отправить простое сообщение без клавиатуры
            try:
                await bot.send_message(chat_id, final_text)
            except Exception as e2:
                logger.error("failed_to_send_simple_completion_notification", error=str(e2))

    except Exception as e:
        logger.error("migration_error_in_handler", link_id=link_id, error=str(e), exc_info=True)

        if bot:
            error_text = (
                f"❌ Ошибка при переносе постов для связи #{link_id}:\n\n"
                f"{str(e)}\n\n"
                f"Попробуйте позже или обратитесь в поддержку."
            )
            try:
                # Редактируем клавиатуру исходного сообщения, если есть его ID
                if start_message_id:
                    try:
                        await bot.edit_message_reply_markup(chat_id=chat_id, message_id=start_message_id, reply_markup=None)
                    except Exception:
                        pass  # Игнорируем ошибку редактирования

                await bot.send_message(chat_id, error_text, reply_markup=get_main_keyboard())
            except Exception as send_error:
                logger.error("failed_to_send_error_message", error=str(send_error))
    finally:
        # Останавливаем миграцию
        await migration_queue.stop_migration(link_id)

        # Отключаем Pyrogram клиент
        if pyrogram_client:
            try:
                await pyrogram_client.disconnect()
                logger.info("pyrogram_client_disconnected")
            except Exception as e:
                logger.error("failed_to_disconnect_pyrogram", error=str(e))
