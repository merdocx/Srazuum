# Получение Session String из Telegram Desktop на Mac

## Важно

Файлы сессий Telegram Desktop на Mac зашифрованы и находятся в:
```
~/Library/Application Support/Telegram Desktop/tdata/
```

Прямое извлечение session string из этих файлов **сложно**, так как они используют специальное шифрование.

## Рекомендуемый способ (самый простой)

### Использование интерактивной авторизации Pyrogram

Этот способ не требует доступа к файлам Telegram Desktop и работает на любой платформе.

#### Шаг 1: Интерактивная авторизация

```bash
cd /root/crossposting_service
source venv/bin/activate
python -m app.mtproto.auth_interactive
```

1. Скрипт запросит код подтверждения
2. Код придет в Telegram (в приложение или SMS)
3. Введите код в терминал
4. После успешной авторизации сессия сохранится в `crossposting_session.session`

#### Шаг 2: Экспорт session string

После успешной авторизации экспортируйте session string:

```bash
python -m app.mtproto.auth_with_session_string export
```

Session string будет сохранен в файл `session_string.txt` в корне проекта.

## Альтернативные способы

### Способ 1: Использование Telegram Desktop через Pyrogram

Если у вас уже есть авторизованная сессия Pyrogram, можно экспортировать session string:

```bash
python -m app.mtproto.auth_with_session_string export
```

### Способ 2: Использование готовых инструментов

Существуют сторонние инструменты для извлечения session string:

1. **TelegramSessionExtractor** - требует установки и настройки
2. **telethon-session-extractor** - для библиотеки Telethon

⚠️ **Внимание**: Используйте сторонние инструменты на свой риск. Проверяйте их безопасность перед использованием.

### Способ 3: Ручное извлечение (для продвинутых пользователей)

1. Найдите файлы сессий в:
   ```
   ~/Library/Application Support/Telegram Desktop/tdata/
   ```

2. Файлы сессий обычно имеют имена вида: `D877F783D5D3EF8C`, `A7FDF864FBC10B77`

3. Используйте специальные инструменты для расшифровки (требует глубоких знаний)

⚠️ **Не рекомендуется**: Этот способ сложен и может привести к потере данных.

## Проверка установки Telegram Desktop

Запустите скрипт для проверки:

```bash
python -m app.mtproto.extract_session_mac
```

Скрипт покажет:
- Установлен ли Telegram Desktop
- Найдены ли файлы сессий
- Инструкции по получению session string

## Использование session string

После получения session string:

### Вариант 1: Через файл

1. Сохраните session string в файл `session_string.txt` в корне проекта
2. Запустите авторизацию:

```bash
python -m app.mtproto.auth_with_session_string auth
```

### Вариант 2: Прямая передача

```bash
python -m app.mtproto.auth_with_session_string auth "ваш_session_string"
```

### Вариант 3: В коде

```python
from app.mtproto.receiver import MTProtoReceiver

receiver = MTProtoReceiver()
await receiver.start(session_string="ваш_session_string")
```

## Примечания

- Session string - это длинная строка, содержащая данные авторизации
- Храните session string в безопасности - он дает полный доступ к аккаунту
- Не публикуйте session string в открытых репозиториях
- Если session string скомпрометирован, отзовите его в настройках Telegram

## Troubleshooting

### Проблема: "Session string недействителен"

**Решение**: 
- Получите новый session string через интерактивную авторизацию
- Проверьте, что session string скопирован полностью (без пробелов, переносов строк)

### Проблема: "Telegram Desktop не найден"

**Решение**:
- Установите Telegram Desktop с официального сайта: https://desktop.telegram.org
- Или используйте интерактивную авторизацию Pyrogram (не требует Telegram Desktop)

### Проблем: "Код подтверждения не приходит"

**Решение**:
- Проверьте номер телефона в `.env`
- Убедитесь, что Telegram Desktop/приложение открыто
- Попробуйте запросить код повторно через несколько минут


