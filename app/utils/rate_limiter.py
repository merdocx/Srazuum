"""Rate limiter для API запросов."""
import asyncio
import time
from typing import Dict, Optional
from collections import defaultdict
from app.utils.logger import get_logger
from app.utils.metrics import metrics_collector

logger = get_logger(__name__)


class RateLimiter:
    """Rate limiter с sliding window."""
    
    def __init__(self, max_calls: int, period: float):
        """
        Инициализация rate limiter.
        
        Args:
            max_calls: Максимальное количество вызовов
            period: Период в секундах
        """
        self.max_calls = max_calls
        self.period = period
        self.calls: Dict[str, list] = defaultdict(list)
        self.locks: Dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
    
    async def acquire(self, key: str = "default") -> bool:
        """
        Проверить и зарегистрировать вызов.
        
        Args:
            key: Ключ для разделения лимитов
        
        Returns:
            True если можно выполнить запрос, False если превышен лимит
        """
        async with self.locks[key]:
            now = time.time()
            # Удаляем старые вызовы
            self.calls[key] = [
                call_time for call_time in self.calls[key]
                if now - call_time < self.period
            ]
            
            if len(self.calls[key]) >= self.max_calls:
                # Записываем метрику rate limit hit
                if metrics_collector.enabled:
                    metrics_collector.record_timing(f"rate_limit_hit_{key}", 0, success=False)
                
                logger.warning(
                    "rate_limit_exceeded",
                    key=key,
                    calls=len(self.calls[key]),
                    max_calls=self.max_calls
                )
                return False
            
            self.calls[key].append(now)
            return True
    
    async def wait_if_needed(self, key: str = "default") -> None:
        """
        Подождать если нужно для соблюдения лимита.
        
        Args:
            key: Ключ для разделения лимитов
        """
        if not await self.acquire(key):
            # Вычисляем время до следующего доступного слота
            async with self.locks[key]:
                if self.calls[key]:
                    oldest_call = min(self.calls[key])
                    wait_time = self.period - (time.time() - oldest_call)
                    if wait_time > 0:
                        logger.info("rate_limit_wait", key=key, wait_time=wait_time)
                        await asyncio.sleep(wait_time)
                        # Повторная попытка
                        await self.acquire(key)


# Глобальные rate limiters
max_api_limiter = RateLimiter(max_calls=30, period=1.0)  # 30 запросов в секунду
telegram_api_limiter = RateLimiter(max_calls=20, period=1.0)  # 20 запросов в секунду



