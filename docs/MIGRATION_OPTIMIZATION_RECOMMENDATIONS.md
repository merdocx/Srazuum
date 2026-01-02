# Рекомендации по оптимизации и параллельной обработке для миграции постов

## Анализ текущего ТЗ и рекомендации

### 1. Оптимизация получения истории постов

#### Проблема в ТЗ:
- Получение всей истории одним запросом может быть медленным для больших каналов
- Нет упоминания о потоковой обработке (streaming)

#### Рекомендации:

**1.1. Потоковая обработка (Streaming)**
```python
# Вместо получения всей истории сразу
async def _get_chat_history_stream(self, chat_id):
    """Получать историю потоком, обрабатывать по мере получения"""
    async for message in self.pyrogram_client.get_chat_history(chat_id, limit=None):
        yield message
        # Обрабатывать сразу, не ждать загрузки всей истории
```

**Преимущества:**
- Начало обработки сразу после получения первых постов
- Меньше потребление памяти
- Возможность показа прогресса в реальном времени

**1.2. Параллельное получение истории по частям**
```python
# Разделить историю на временные интервалы
# Получать параллельно разные периоды
async def _get_chat_history_parallel(self, chat_id, date_ranges):
    """Получать историю параллельно по временным интервалам"""
    tasks = [
        self._get_chat_history_period(chat_id, start_date, end_date)
        for start_date, end_date in date_ranges
    ]
    results = await asyncio.gather(*tasks)
    # Объединить и отсортировать по дате
    return sorted(chain(*results), key=lambda m: m.date)
```

**Преимущества:**
- Ускорение получения истории для больших каналов
- Возможность обработки разных периодов параллельно

---

### 2. Оптимизация проверки на дублирование

#### Проблема в ТЗ:
- Проверка каждого поста отдельным запросом к БД
- Для больших каналов это тысячи запросов

#### Рекомендации:

**2.1. Батчинг проверки дублирования**
```python
# Вместо проверки каждого поста отдельно
async def _check_duplicates_batch(self, link_id, message_ids, session):
    """Проверка дублирования батчами"""
    batch_size = 1000  # Проверять по 1000 постов за раз
    existing_ids = set()
    
    for i in range(0, len(message_ids), batch_size):
        batch = message_ids[i:i + batch_size]
        result = await session.execute(
            select(MessageLog.telegram_message_id)
            .where(MessageLog.crossposting_link_id == link_id)
            .where(MessageLog.telegram_message_id.in_(batch))
            .where(MessageLog.status == MessageStatus.SUCCESS)
        )
        existing_ids.update(result.scalars().all())
    
    return existing_ids
```

**Преимущества:**
- Сокращение количества запросов к БД с N до N/1000
- Значительное ускорение для больших каналов

**2.2. Кэширование уже перенесенных постов**
```python
# Загрузить все уже перенесенные посты в память один раз
async def _load_existing_messages_cache(self, link_id, session):
    """Загрузить все перенесенные посты в память"""
    result = await session.execute(
        select(MessageLog.telegram_message_id)
        .where(MessageLog.crossposting_link_id == link_id)
        .where(MessageLog.status == MessageStatus.SUCCESS)
    )
    return set(result.scalars().all())  # O(1) проверка в set
```

**Преимущества:**
- O(1) проверка вместо O(log N) в БД
- Один запрос вместо тысяч

**2.3. Индексы БД**
```sql
-- Убедиться, что есть составной индекс
CREATE INDEX IF NOT EXISTS idx_message_log_migration_check 
ON message_log(crossposting_link_id, telegram_message_id, status)
WHERE status = 'success';
```

---

### 3. Параллельная обработка постов

#### Проблема в ТЗ:
- Последовательная обработка постов
- Нет упоминания о параллельной обработке

#### Рекомендации:

**3.1. Параллельная обработка независимых постов**
```python
# Обрабатывать несколько постов параллельно
async def _process_posts_parallel(self, posts, existing_ids, semaphore):
    """Обрабатывать посты параллельно с ограничением"""
    tasks = []
    for post in posts:
        if post.id not in existing_ids:
            tasks.append(self._process_single_post(post, semaphore))
    
    # Обрабатывать батчами по N постов одновременно
    batch_size = 5  # Параллельно обрабатывать 5 постов
    results = []
    for i in range(0, len(tasks), batch_size):
        batch = tasks[i:i + batch_size]
        batch_results = await asyncio.gather(*batch, return_exceptions=True)
        results.extend(batch_results)
        # Задержка между батчами для соблюдения rate limits
        await asyncio.sleep(1)
    
    return results
```

**Преимущества:**
- Ускорение обработки в N раз (где N - размер батча)
- Соблюдение rate limits через semaphore

**3.2. Semaphore для контроля параллелизма**
```python
# Ограничить количество одновременных запросов к API
semaphore = asyncio.Semaphore(5)  # Максимум 5 параллельных запросов

async def _process_single_post(self, post, semaphore):
    async with semaphore:
        # Обработка поста
        await self.message_processor.process_message(...)
```

**3.3. Разделение на типы постов**
```python
# Обрабатывать текстовые посты параллельно с медиа-постами
text_posts = [p for p in posts if not p.media]
media_posts = [p for p in posts if p.media]

# Параллельная обработка разных типов
await asyncio.gather(
    self._process_text_posts_parallel(text_posts),
    self._process_media_posts_parallel(media_posts)
)
```

---

### 4. Оптимизация обработки медиа-групп

#### Проблема в ТЗ:
- Медиа-группы обрабатываются последовательно
- Нет упоминания о параллельной загрузке медиа

#### Рекомендации:

**4.1. Параллельная загрузка медиафайлов**
```python
# Уже реализовано в MaxAPIClient, но можно улучшить
# Использовать asyncio.gather для параллельной загрузки всех файлов группы
async def _download_media_group_parallel(self, messages, client):
    """Параллельная загрузка всех медиа из группы"""
    tasks = []
    for msg in messages:
        if msg.photo:
            tasks.append(self._download_photo(msg, client))
        elif msg.video:
            tasks.append(self._download_video(msg, client))
    
    # Загружать все параллельно
    results = await asyncio.gather(*tasks, return_exceptions=True)
    return [r for r in results if not isinstance(r, Exception)]
```

**4.2. Предварительная группировка медиа-групп**
```python
# Группировать медиа-группы ДО начала обработки
async def _group_messages_by_media_group(self, messages):
    """Группировать сообщения по media_group_id заранее"""
    groups = {}
    standalone = []
    
    for msg in messages:
        if msg.media_group_id:
            if msg.media_group_id not in groups:
                groups[msg.media_group_id] = []
            groups[msg.media_group_id].append(msg)
        else:
            standalone.append(msg)
    
    # Сортировать группы по дате первого сообщения
    sorted_groups = sorted(groups.values(), key=lambda g: min(m.date for m in g))
    
    return sorted_groups, standalone
```

---

### 5. Оптимизация запросов к БД

#### Рекомендации:

**5.1. Батчинг вставок в message_log**
```python
# Вместо создания записи для каждого поста отдельно
async def _batch_create_message_logs(self, logs_data, session):
    """Создавать записи в message_log батчами"""
    batch_size = 100
    
    for i in range(0, len(logs_data), batch_size):
        batch = logs_data[i:i + batch_size]
        session.add_all([
            MessageLog(**log_data) for log_data in batch
        ])
        await session.commit()
```

**5.2. Использование bulk operations**
```python
# Для больших объемов использовать bulk insert
from sqlalchemy.dialects.postgresql import insert

async def _bulk_insert_message_logs(self, logs_data, session):
    """Bulk insert для больших объемов"""
    stmt = insert(MessageLog).values(logs_data)
    await session.execute(stmt)
    await session.commit()
```

**5.3. Eager loading для связей**
```python
# Загружать связи с eager loading один раз
result = await session.execute(
    select(CrosspostingLink)
    .options(
        selectinload(CrosspostingLink.telegram_channel),
        selectinload(CrosspostingLink.max_channel)
    )
    .where(CrosspostingLink.id == link_id)
)
link = result.scalar_one()
# Использовать link.telegram_channel и link.max_channel без дополнительных запросов
```

---

### 6. Кэширование и оптимизация памяти

#### Рекомендации:

**6.1. Кэширование информации о связи**
```python
# Кэшировать информацию о связи на время миграции
@lru_cache(maxsize=100)
async def _get_link_info(self, link_id):
    """Кэшировать информацию о связи"""
    # Загрузить один раз, использовать многократно
    pass
```

**6.2. Потоковая обработка для экономии памяти**
```python
# Не загружать все посты в память сразу
async def migrate_link_posts_streaming(self, link_id):
    """Потоковая обработка для экономии памяти"""
    existing_ids = await self._load_existing_messages_cache(link_id)
    
    async for message in self._get_chat_history_stream(chat_id):
        if message.id not in existing_ids:
            await self._process_single_post(message)
            # Освобождать память после обработки
```

**6.3. Очистка медиафайлов сразу после отправки**
```python
# Удалять медиафайлы сразу после успешной отправки
# Не накапливать их в памяти
async def _process_and_cleanup(self, message):
    try:
        await self._process_message(message)
    finally:
        # Всегда удалять временные файлы
        await self._cleanup_temp_files(message)
```

---

### 7. Прогресс и уведомления

#### Рекомендации:

**7.1. Периодические обновления прогресса**
```python
# Отправлять промежуточные уведомления о прогрессе
async def _send_progress_update(self, processed, total, start_time):
    """Отправлять обновления прогресса каждые N постов или каждые X минут"""
    if processed % 100 == 0 or (time.time() - start_time) % 300 == 0:
        progress = (processed / total) * 100
        elapsed = time.time() - start_time
        estimated_total = elapsed * (total / processed) if processed > 0 else 0
        remaining = estimated_total - elapsed
        
        await self._send_progress_message(
            f"⏳ Прогресс: {processed}/{total} ({progress:.1f}%)\n"
            f"⏱ Осталось примерно: {remaining/60:.1f} минут"
        )
```

**7.2. Асинхронные уведомления**
```python
# Отправлять уведомления асинхронно, не блокируя обработку
async def _send_notification_async(self, message):
    """Отправлять уведомления в фоне"""
    asyncio.create_task(self.bot.send_message(chat_id, message))
```

---

### 8. Обработка ошибок и надежность

#### Рекомендации:

**8.1. Retry с exponential backoff для критических операций**
```python
# Для критических операций (получение истории) использовать retry
@retry(max_attempts=3, backoff_factor=2)
async def _get_chat_history_with_retry(self, chat_id):
    """Получение истории с повторными попытками"""
    return await self.pyrogram_client.get_chat_history(chat_id)
```

**8.2. Сохранение прогресса**
```python
# Сохранять прогресс миграции для возможности возобновления
async def _save_migration_progress(self, link_id, last_processed_id):
    """Сохранять последний обработанный ID для возобновления"""
    await self.cache.set(f"migration_progress:{link_id}", last_processed_id)
```

**8.3. Graceful shutdown**
```python
# Обрабатывать сигналы завершения корректно
import signal

def setup_graceful_shutdown(migrator):
    def signal_handler(sig, frame):
        logger.info("Migration interrupted, saving progress...")
        asyncio.create_task(migrator.save_progress_and_stop())
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
```

---

### 9. Мониторинг и метрики

#### Рекомендации:

**9.1. Детальные метрики**
```python
# Собирать детальные метрики для анализа производительности
metrics = {
    "total_posts": 0,
    "processed_posts": 0,
    "skipped_posts": 0,
    "failed_posts": 0,
    "avg_processing_time": 0,
    "total_media_files": 0,
    "avg_media_download_time": 0,
    "db_query_count": 0,
    "api_request_count": 0,
}
```

**9.2. Логирование производительности**
```python
# Логировать время выполнения операций
@record_operation_time("migration_post_processing")
async def _process_single_post(self, post):
    # Обработка поста
    pass
```

---

### 10. Рекомендуемая архитектура

#### Оптимизированный алгоритм:

```python
async def migrate_link_posts_optimized(self, link_id, progress_callback):
    """Оптимизированный метод переноса"""
    
    # 1. Загрузить кэш уже перенесенных постов (один запрос)
    existing_ids = await self._load_existing_messages_cache(link_id)
    
    # 2. Получить информацию о связи (с кэшированием)
    link_info = await self._get_link_info_cached(link_id)
    
    # 3. Создать semaphore для контроля параллелизма
    semaphore = asyncio.Semaphore(5)  # 5 параллельных запросов
    
    # 4. Потоковая обработка постов
    processed = 0
    success = 0
    skipped = 0
    failed = 0
    
    async for message in self._get_chat_history_stream(link_info.telegram_channel_id):
        processed += 1
        
        # Проверка дублирования (O(1) в памяти)
        if message.id in existing_ids:
            skipped += 1
            continue
        
        # Параллельная обработка с ограничением
        try:
            async with semaphore:
                await self._process_single_post(message, link_id)
            success += 1
            # Добавить в кэш для предотвращения повторной обработки
            existing_ids.add(message.id)
        except Exception as e:
            failed += 1
            logger.error(f"Failed to process post {message.id}: {e}")
        
        # Периодические обновления прогресса
        if processed % 100 == 0:
            await progress_callback(processed, success, skipped, failed)
    
    # 5. Финальная статистика
    return {
        "total": processed,
        "success": success,
        "skipped": skipped,
        "failed": failed
    }
```

---

### 11. Настройки производительности

#### Рекомендуемые параметры:

```python
# В config/settings.py
class Settings:
    # Миграция
    migration_parallel_posts: int = 5  # Параллельно обрабатывать 5 постов
    migration_batch_check_size: int = 1000  # Проверка дублирования батчами по 1000
    migration_progress_update_interval: int = 100  # Обновление прогресса каждые 100 постов
    migration_progress_update_time: int = 300  # Обновление прогресса каждые 5 минут
    migration_memory_limit_mb: int = 500  # Лимит памяти для миграции
    migration_streaming_enabled: bool = True  # Использовать потоковую обработку
```

---

### 12. Итоговые рекомендации по приоритетам

#### Критичные (обязательно):
1. ✅ Батчинг проверки дублирования (сокращение запросов к БД)
2. ✅ Кэширование уже перенесенных постов в памяти
3. ✅ Индексы БД для быстрой проверки дублирования
4. ✅ Батчинг вставок в message_log

#### Важные (сильно улучшат производительность):
5. ✅ Параллельная обработка постов (с semaphore)
6. ✅ Потоковая обработка истории (экономия памяти)
7. ✅ Параллельная загрузка медиафайлов
8. ✅ Периодические обновления прогресса

#### Желательные (оптимизация):
9. ✅ Сохранение прогресса для возобновления
10. ✅ Детальные метрики производительности
11. ✅ Graceful shutdown
12. ✅ Параллельное получение истории по периодам

---

### 13. Оценка производительности

#### Без оптимизаций:
- Канал с 10,000 постов: ~5-10 часов
- 10,000 запросов к БД для проверки дублирования
- Последовательная обработка

#### С оптимизациями:
- Канал с 10,000 постов: ~1-2 часа
- 10 запросов к БД для проверки дублирования (батчинг)
- Параллельная обработка 5 постов одновременно
- Потоковая обработка (меньше памяти)

**Ускорение: 3-5x для типичных каналов, до 10x для больших каналов**




