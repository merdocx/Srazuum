"""Тесты для форматирования текста."""
import pytest
from unittest.mock import Mock
from app.utils.text_formatter import telegram_entities_to_markdown, apply_formatting


@pytest.mark.unit
def test_format_text_simple():
    """Тест простого форматирования текста."""
    text = "Простой текст"
    entities = None
    
    result = telegram_entities_to_markdown(text, entities)
    assert result == "Простой текст"


@pytest.mark.unit
def test_format_text_with_bold():
    """Тест форматирования с жирным текстом."""
    text = "Жирный текст"
    
    # Создаем mock entity
    entity = Mock()
    entity.type.name = "BOLD"
    entity.offset = 0
    entity.length = 6
    entities = [entity]
    
    result = telegram_entities_to_markdown(text, entities)
    # Проверяем, что форматирование применено
    assert "**" in result


@pytest.mark.unit
def test_format_text_with_italic():
    """Тест форматирования с курсивом."""
    text = "Курсивный текст"
    
    entity = Mock()
    entity.type.name = "ITALIC"
    entity.offset = 0
    entity.length = 8
    entities = [entity]
    
    result = telegram_entities_to_markdown(text, entities)
    # Проверяем, что форматирование применено
    assert "*" in result


@pytest.mark.unit
def test_format_text_with_link():
    """Тест форматирования с ссылкой."""
    text = "Ссылка на сайт"
    
    entity = Mock()
    entity.type.name = "TEXT_LINK"
    entity.offset = 0
    entity.length = 6
    entity.url = "https://example.com"
    entities = [entity]
    
    result = telegram_entities_to_markdown(text, entities)
    # Проверяем, что ссылка добавлена
    assert "https://example.com" in result


@pytest.mark.unit
def test_format_text_empty():
    """Тест форматирования пустого текста."""
    result = telegram_entities_to_markdown("", None)
    assert result == ""


@pytest.mark.unit
def test_apply_formatting():
    """Тест применения форматирования."""
    text = "Текст"
    entities = None
    
    formatted_text, parse_mode = apply_formatting(text, entities)
    assert formatted_text == text
    assert parse_mode is None

