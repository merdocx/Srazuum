"""Circuit breaker для защиты от каскадных сбоев."""
import asyncio
import time
from typing import Optional, Callable, Any, Type
from enum import Enum
from app.utils.logger import get_logger
from app.utils.exceptions import APIError

logger = get_logger(__name__)


class CircuitState(Enum):
    """Состояния circuit breaker."""
    CLOSED = "closed"  # Нормальная работа
    OPEN = "open"  # Разомкнут, запросы блокируются
    HALF_OPEN = "half_open"  # Тестовый режим


class CircuitBreaker:
    """Circuit breaker для защиты от каскадных сбоев."""
    
    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: int = 60,
        expected_exception: Type[Exception] = Exception
    ):
        """
        Инициализация circuit breaker.
        
        Args:
            failure_threshold: Количество ошибок для открытия
            recovery_timeout: Время восстановления в секундах
            expected_exception: Тип исключения для отслеживания
        """
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.expected_exception = expected_exception
        
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.last_failure_time: Optional[float] = None
        self.success_count = 0
        self.lock = asyncio.Lock()
    
    async def call(self, func: Callable, *args, **kwargs) -> Any:
        """
        Вызвать функцию через circuit breaker.
        
        Args:
            func: Функция для вызова
            *args: Аргументы функции
            **kwargs: Ключевые аргументы функции
        
        Returns:
            Результат вызова функции
        
        Raises:
            APIError: Если circuit breaker открыт
        """
        async with self.lock:
            # Проверяем состояние
            if self.state == CircuitState.OPEN:
                if time.time() - (self.last_failure_time or 0) >= self.recovery_timeout:
                    # Переходим в half-open для теста
                    self.state = CircuitState.HALF_OPEN
                    self.success_count = 0
                    logger.info("circuit_breaker_half_open")
                else:
                    # Circuit открыт, блокируем запрос
                    raise APIError(
                        f"Circuit breaker открыт. Попробуйте через {self.recovery_timeout} секунд"
                    )
        
        # Выполняем запрос
        try:
            result = await func(*args, **kwargs)
            await self._on_success()
            return result
        except self.expected_exception as e:
            await self._on_failure()
            raise
    
    async def _on_success(self):
        """Обработка успешного запроса."""
        async with self.lock:
            if self.state == CircuitState.HALF_OPEN:
                self.success_count += 1
                if self.success_count >= 2:  # Нужно 2 успешных запроса для закрытия
                    self.state = CircuitState.CLOSED
                    self.failure_count = 0
                    self.success_count = 0
                    logger.info("circuit_breaker_closed")
            elif self.state == CircuitState.CLOSED:
                # Сбрасываем счетчик ошибок при успехе
                self.failure_count = 0
    
    async def _on_failure(self) -> None:
        """Обработка ошибки."""
        async with self.lock:
            self.failure_count += 1
            self.last_failure_time = time.time()
            
            if self.state == CircuitState.HALF_OPEN:
                # В half-open любая ошибка открывает circuit
                self.state = CircuitState.OPEN
                logger.warning(
                    "circuit_breaker_opened_from_half_open",
                    failure_count=self.failure_count
                )
            elif self.state == CircuitState.CLOSED:
                if self.failure_count >= self.failure_threshold:
                    self.state = CircuitState.OPEN
                    logger.error(
                        "circuit_breaker_opened",
                        failure_count=self.failure_count,
                        threshold=self.failure_threshold
                    )
    
    def get_state(self) -> CircuitState:
        """Получить текущее состояние."""
        return self.state
    
    async def reset(self) -> None:
        """
        Сбросить circuit breaker в исходное состояние.
        """
        async with self.lock:
            self.state = CircuitState.CLOSED
            self.failure_count = 0
            self.success_count = 0
            self.last_failure_time = None
            logger.info("circuit_breaker_reset")








