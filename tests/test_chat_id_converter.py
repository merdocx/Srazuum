"""Тесты для конвертера chat_id."""
import pytest
from app.utils.chat_id_converter import convert_chat_id


def test_convert_string_int():
    """Тест преобразования строки с числом."""
    assert convert_chat_id("123") == 123
    assert convert_chat_id("-123") == -123
    assert convert_chat_id("123.0") == 123


def test_convert_int():
    """Тест преобразования int."""
    assert convert_chat_id(123) == 123
    assert convert_chat_id(-123) == -123


def test_convert_float():
    """Тест преобразования float."""
    assert convert_chat_id(123.0) == 123
    assert convert_chat_id(-123.0) == -123


def test_convert_string_non_numeric():
    """Тест преобразования нечисловой строки."""
    result = convert_chat_id("abc")
    assert result == "abc"  # Возвращается как есть


