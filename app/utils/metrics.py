"""Метрики производительности."""

import time
import os
from typing import Dict, Any, Optional
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from app.utils.logger import get_logger
from config.settings import settings

# Опциональный импорт psutil
try:
    import psutil

    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False

# Опциональный импорт engine
try:
    from config.database import engine

    ENGINE_AVAILABLE = True
except ImportError:
    ENGINE_AVAILABLE = False

logger = get_logger(__name__)


class MetricsCollector:
    """Сборщик метрик производительности."""

    def __init__(self):
        self.metrics: Dict[str, Any] = defaultdict(
            lambda: {
                "count": 0,
                "total_time": 0.0,
                "min_time": float("inf"),
                "max_time": 0.0,
                "errors": 0,
                "last_update": None,
            }
        )
        self.enabled = settings.enable_metrics

    def record_timing(self, operation: str, duration: float, success: bool = True):
        """
        Записать время выполнения операции.

        Args:
            operation: Название операции
            duration: Время выполнения в секундах
            success: Успешность операции
        """
        if not self.enabled:
            return

        metric = self.metrics[operation]
        metric["count"] += 1
        metric["total_time"] += duration
        metric["min_time"] = min(metric["min_time"], duration)
        metric["max_time"] = max(metric["max_time"], duration)
        if not success:
            metric["errors"] += 1
        metric["last_update"] = datetime.utcnow()

    def get_metrics(self) -> Dict[str, Any]:
        """Получить все метрики."""
        result = {}
        for operation, data in self.metrics.items():
            avg_time = data["total_time"] / data["count"] if data["count"] > 0 else 0
            result[operation] = {
                "count": data["count"],
                "avg_time": round(avg_time, 3),
                "min_time": round(data["min_time"], 3) if data["min_time"] != float("inf") else 0,
                "max_time": round(data["max_time"], 3),
                "errors": data["errors"],
                "error_rate": round(data["errors"] / data["count"], 3) if data["count"] > 0 else 0,
                "last_update": data["last_update"].isoformat() if data["last_update"] else None,
            }
        return result

    def reset(self):
        """Сбросить метрики."""
        self.metrics.clear()
        logger.info("metrics_reset")

    def log_summary(self):
        """Вывести сводку метрик в лог."""
        if not self.enabled:
            return

        metrics = self.get_metrics()
        if metrics:
            logger.info("metrics_summary", metrics=metrics)

    def get_system_metrics(self) -> Dict[str, Any]:
        """
        Получить системные метрики.

        Returns:
            Словарь с системными метриками
        """
        try:
            metrics = {}

            # Использование памяти и CPU (требует psutil)
            if PSUTIL_AVAILABLE:
                try:
                    process = psutil.Process(os.getpid())
                    memory_info = process.memory_info()

                    # Использование памяти
                    metrics["memory_mb"] = round(memory_info.rss / (1024 * 1024), 2)
                    metrics["memory_percent"] = round(process.memory_percent(), 2)

                    # Использование CPU
                    metrics["cpu_percent"] = round(process.cpu_percent(interval=0.1), 2)
                except Exception as e:
                    logger.warning("failed_to_get_process_metrics", error=str(e))
            else:
                metrics["memory_mb"] = None
                metrics["memory_percent"] = None
                metrics["cpu_percent"] = None

            # Размер медиа-файлов
            media_size_mb = 0
            media_file_count = 0
            if settings.media_storage_path:
                try:
                    # Поддерживаем как абсолютные, так и относительные пути
                    if settings.media_storage_path.startswith("/"):
                        media_path = Path(settings.media_storage_path)
                    else:
                        PROJECT_ROOT = Path(__file__).parent.parent.parent
                        media_path = PROJECT_ROOT / settings.media_storage_path

                    if media_path.exists():
                        for file_path in media_path.iterdir():
                            if file_path.is_file():
                                media_size_mb += file_path.stat().st_size / (1024 * 1024)
                                media_file_count += 1
                except Exception as e:
                    logger.warning("failed_to_get_media_metrics", error=str(e))

            metrics["media_size_mb"] = round(media_size_mb, 2)
            metrics["media_file_count"] = media_file_count

            # Количество активных соединений к БД
            db_connections = 0
            if ENGINE_AVAILABLE:
                try:
                    pool = engine.pool
                    db_connections = pool.size() if hasattr(pool, "size") else 0
                except Exception as e:
                    logger.debug("failed_to_get_db_connections", error=str(e))

            metrics["db_connections"] = db_connections
            metrics["timestamp"] = datetime.utcnow().isoformat()

            return metrics
        except Exception as e:
            logger.error("failed_to_get_system_metrics", error=str(e), exc_info=True)
            return {}

    def get_all_metrics(self) -> Dict[str, Any]:
        """
        Получить все метрики (операционные + системные).

        Returns:
            Словарь со всеми метриками
        """
        return {"operations": self.get_metrics(), "system": self.get_system_metrics()}


# Глобальный экземпляр
metrics_collector = MetricsCollector()


def record_operation_time(operation: str):
    """Декоратор для записи времени выполнения операции."""

    def decorator(func):
        async def wrapper(*args, **kwargs):
            if not metrics_collector.enabled:
                return await func(*args, **kwargs)

            start_time = time.time()
            success = True
            try:
                result = await func(*args, **kwargs)
                return result
            except Exception:
                success = False
                raise
            finally:
                duration = time.time() - start_time
                metrics_collector.record_timing(operation, duration, success)

        return wrapper

    return decorator
