# API Документация

## Telegram Bot API

### Команды

#### `/start`
Начало работы с ботом.

**Ответ:** Приветственное сообщение с инструкциями.

#### `/add_channel`
Добавление новой связи кросспостинга.

**Процесс:**
1. Отправьте сообщение из Telegram канала или укажите @username
2. Отправьте ID или username MAX канала

**Пример:**
```
/add_channel
[Пересылаете сообщение из Telegram канала]
-70002399365886
```

#### `/list_channels`
Список всех активных связей кросспостинга.

**Ответ:** Список связей с информацией о каналах.

#### `/delete_channel <link_id>`
Удаление связи кросспостинга.

**Параметры:**
- `link_id` - ID связи (можно получить из `/list_channels`)

#### `/enable_channel <link_id>`
Включение связи кросспостинга.

#### `/disable_channel <link_id>`
Отключение связи кросспостинга.

#### `/stats`
Статистика по отправленным сообщениям.

**Ответ:** Количество успешных и неудачных отправок.

## MAX API

### Endpoints

#### `POST /messages?chat_id={chat_id}`
Отправка сообщения в канал.

**Параметры:**
- `chat_id` (query) - ID канала в MAX

**Тело запроса:**
```json
{
  "text": "Текст сообщения",
  "format": "markdown",
  "attachments": [
    {
      "type": "image",
      "payload": {
        "token": "token_from_upload"
      }
    }
  ]
}
```

#### `POST /uploads?type={type}`
Получение URL для загрузки файла.

**Параметры:**
- `type` (query) - Тип файла: `image`, `video`, `document`, `audio`

**Ответ:**
```json
{
  "url": "https://vu.okcdn.ru/upload.do?...",
  "token": "token_for_attachment"
}
```

## Формат сообщений

### Текст
```json
{
  "text": "Текст сообщения",
  "format": "markdown"
}
```

### Фото
```json
{
  "text": "Подпись к фото",
  "attachments": [
    {
      "type": "image",
      "payload": {
        "token": "token_from_upload"
      }
    }
  ]
}
```

### Видео
```json
{
  "text": "Подпись к видео",
  "attachments": [
    {
      "type": "video",
      "payload": {
        "token": "token_from_upload"
      }
    }
  ]
}
```

### Альбом (несколько фото/видео)
```json
{
  "text": "Подпись к альбому",
  "attachments": [
    {
      "type": "image",
      "payload": {
        "token": "token1"
      }
    },
    {
      "type": "image",
      "payload": {
        "token": "token2"
      }
    }
  ]
}
```

## Markdown форматирование

Поддерживаемые форматы:
- **Жирный текст**: `**текст**`
- *Курсив*: `*текст*`
- `Код`: `` `код` ``
- [Ссылки](url): `[текст](url)`
- ~~Зачеркнутый~~: `~~текст~~`
- ++Подчеркнутый++: `++текст++`








