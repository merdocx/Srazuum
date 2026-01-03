# Настройка автоматических бэкапов и ротации логов

## Обзор

В проекте настроены:
- ✅ Автоматические бэкапы базы данных PostgreSQL
- ✅ Ротация старых бэкапов (хранение 7 дней)
- ✅ Ротация логов systemd journal

---

## Автоматические бэкапы БД

### Описание

Скрипт `scripts/backup_database.py` создает автоматические бэкапы базы данных:
- Формат: SQL dump (plain text)
- Сжатие: gzip (опционально)
- Хранение: 7 дней (настраивается)
- Расписание: ежедневно в 3:00 ночи

### Установка

1. **Запустите скрипт настройки:**
   ```bash
   cd /root/crossposting_service
   sudo ./scripts/setup_backup_and_logs.sh
   ```

2. **Проверьте наличие зависимостей:**
   ```bash
   # Проверка pg_dump
   which pg_dump
   
   # Если не установлен:
   sudo apt-get install postgresql-client
   ```

3. **Запустите таймер:**
   ```bash
   sudo systemctl start crossposting-backup.timer
   sudo systemctl enable crossposting-backup.timer
   ```

4. **Проверьте статус:**
   ```bash
   # Статус таймера
   sudo systemctl status crossposting-backup.timer
   
   # Список таймеров
   sudo systemctl list-timers crossposting-backup.timer
   ```

### Тестовый запуск

```bash
# Запустить бэкап вручную
sudo systemctl start crossposting-backup.service

# Просмотр логов
sudo journalctl -u crossposting-backup.service -f
```

### Настройки

В файле `scripts/backup_database.py` можно изменить:

```python
BACKUP_DIR = Path("/root/crossposting_service/backups")
BACKUP_RETENTION_DAYS = 7  # Хранить бэкапы 7 дней
BACKUP_COMPRESS = True  # Сжимать бэкапы
```

### Расписание

По умолчанию бэкапы запускаются ежедневно в 3:00 ночи.

Для изменения расписания отредактируйте `/etc/systemd/system/crossposting-backup.timer`:

```ini
[Timer]
# Примеры расписания:
OnCalendar=daily                    # Каждый день в 00:00
OnCalendar=*-*-* 03:00:00          # Каждый день в 3:00
OnCalendar=Mon..Fri 02:00:00       # Пн-Пт в 2:00
OnCalendar=*-*-01,15 01:00:00      # 1-го и 15-го числа в 1:00
```

После изменения:
```bash
sudo systemctl daemon-reload
sudo systemctl restart crossposting-backup.timer
```

### Восстановление из бэкапа

```bash
# Распаковать сжатый бэкап (если сжат)
gunzip backups/crossposting_backup_YYYYMMDD_HHMMSS.sql.gz

# Восстановить
psql -h HOST -U USER -d DATABASE < backups/crossposting_backup_YYYYMMDD_HHMMSS.sql
```

---

## Ротация логов systemd journal

### Описание

Логи сервисов сохраняются в systemd journal с автоматической ротацией:
- Максимальный размер: 500MB
- Время хранения: 30 дней
- Сжатие: включено
- Максимальный размер файла: 50MB

### Установка

1. **Скопируйте конфигурацию:**
   ```bash
   sudo mkdir -p /etc/systemd/journald.conf.d
   sudo cp /root/crossposting_service/systemd/journald.conf.d/crossposting.conf \
          /etc/systemd/journald.conf.d/
   ```

2. **Перезапустите systemd-journald:**
   ```bash
   sudo systemctl restart systemd-journald
   ```

3. **Проверьте настройки:**
   ```bash
   sudo journalctl --disk-usage
   ```

### Просмотр логов

```bash
# Логи бота
sudo journalctl -u crossposting-bot.service -f

# Логи MTProto
sudo journalctl -u crossposting-mtproto.service -f

# Логи бэкапов
sudo journalctl -u crossposting-backup.service -f

# Все логи за последний час
sudo journalctl -u crossposting-*.service --since "1 hour ago"

# Логи с фильтрацией по уровню
sudo journalctl -u crossposting-bot.service -p err
```

### Настройки

В файле `/etc/systemd/journald.conf.d/crossposting.conf`:

```ini
[Journal]
SystemMaxUse=500M          # Максимальный размер всех журналов
SystemKeepFree=1G          # Минимальное свободное место
SystemMaxFileSize=50M      # Максимальный размер одного файла
MaxRetentionSec=30day      # Время хранения (30 дней)
MaxFiles=10                # Максимальное количество файлов
Compress=yes               # Сжатие старых файлов
```

### Очистка старых логов вручную

```bash
# Удалить логи старше 7 дней
sudo journalctl --vacuum-time=7d

# Оставить только 100MB логов
sudo journalctl --vacuum-size=100M

# Удалить логи до определенной даты
sudo journalctl --vacuum-time=2025-01-01
```

---

## Мониторинг

### Проверка размера бэкапов

```bash
du -sh /root/crossposting_service/backups
ls -lh /root/crossposting_service/backups
```

### Проверка размера логов

```bash
sudo journalctl --disk-usage
```

### Проверка статуса таймера

```bash
sudo systemctl status crossposting-backup.timer
sudo systemctl list-timers crossposting-backup.timer
```

---

## Устранение неполадок

### Бэкап не создается

1. Проверьте логи:
   ```bash
   sudo journalctl -u crossposting-backup.service -n 50
   ```

2. Проверьте права доступа:
   ```bash
   ls -la /root/crossposting_service/backups
   ```

3. Проверьте подключение к БД:
   ```bash
   psql -h HOST -U USER -d DATABASE -c "SELECT 1;"
   ```

### Логи не ротируются

1. Проверьте конфигурацию:
   ```bash
   cat /etc/systemd/journald.conf.d/crossposting.conf
   ```

2. Перезапустите journald:
   ```bash
   sudo systemctl restart systemd-journald
   ```

3. Проверьте статус:
   ```bash
   sudo systemctl status systemd-journald
   ```

---

## Рекомендации

1. **Регулярно проверяйте бэкапы:**
   - Убедитесь, что бэкапы создаются
   - Проверяйте размер файлов (не должны быть пустыми)
   - Тестируйте восстановление из бэкапа

2. **Мониторинг дискового пространства:**
   - Бэкапы: ~100-500MB в день (зависит от размера БД)
   - Логи: до 500MB (настраивается)

3. **Хранение бэкапов вне сервера:**
   - Рекомендуется копировать бэкапы на внешний сервер
   - Используйте rsync, scp или облачное хранилище

4. **Уведомления:**
   - Настройте уведомления при ошибках бэкапа
   - Мониторьте размер диска

---

## Дополнительные ресурсы

- [systemd.timer документация](https://www.freedesktop.org/software/systemd/man/systemd.timer.html)
- [journald.conf документация](https://www.freedesktop.org/software/systemd/man/journald.conf.html)
- [pg_dump документация](https://www.postgresql.org/docs/current/app-pgdump.html)



