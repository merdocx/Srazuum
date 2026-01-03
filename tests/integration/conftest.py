"""Конфигурация для интеграционных тестов."""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def api_client():
    """Фикстура для тестового клиента API."""
    # TODO: Настроить TestClient для admin panel API
    # from admin_panel.backend.main import app
    # return TestClient(app)
    pass

