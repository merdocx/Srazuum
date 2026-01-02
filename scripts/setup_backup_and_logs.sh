#!/bin/bash
# Скрипт для настройки автоматических бэкапов и ротации логов

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SYSTEMD_DIR="$PROJECT_ROOT/systemd"

echo "============================================================"
echo "Настройка автоматических бэкапов и ротации логов"
echo "============================================================"

# 1. Создаем директорию для бэкапов
echo "1. Создание директории для бэкапов..."
mkdir -p "$PROJECT_ROOT/backups"
chmod 700 "$PROJECT_ROOT/backups"
echo "   ✅ Директория создана: $PROJECT_ROOT/backups"

# 2. Копируем systemd сервисы и таймер
echo "2. Установка systemd сервисов..."
if [ -f "$SYSTEMD_DIR/crossposting-backup.service" ]; then
    cp "$SYSTEMD_DIR/crossposting-backup.service" /etc/systemd/system/
    cp "$SYSTEMD_DIR/crossposting-backup.timer" /etc/systemd/system/
    systemctl daemon-reload
    systemctl enable crossposting-backup.timer
    echo "   ✅ Сервисы установлены и включены"
else
    echo "   ⚠️  Файлы сервисов не найдены"
fi

# 3. Настраиваем ротацию systemd journal
echo "3. Настройка ротации systemd journal..."
JOURNALD_CONF_DIR="/etc/systemd/journald.conf.d"
mkdir -p "$JOURNALD_CONF_DIR"

if [ -f "$SYSTEMD_DIR/journald.conf.d/crossposting.conf" ]; then
    cp "$SYSTEMD_DIR/journald.conf.d/crossposting.conf" "$JOURNALD_CONF_DIR/"
    echo "   ✅ Конфигурация journald скопирована"
    echo "   ⚠️  Перезапустите systemd-journald для применения настроек:"
    echo "      sudo systemctl restart systemd-journald"
else
    echo "   ⚠️  Файл конфигурации journald не найден"
fi

# 4. Проверяем наличие pg_dump
echo "4. Проверка наличия pg_dump..."
if command -v pg_dump &> /dev/null; then
    echo "   ✅ pg_dump установлен: $(which pg_dump)"
else
    echo "   ❌ pg_dump не найден. Установите postgresql-client:"
    echo "      sudo apt-get install postgresql-client"
fi

# 5. Проверяем наличие gzip
echo "5. Проверка наличия gzip..."
if command -v gzip &> /dev/null; then
    echo "   ✅ gzip установлен: $(which gzip)"
else
    echo "   ❌ gzip не найден. Установите gzip:"
    echo "      sudo apt-get install gzip"
fi

echo ""
echo "============================================================"
echo "Настройка завершена!"
echo "============================================================"
echo ""
echo "Следующие шаги:"
echo "1. Перезапустите systemd-journald:"
echo "   sudo systemctl restart systemd-journald"
echo ""
echo "2. Запустите таймер бэкапов:"
echo "   sudo systemctl start crossposting-backup.timer"
echo ""
echo "3. Проверьте статус таймера:"
echo "   sudo systemctl status crossposting-backup.timer"
echo ""
echo "4. Проверьте список таймеров:"
echo "   sudo systemctl list-timers crossposting-backup.timer"
echo ""
echo "5. Запустите тестовый бэкап:"
echo "   sudo systemctl start crossposting-backup.service"
echo "   sudo journalctl -u crossposting-backup.service -f"
echo ""

