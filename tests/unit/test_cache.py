"""Тесты для кеширования."""

import pytest
from unittest.mock import AsyncMock, patch
from app.utils.cache import (
    get_cache,
    set_cache,
    delete_cache,
    get_channel_cache_key,
    get_links_cache_key,
    get_active_links_cache_key,
)


@pytest.mark.asyncio
@pytest.mark.unit
async def test_cache_set_and_get():
    """Тест установки и получения значения из кеша."""
    key = "test_key"
    value = {"test": "data"}

    mock_redis = AsyncMock()
    mock_redis.get.return_value = b'{"test": "data"}'
    mock_redis.setex = AsyncMock()

    with patch("app.utils.cache.get_redis", return_value=mock_redis):
        await set_cache(key, value, 60)
        cached_value = await get_cache(key)

    assert cached_value == value
    mock_redis.setex.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.unit
async def test_cache_get_nonexistent():
    """Тест получения несуществующего ключа."""
    mock_redis = AsyncMock()
    mock_redis.get.return_value = None

    with patch("app.utils.cache.get_redis", return_value=mock_redis):
        result = await get_cache("nonexistent_key")

    assert result is None


@pytest.mark.asyncio
@pytest.mark.unit
async def test_cache_delete():
    """Тест удаления ключа из кеша."""
    key = "test_delete_key"

    mock_redis = AsyncMock()
    mock_redis.delete = AsyncMock()

    with patch("app.utils.cache.get_redis", return_value=mock_redis):
        await delete_cache(key)

    mock_redis.delete.assert_called_once_with(key)


@pytest.mark.unit
def test_cache_key_generators():
    """Тест генераторов ключей кеша."""
    assert get_channel_cache_key(123) == "channel:123"
    assert get_links_cache_key(456) == "user_links:456"
    assert get_active_links_cache_key() == "active_links"
