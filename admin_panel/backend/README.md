# Srazuum Admin Panel - Backend

FastAPI backend для админ-панели Srazuum.

## Структура

```
backend/
├── app/
│   ├── api/           # API endpoints
│   ├── core/          # Конфигурация, БД, безопасность
│   ├── models/        # SQLAlchemy модели
│   └── schemas/       # Pydantic схемы
├── main.py            # Точка входа
└── create_admin.py    # Скрипт создания администратора
```

## Установка

1. Активируйте виртуальное окружение основного проекта:
```bash
cd /root/crossposting_service
source venv/bin/activate
```

2. Установите зависимости админ-панели:
```bash
cd admin_panel/backend
pip install -r requirements.txt
```

3. Примените миграцию для создания таблиц админов:
```bash
cd /root/crossposting_service
alembic upgrade head
```

4. Создайте первого администратора:
```bash
cd admin_panel/backend
python create_admin.py admin admin@example.com
```

## Запуск

### Разработка
```bash
cd admin_panel/backend
uvicorn main:app --reload --host 0.0.0.0 --port 8001
```

### Production
Используйте systemd service или process manager (PM2, supervisor).

## API

- Swagger UI: http://localhost:8001/docs
- ReDoc: http://localhost:8001/redoc

## Endpoints

- `POST /api/auth/login` - Вход
- `GET /api/auth/me` - Информация о текущем администраторе

