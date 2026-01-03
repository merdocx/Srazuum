"""Тесты для валидаторов."""
import pytest
from app.utils.validators import TelegramChannelInput, MaxChannelInput
from pydantic import ValidationError


@pytest.mark.unit
def test_telegram_channel_input_valid():
    """Тест валидного TelegramChannelInput."""
    input_data = TelegramChannelInput(
        channel_id=-1001234567890,
        channel_username="test_channel",
        channel_title="Test Channel"
    )
    
    assert input_data.channel_id == -1001234567890
    assert input_data.channel_username == "test_channel"
    assert input_data.channel_title == "Test Channel"


@pytest.mark.unit
def test_telegram_channel_input_minimal():
    """Тест минимального TelegramChannelInput (только channel_title)."""
    input_data = TelegramChannelInput(channel_title="Test Channel")
    
    assert input_data.channel_title == "Test Channel"
    assert input_data.channel_id is None
    assert input_data.channel_username is None


@pytest.mark.unit
def test_telegram_channel_input_username_with_at():
    """Тест username с @."""
    input_data = TelegramChannelInput(
        channel_title="Test",
        channel_username="@test_channel"
    )
    assert input_data.channel_username == "test_channel"


@pytest.mark.unit
def test_max_channel_input_valid():
    """Тест валидного MaxChannelInput."""
    input_data = MaxChannelInput(channel_id="test_channel")
    
    assert input_data.channel_id == "test_channel"


@pytest.mark.unit
def test_max_channel_input_empty():
    """Тест пустого channel_id."""
    with pytest.raises(ValidationError):
        MaxChannelInput(channel_id="")


@pytest.mark.unit
def test_max_channel_input_none():
    """Тест None channel_id."""
    with pytest.raises(ValidationError):
        MaxChannelInput(channel_id=None)

