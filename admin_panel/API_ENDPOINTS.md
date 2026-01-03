# API Endpoints - Srazuum Admin Panel

## Аутентификация (`/api/auth`)

- `POST /api/auth/login` - Вход в систему
- `GET /api/auth/me` - Информация о текущем администраторе

## Статистика (`/api/stats`)

- `GET /api/stats/dashboard` - Статистика для dashboard
- `GET /api/stats/messages?days=7` - Статистика сообщений за период

## Система (`/api/system`)

- `GET /api/system/status` - Статус системных сервисов и метрики

## Пользователи (`/api/users`)

- `GET /api/users?skip=0&limit=50&search=...` - Список пользователей
- `GET /api/users/{user_id}` - Детальная информация о пользователе

## Каналы (`/api/channels`)

- `GET /api/channels/telegram?skip=0&limit=50&user_id=...&is_active=...&search=...` - Список Telegram каналов
- `GET /api/channels/telegram/{channel_id}` - Детали Telegram канала
- `GET /api/channels/max?skip=0&limit=50&user_id=...&is_active=...&search=...` - Список MAX каналов
- `GET /api/channels/max/{channel_id}` - Детали MAX канала

## Связи (`/api/links`)

- `GET /api/links?skip=0&limit=50&user_id=...&is_enabled=...&telegram_channel_id=...&max_channel_id=...` - Список связей
- `GET /api/links/{link_id}` - Детальная информация о связи

## Логи (`/api/logs`)

- `GET /api/logs/messages?skip=0&limit=50&link_id=...&status=...&start_date=...&end_date=...` - Логи сообщений
- `GET /api/logs/messages/{log_id}` - Детали лога сообщения
- `GET /api/logs/failed?skip=0&limit=50&link_id=...&resolved=...` - Неудачные сообщения
- `GET /api/logs/audit?skip=0&limit=50&user_id=...&action=...&start_date=...&end_date=...` - Логи аудита

## Общие параметры

Все endpoints поддерживают:
- Пагинация: `skip`, `limit`
- Фильтрация (где применимо)
- Поиск (где применимо)
- Аутентификация: все endpoints требуют JWT токен (кроме `/api/auth/login`)

## Формат ответа

Все списки возвращают:
```json
{
  "total": 100,
  "skip": 0,
  "limit": 50,
  "data": [...]
}
```

Детальные endpoints возвращают объект напрямую.
