# CI/CD Workflows

Этот проект использует GitHub Actions для автоматической проверки кода.

## Workflows

### 1. CI Workflow (`.github/workflows/ci.yml`)

Основной workflow, который запускается при:
- Push в ветки `main`, `master`, `develop`
- Создании Pull Request в эти ветки

**Проверки:**
1. **Линтинг (flake8)** - проверка качества кода
2. **Форматирование (black)** - проверка соответствия стилю
3. **Типы (mypy)** - проверка типов
4. **Тесты (pytest)** - запуск тестов с покрытием
5. **Загрузка отчета покрытия** - сохранение HTML отчета

**Сервисы:**
- PostgreSQL 15 (для тестов)
- Redis 7 (для тестов)

### 2. Lint Workflow (`.github/workflows/lint.yml`)

Отдельный workflow для быстрой проверки линтинга, форматирования и типов.

## Локальное использование

### Форматирование кода
```bash
black app/ tests/ admin_panel/backend/app/
```

### Проверка форматирования
```bash
black --check app/ tests/ admin_panel/backend/app/
```

### Линтинг
```bash
flake8 app/ tests/ admin_panel/backend/app/
```

### Проверка типов
```bash
mypy app/ --ignore-missing-imports --no-strict-optional
```

### Запуск тестов
```bash
pytest tests/ --cov=app --cov-report=term --cov-report=html -v
```

## Конфигурация

- **`.flake8`** - настройки flake8
- **`pyproject.toml`** - настройки black, mypy, pytest, coverage

## Отчеты покрытия

После выполнения CI/CD workflow:
- HTML отчет покрытия доступен в артефактах workflow
- XML отчет загружается в Codecov (если настроен)

