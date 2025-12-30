"""Утилита для преобразования chat_id в правильный формат."""
from typing import Union


def convert_chat_id(chat_id: Union[str, int, float]) -> int:
    """
    Преобразовать chat_id в правильный формат для MAX API.
    
    Args:
        chat_id: ID канала (может быть строкой или числом)
    
    Returns:
        Преобразованное значение как int
    """
    try:
        if isinstance(chat_id, str):
            # Убираем минус и пробуем преобразовать
            cleaned = chat_id.lstrip('-')
            if cleaned.replace('.', '').isdigit():
                return int(float(chat_id))
            return chat_id
        elif isinstance(chat_id, (int, float)):
            return int(chat_id)
        else:
            return chat_id
    except (ValueError, TypeError):
        return chat_id

