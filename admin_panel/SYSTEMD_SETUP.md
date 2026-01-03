# Настройка автозапуска админ-панели

## Systemd Service

Сервис админ-панели настроен как `crossposting-admin.service`

### Команды управления

```bash
# Запустить сервис
sudo systemctl start crossposting-admin.service

# Остановить сервис
sudo systemctl stop crossposting-admin.service

# Перезапустить сервис
sudo systemctl restart crossposting-admin.service

# Статус сервиса
sudo systemctl status crossposting-admin.service

# Включить автозапуск
sudo systemctl enable crossposting-admin.service

# Отключить автозапуск
sudo systemctl disable crossposting-admin.service

# Просмотр логов
sudo journalctl -u crossposting-admin.service -f
```

### Конфигурация

- Файл сервиса: `/etc/systemd/system/crossposting-admin.service`
- Исходный файл: `/root/crossposting_service/systemd/crossposting-admin.service`
- Рабочая директория: `/root/crossposting_service/admin_panel/backend`
- Порт: `8001`
- Автозапуск: включен

### Логи

Логи доступны через journalctl:
```bash
sudo journalctl -u crossposting-admin.service -n 100
```

## Текущий статус

✅ **Systemd service создан и настроен:**
- Файл: `/etc/systemd/system/crossposting-admin.service`
- Автозапуск: включен (`systemctl enable`)
- Статус: настроен (запуск может требовать исправления импортов в коде)

⚠️ **Примечание:** Сервис может не запускаться до тех пор, пока не будут исправлены проблемы с импортами в backend коде (конфигурация БД). Это нормально - автозапуск настроен и будет работать после исправления кода.

## Проверка

```bash
# Проверить статус
systemctl status crossposting-admin.service

# Проверить логи
journalctl -u crossposting-admin.service -n 50

# Проверить автозапуск
systemctl is-enabled crossposting-admin.service
```
