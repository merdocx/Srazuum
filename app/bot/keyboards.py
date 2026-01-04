"""Клавиатуры для Telegram бота."""

from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from typing import List, Optional


def get_main_keyboard() -> ReplyKeyboardMarkup:
    """
    Главная клавиатура с основными действиями.

    Returns:
        ReplyKeyboardMarkup с кнопками
    """
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Добавить связь"), KeyboardButton(text="📋 Список связей")],
            [KeyboardButton(text="💬 Связаться с поддержкой")],
        ],
        resize_keyboard=True,
    )
    return keyboard


def get_channels_list_keyboard(links: List[dict], page: int = 0, per_page: int = 5) -> ReplyKeyboardMarkup:
    """
    Клавиатура со списком связей с пагинацией.

    Args:
        links: Список связей с информацией
        page: Номер страницы (0-based)
        per_page: Количество элементов на странице

    Returns:
        ReplyKeyboardMarkup со списком связей
    """
    keyboard_buttons = []

    # Показываем связи для текущей страницы
    start_idx = page * per_page
    end_idx = start_idx + per_page
    page_links = links[start_idx:end_idx]

    for link in page_links:
        link_id = link.get("id")
        telegram_title = link.get("telegram_title", "Unknown")
        max_title = link.get("max_title", "Unknown")
        is_enabled = link.get("is_enabled", False)

        status_icon = "✅" if is_enabled else "❌"
        # Формат: "✅ Telegram канал - MAX канал" или "❌ Telegram канал - MAX канал"
        # Ограничиваем длину названий, чтобы кнопка не была слишком длинной
        telegram_short = telegram_title[:20] + "..." if len(telegram_title) > 20 else telegram_title
        max_short = max_title[:20] + "..." if len(max_title) > 20 else max_title
        button_text = f"{status_icon} {telegram_short} - {max_short}"

        keyboard_buttons.append([KeyboardButton(text=button_text)])

    # Кнопки навигации
    nav_buttons = []
    if page > 0:
        nav_buttons.append(KeyboardButton(text="◀️ Назад"))

    if end_idx < len(links):
        nav_buttons.append(KeyboardButton(text="Вперед ▶️"))

    if nav_buttons:
        keyboard_buttons.append(nav_buttons)

    # Кнопка "Назад в меню"
    keyboard_buttons.append([KeyboardButton(text="🏠 Главное меню")])

    return ReplyKeyboardMarkup(keyboard=keyboard_buttons, resize_keyboard=True)


def get_link_detail_keyboard(link_id: int, is_enabled: bool) -> ReplyKeyboardMarkup:
    """
    Клавиатура для детальной информации о связи.

    Args:
        link_id: ID связи
        is_enabled: Включена ли связь

    Returns:
        ReplyKeyboardMarkup с действиями для связи
    """
    keyboard_buttons = []

    if is_enabled:
        keyboard_buttons.append([KeyboardButton(text="⏸ Отключить")])
    else:
        keyboard_buttons.append([KeyboardButton(text="▶️ Включить")])

    keyboard_buttons.append([KeyboardButton(text="🗑 Удалить")])

    keyboard_buttons.append([KeyboardButton(text="🔙 Назад к списку")])

    return ReplyKeyboardMarkup(keyboard=keyboard_buttons, resize_keyboard=True)


def get_delete_confirm_keyboard(link_id: int) -> ReplyKeyboardMarkup:
    """
    Клавиатура подтверждения удаления.

    Args:
        link_id: ID связи

    Returns:
        ReplyKeyboardMarkup с подтверждением
    """
    keyboard = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="✅ Да, удалить"), KeyboardButton(text="❌ Отмена")]], resize_keyboard=True
    )
    return keyboard


def get_back_to_menu_keyboard() -> ReplyKeyboardMarkup:
    """
    Клавиатура с кнопкой "Назад в меню".

    Returns:
        ReplyKeyboardMarkup
    """
    keyboard = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="🏠 Главное меню")]], resize_keyboard=True)
    return keyboard


def get_cancel_keyboard() -> ReplyKeyboardMarkup:
    """
    Клавиатура с кнопкой "Отмена" для отмены процесса создания связи.

    Returns:
        ReplyKeyboardMarkup
    """
    keyboard = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="❌ Отмена")]], resize_keyboard=True)
    return keyboard


def get_retry_keyboard(state: str = None) -> ReplyKeyboardMarkup:
    """
    Клавиатура для ошибок с кнопками "Повторить" и "Главное меню".

    Args:
        state: Состояние для возврата при нажатии "Повторить" (опционально)

    Returns:
        ReplyKeyboardMarkup
    """
    buttons = []
    if state:
        buttons.append([KeyboardButton(text="🔄 Повторить")])
    buttons.append([KeyboardButton(text="🏠 Главное меню")])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)


def get_migrate_links_keyboard(links: List[dict]) -> ReplyKeyboardMarkup:
    """
    Клавиатура для выбора связи для миграции.

    Args:
        links: Список связей с информацией

    Returns:
        ReplyKeyboardMarkup со списком связей
    """
    keyboard_buttons = []

    for link in links:
        link_id = link.get("id")
        telegram_title = link.get("telegram_title", "Unknown")
        max_title = link.get("max_title", "Unknown")
        is_enabled = link.get("is_enabled", False)

        status_icon = "✅" if is_enabled else "❌"
        button_text = f"{status_icon} Связь #{link_id}"

        keyboard_buttons.append([KeyboardButton(text=button_text)])

    # Кнопка "Назад в меню"
    keyboard_buttons.append([KeyboardButton(text="🏠 Главное меню")])

    return ReplyKeyboardMarkup(keyboard=keyboard_buttons, resize_keyboard=True)


def get_migration_offer_keyboard(link_id: int) -> InlineKeyboardMarkup:
    """
    Инлайн-клавиатура для предложения миграции после создания связи.

    Args:
        link_id: ID только что созданной связи

    Returns:
        InlineKeyboardMarkup с кнопками миграции
    """
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📥 Перенести старые посты", callback_data=f"migrate_link_{link_id}")],
            [InlineKeyboardButton(text="❌ Не нужно", callback_data=f"migrate_dismiss")],
        ]
    )
    return keyboard


def get_stop_migration_keyboard() -> ReplyKeyboardMarkup:
    """
    Клавиатура с кнопкой "Остановить миграцию" во время миграции.

    Returns:
        ReplyKeyboardMarkup с кнопкой остановки миграции
    """
    keyboard = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="⏹ Остановить миграцию")]], resize_keyboard=True)
    return keyboard
