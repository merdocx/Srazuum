"""Настройка логирования для админ-панели."""

import sys
from pathlib import Path

# Добавляем путь к основному приложению для импорта logger
project_root = Path(__file__).parent.parent.parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

try:
    from app.utils.logger import get_logger as _get_logger_main

    def get_logger(name: str = __name__):
        """Получить логгер из основного приложения."""
        return _get_logger_main(name)

except ImportError:
    # Fallback на стандартный logging, если основной модуль недоступен
    import logging

    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=logging.INFO,
    )

    def get_logger(name: str = __name__):
        """Получить стандартный логгер."""
        return logging.getLogger(name)
