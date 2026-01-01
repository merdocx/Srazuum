"""Тесты для circuit breaker."""
import pytest
import asyncio
from app.utils.circuit_breaker import CircuitBreaker, CircuitState
from app.utils.exceptions import APIError


@pytest.mark.asyncio
async def test_circuit_breaker_closed():
    """Тест нормальной работы circuit breaker."""
    breaker = CircuitBreaker(failure_threshold=3, recovery_timeout=1)
    
    async def success_func():
        return "success"
    
    result = await breaker.call(success_func)
    assert result == "success"
    assert breaker.get_state() == CircuitState.CLOSED


@pytest.mark.asyncio
async def test_circuit_breaker_opens_after_failures():
    """Тест открытия circuit breaker после ошибок."""
    breaker = CircuitBreaker(failure_threshold=2, recovery_timeout=1)
    
    async def fail_func():
        raise APIError("Test error")
    
    # Первая ошибка
    with pytest.raises(APIError):
        await breaker.call(fail_func)
    
    # Вторая ошибка - circuit должен открыться
    with pytest.raises(APIError):
        await breaker.call(fail_func)
    
    # Circuit открыт, запросы блокируются
    with pytest.raises(APIError) as exc_info:
        await breaker.call(fail_func)
    assert "Circuit breaker открыт" in str(exc_info.value)



