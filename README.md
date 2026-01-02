# Сервис кросспостинга из Telegram в MAX

**Версия:** 1.3.6

Автоматический сервис для кросспостинга сообщений из каналов Telegram в каналы мессенджера MAX.

## Установка

1. Клонируйте репозиторий
2. Создайте виртуальное окружение:
   ```bash
   python -m venv venv
   source venv/bin/activate  # Linux/Mac
   # или
   venv\Scripts\activate  # Windows
   ```

3. Установите зависимости:
   ```bash
   pip install -r requirements.txt
   ```

4. Скопируйте `.env.example` в `.env` и заполните переменные окружения

   **Важно:** Для работы MTProto нужны API ID и API Hash. 
   Получите их на https://my.telegram.org/apps
   Подробная инструкция: [docs/MTProto_GUIDE.md](docs/MTProto_GUIDE.md)

5. Настройте базу данных:
   ```bash
   alembic upgrade head
   ```

## Запуск

### Telegram Bot Handler (команды пользователей)
```bash
python -m app.bot.main
```

### Telegram MTProto Receiver (получение сообщений из каналов)
```bash
python -m app.mtproto.main
```


## Структура проекта

```
crossposting_service/
├── app/
│   ├── bot/          # Telegram Bot Handler
│   ├── mtproto/      # Telegram MTProto Receiver
│   ├── max_api/       # MAX API Client
│   ├── core/          # Core logic (Message Processor)
│   ├── models/        # SQLAlchemy models
│   └── utils/         # Utilities
├── alembic/           # Database migrations
├── tests/             # Tests
└── config/            # Configuration
```

## Документация

- [Техническое задание](TZ_crossposting.md) - полное ТЗ проекта
- [Руководство по MTProto](docs/MTProto_GUIDE.md) - подробное описание MTProto и получение API ID/Hash
- [FAQ по MTProto](docs/MTProto_FAQ.md) - часто задаваемые вопросы
- [Быстрый старт](QUICKSTART.md) - пошаговая инструкция по запуску
- [Статус реализации](IMPLEMENTATION_STATUS.md) - что реализовано и что осталось

## Разработка

См. техническое задание в `TZ_crossposting.md`

