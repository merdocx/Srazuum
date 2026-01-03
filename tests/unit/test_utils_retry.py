"""Тесты для утилиты retry."""
import pytest
import asyncio
from app.utils.retry import retry_with_backoff
from app.utils.exceptions import APIError


@pytest.mark.asyncio
@pytest.mark.unit
async def test_retry_success():
    """Тест успешного выполнения без повторных попыток."""
    call_count = 0
    
    async def success_func():
        nonlocal call_count
        call_count += 1
        return "success"
    
    result = await retry_with_backoff(success_func, max_attempts=3, base_delay=0.1)
    assert result == "success"
    assert call_count == 1


@pytest.mark.asyncio
@pytest.mark.unit
async def test_retry_with_failures():
    """Тест повторных попыток при ошибках."""
    call_count = 0
    
    async def fail_then_success():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise APIError("Temporary error")
        return "success"
    
    result = await retry_with_backoff(fail_then_success, max_attempts=3, base_delay=0.1)
    assert result == "success"
    assert call_count == 3


@pytest.mark.asyncio
@pytest.mark.unit
async def test_retry_exhausted():
    """Тест исчерпания попыток."""
    call_count = 0
    
    async def always_fail():
        nonlocal call_count
        call_count += 1
        raise APIError("Persistent error")
    
    with pytest.raises(APIError):
        await retry_with_backoff(always_fail, max_attempts=2, base_delay=0.1)
    
    assert call_count == 2

