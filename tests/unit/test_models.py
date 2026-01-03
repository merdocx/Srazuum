"""Тесты для моделей данных."""
import pytest
from datetime import datetime
from sqlalchemy import select

from app.models.user import User
from app.models.telegram_channel import TelegramChannel
from app.models.max_channel import MaxChannel
from app.models.crossposting_link import CrosspostingLink


@pytest.mark.asyncio
@pytest.mark.unit
async def test_user_creation(db_session):
    """Тест создания пользователя."""
    user = User(
        telegram_user_id=123456789,
        telegram_username="test_user"
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    
    assert user.id is not None
    assert user.telegram_user_id == 123456789
    assert user.telegram_username == "test_user"
    assert user.created_at is not None


@pytest.mark.asyncio
@pytest.mark.unit
async def test_telegram_channel_creation(db_session):
    """Тест создания Telegram канала."""
    user = User(telegram_user_id=123456789)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    
    channel = TelegramChannel(
        user_id=user.id,
        channel_id=-1001234567890,
        channel_username="test_channel",
        channel_title="Test Channel"
    )
    db_session.add(channel)
    await db_session.commit()
    await db_session.refresh(channel)
    
    assert channel.id is not None
    assert channel.user_id == user.id
    assert channel.channel_id == -1001234567890
    assert channel.channel_username == "test_channel"


@pytest.mark.asyncio
@pytest.mark.unit
async def test_max_channel_creation(db_session):
    """Тест создания MAX канала."""
    user = User(telegram_user_id=123456789)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    
    max_channel = MaxChannel(
        user_id=user.id,
        channel_id="test_max_channel",
        channel_title="Test MAX Channel"
    )
    db_session.add(max_channel)
    await db_session.commit()
    await db_session.refresh(max_channel)
    
    assert max_channel.id is not None
    assert max_channel.user_id == user.id
    assert max_channel.channel_id == "test_max_channel"


@pytest.mark.asyncio
@pytest.mark.unit
async def test_crossposting_link_creation(db_session):
    """Тест создания связи кросспостинга."""
    user = User(telegram_user_id=123456789)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    
    tg_channel = TelegramChannel(
        user_id=user.id,
        channel_id=-1001234567890,
        channel_title="TG Channel"
    )
    max_channel = MaxChannel(
        user_id=user.id,
        channel_id="max_channel",
        channel_title="MAX Channel"
    )
    db_session.add(tg_channel)
    db_session.add(max_channel)
    await db_session.commit()
    await db_session.refresh(tg_channel)
    await db_session.refresh(max_channel)
    
    link = CrosspostingLink(
        user_id=user.id,
        telegram_channel_id=tg_channel.id,
        max_channel_id=max_channel.id,
        is_enabled=True
    )
    db_session.add(link)
    await db_session.commit()
    await db_session.refresh(link)
    
    assert link.id is not None
    assert link.user_id == user.id
    assert link.is_enabled is True

