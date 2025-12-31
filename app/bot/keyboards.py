"""Клавиатуры для Telegram бота."""
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from typing import List, Optional


def get_main_keyboard() -> InlineKeyboardMarkup:
    """
    Главная клавиатура с основными действиями.
    
    Returns:
        InlineKeyboardMarkup с кнопками
    """
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="➕ Добавить связь", callback_data="add_channel"),
            InlineKeyboardButton(text="📋 Список связей", callback_data="list_channels")
        ],
        [
            InlineKeyboardButton(text="📊 Статус", callback_data="status"),
            InlineKeyboardButton(text="❓ Помощь", callback_data="help")
        ]
    ])
    return keyboard


def get_channels_list_keyboard(links: List[dict], page: int = 0, per_page: int = 5) -> InlineKeyboardMarkup:
    """
    Клавиатура со списком связей с пагинацией.
    
    Args:
        links: Список связей с информацией
        page: Номер страницы (0-based)
        per_page: Количество элементов на странице
    
    Returns:
        InlineKeyboardMarkup со списком связей
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
        button_text = f"{status_icon} {telegram_title} → {max_title}"
        
        keyboard_buttons.append([
            InlineKeyboardButton(
                text=button_text,
                callback_data=f"link_detail_{link_id}"
            )
        ])
    
    # Кнопки навигации
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(text="◀️ Назад", callback_data=f"list_channels_page_{page-1}"))
    
    if end_idx < len(links):
        nav_buttons.append(InlineKeyboardButton(text="Вперед ▶️", callback_data=f"list_channels_page_{page+1}"))
    
    if nav_buttons:
        keyboard_buttons.append(nav_buttons)
    
    # Кнопка "Назад в меню"
    keyboard_buttons.append([
        InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu")
    ])
    
    return InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)


def get_link_detail_keyboard(link_id: int, is_enabled: bool) -> InlineKeyboardMarkup:
    """
    Клавиатура для детальной информации о связи.
    
    Args:
        link_id: ID связи
        is_enabled: Включена ли связь
    
    Returns:
        InlineKeyboardMarkup с действиями для связи
    """
    keyboard_buttons = []
    
    if is_enabled:
        keyboard_buttons.append([
            InlineKeyboardButton(text="⏸ Отключить", callback_data=f"disable_{link_id}")
        ])
    else:
        keyboard_buttons.append([
            InlineKeyboardButton(text="▶️ Включить", callback_data=f"enable_{link_id}")
        ])
    
    keyboard_buttons.append([
        InlineKeyboardButton(text="📊 Детальный статус", callback_data=f"status_detail_{link_id}")
    ])
    
    keyboard_buttons.append([
        InlineKeyboardButton(text="🗑 Удалить", callback_data=f"delete_confirm_{link_id}")
    ])
    
    keyboard_buttons.append([
        InlineKeyboardButton(text="🔙 Назад к списку", callback_data="list_channels")
    ])
    
    return InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)


def get_delete_confirm_keyboard(link_id: int) -> InlineKeyboardMarkup:
    """
    Клавиатура подтверждения удаления.
    
    Args:
        link_id: ID связи
    
    Returns:
        InlineKeyboardMarkup с подтверждением
    """
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"delete_yes_{link_id}"),
            InlineKeyboardButton(text="❌ Отмена", callback_data=f"link_detail_{link_id}")
        ]
    ])
    return keyboard


def get_back_to_menu_keyboard() -> InlineKeyboardMarkup:
    """
    Клавиатура с кнопкой "Назад в меню".
    
    Returns:
        InlineKeyboardMarkup
    """
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu")
        ]
    ])
    return keyboard


def get_retry_keyboard(state: str = None) -> InlineKeyboardMarkup:
    """
    Клавиатура для ошибок с кнопками "Повторить" и "Главное меню".
    
    Args:
        state: Состояние для возврата при нажатии "Повторить" (опционально)
    
    Returns:
        InlineKeyboardMarkup
    """
    buttons = []
    if state:
        buttons.append([
            InlineKeyboardButton(text="🔄 Повторить", callback_data=f"retry_{state}")
        ])
    buttons.append([
        InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu")
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

