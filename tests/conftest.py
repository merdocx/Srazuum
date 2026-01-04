"""Конфигурация pytest."""

import pytest
import asyncio
import sys
import os
from pathlib import Path
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool

# Добавляем корень проекта в путь
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Импортируем Base и модели
from config.database import Base

# Импортируем все модели, чтобы они были зарегистрированы в Base.metadata
from app.models import User, TelegramChannel, MaxChannel, CrosspostingLink


# Тестовая база данных (PostgreSQL)
# Используем переменную окружения TEST_DATABASE_URL, если она установлена
# Иначе используем значение по умолчанию для локальной разработки
TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/crossposting_test",
)

test_engine = create_async_engine(
    TEST_DATABASE_URL,
    poolclass=NullPool,  # Не используем пул соединений для тестов
    echo=False,
)

TestSessionLocal = async_sessionmaker(
    test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


@pytest.fixture(scope="function")
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Фикстура для тестовой сессии БД."""
    # Создаем все таблицы перед тестом
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Выполняем тест
    async with TestSessionLocal() as session:
        yield session
        await session.rollback()

    # Удаляем все таблицы после теста
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture(scope="function")
def event_loop():
    """Фикстура для event loop."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()
