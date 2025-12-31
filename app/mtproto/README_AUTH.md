# Авторизация MTProto

## Обновленные данные

- **Телефон**: +79099297070
- **API ID**: 30899492
- **API Hash**: b5318acb70e38eddf4e79359c1f1f2d4

## Способы авторизации

### 1. Интерактивная авторизация (рекомендуется)

Используйте интерактивный скрипт для авторизации:

```bash
cd /root/crossposting_service
source venv/bin/activate
python -m app.mtproto.auth_interactive
```

Скрипт запросит код подтверждения, который придет в Telegram.

### 2. Авторизация по шагам

Если интерактивная авторизация не работает, используйте двухшаговый процесс:

**Шаг 1: Запрос кода**
```bash
python -m app.mtproto.auth step1
```

**Шаг 2: Использование кода**
```bash
python -m app.mtproto.auth step2 <код>
```

### 3. Авторизация с session string

Если у вас есть session string из Telegram Desktop:

**Способ 1: Через файл**
1. Сохраните session string в файл `session_string.txt` в корне проекта
2. Запустите:
```bash
python -m app.mtproto.auth_with_session_string auth
```

**Способ 2: Прямая передача**
```bash
python -m app.mtproto.auth_with_session_string auth "ваш_session_string"
```

**Экспорт session string из существующей сессии:**
Если у вас уже есть авторизованная сессия, можно экспортировать session string:
```bash
python -m app.mtproto.auth_with_session_string export
```

## Получение session string из Telegram Desktop

Файл `result.json` из экспорта Telegram содержит информацию о сессиях, но не содержит session string.

Для получения session string:

1. **Используйте Pyrogram для экспорта** (если сессия уже создана):
   ```bash
   python -m app.mtproto.auth_with_session_string export
   ```

2. **Или используйте интерактивную авторизацию** для создания новой сессии:
   ```bash
   python -m app.mtproto.auth_interactive
   ```

## Использование в receiver

После успешной авторизации сессия будет сохранена в файл `crossposting_session.session` и будет автоматически использоваться при запуске `MTProtoReceiver`.

Если у вас есть session string, вы можете передать его в `receiver.start()`:

```python
from app.mtproto.receiver import MTProtoReceiver

receiver = MTProtoReceiver()
await receiver.start(session_string="ваш_session_string")
```

## Примечания

- Файл `result.json` из экспорта Telegram содержит только метаданные о сессиях, но не сами данные сессии
- Для авторизации нужен либо session string, либо интерактивная авторизация
- После успешной авторизации сессия сохраняется в файл `.session` и может использоваться повторно



