"""Утилиты для форматирования текста."""
from typing import List, Optional
from pyrogram.types import MessageEntity
from app.utils.logger import get_logger

logger = get_logger(__name__)


def telegram_entities_to_markdown(text: str, entities: Optional[List[MessageEntity]]) -> str:
    """
    Конвертировать Telegram entities в Markdown формат для MAX API.
    
    Args:
        text: Исходный текст
        entities: Список entities из Telegram сообщения
    
    Returns:
        Текст с Markdown разметкой
    """
    if not entities or not text:
        return text
    
    # Сортируем entities по offset (позиции в тексте) в обратном порядке
    # чтобы при замене не сбивались индексы
    sorted_entities = sorted(entities, key=lambda e: (e.offset, -e.length), reverse=True)
    
    result = text
    
    for entity in sorted_entities:
        offset = entity.offset
        length = entity.length
        
        # Проверяем границы
        if offset < 0 or offset + length > len(text):
            continue
        
        entity_text = text[offset:offset + length]
        
        # Обрабатываем разные типы форматирования
        if entity.type.name == "BOLD":
            # Жирный: **текст**
            replacement = f"**{entity_text}**"
        elif entity.type.name == "ITALIC":
            # Курсив: *текст*
            replacement = f"*{entity_text}*"
        elif entity.type.name == "CODE":
            # Моноширинный: `код`
            replacement = f"`{entity_text}`"
        elif entity.type.name == "PRE":
            # Блок кода: ```код```
            replacement = f"```{entity_text}```"
        elif entity.type.name == "STRIKETHROUGH":
            # Зачеркнутый: ~~текст~~
            replacement = f"~~{entity_text}~~"
        elif entity.type.name == "UNDERLINE":
            # Подчеркнутый: ++текст++ (MAX формат)
            replacement = f"++{entity_text}++"
        elif entity.type.name == "TEXT_LINK":
            # Ссылка: [текст](url)
            url = entity.url if hasattr(entity, 'url') else ""
            if url:
                replacement = f"[{entity_text}]({url})"
            else:
                replacement = entity_text
        elif entity.type.name == "TEXT_MENTION":
            # Упоминание пользователя: @username или [имя](tg://user?id=id)
            user = entity.user if hasattr(entity, 'user') else None
            if user:
                username = user.username or (user.first_name or "")
                if username.startswith("@"):
                    replacement = username
                else:
                    replacement = f"@{username}" if username else entity_text
            else:
                replacement = entity_text
        else:
            # Неизвестный тип - оставляем как есть
            replacement = entity_text
            logger.debug(f"unknown_entity_type", type=entity.type.name)
        
        # Заменяем текст в строке
        result = result[:offset] + replacement + result[offset + length:]
    
    return result


def apply_formatting(text: str, entities: Optional[List[MessageEntity]], parse_mode: Optional[str] = None) -> tuple[str, Optional[str]]:
    """
    Применить форматирование к тексту.
    
    Args:
        text: Исходный текст
        entities: Список entities из Telegram сообщения
        parse_mode: Режим парсинга (markdown, html, или None)
    
    Returns:
        Кортеж (отформатированный текст, parse_mode для MAX API)
    """
    if not entities:
        return text, None
    
    # Конвертируем в Markdown
    formatted_text = telegram_entities_to_markdown(text, entities)
    
    # MAX API поддерживает markdown
    return formatted_text, "markdown"



