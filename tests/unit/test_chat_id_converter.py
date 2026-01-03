"""Тесты для конвертации chat_id."""

import pytest
from app.utils.chat_id_converter import convert_chat_id


@pytest.mark.unit
def test_convert_chat_id_positive_int():
    """Тест конвертации положительного int chat_id."""
    chat_id = 123456789
    result = convert_chat_id(chat_id)
    assert result == 123456789
    assert isinstance(result, int)


@pytest.mark.unit
def test_convert_chat_id_negative_int():
    """Тест конвертации отрицательного int chat_id."""
    chat_id = -1001234567890
    result = convert_chat_id(chat_id)
    assert result == -1001234567890
    assert isinstance(result, int)


@pytest.mark.unit
def test_convert_chat_id_string_positive():
    """Тест конвертации строки с положительным числом."""
    chat_id = "123456789"
    result = convert_chat_id(chat_id)
    assert result == 123456789
    assert isinstance(result, int)


@pytest.mark.unit
def test_convert_chat_id_string_negative():
    """Тест конвертации строки с отрицательным числом."""
    chat_id = "-1001234567890"
    result = convert_chat_id(chat_id)
    assert result == -1001234567890
    assert isinstance(result, int)


@pytest.mark.unit
def test_convert_chat_id_float():
    """Тест конвертации float."""
    chat_id = 123.456
    result = convert_chat_id(chat_id)
    assert result == 123
    assert isinstance(result, int)


@pytest.mark.unit
def test_convert_chat_id_zero():
    """Тест конвертации нулевого chat_id."""
    chat_id = 0
    result = convert_chat_id(chat_id)
    assert result == 0
