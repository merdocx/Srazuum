#!/bin/bash
# Скрипт для настройки автоматического мониторинга безопасности

set -e

PROJECT_ROOT="/root/crossposting_service"
SCRIPT_PATH="$PROJECT_ROOT/scripts/security_monitor.py"
SYSTEMD_DIR="$PROJECT_ROOT/systemd"

echo "Настройка мониторинга безопасности..."
echo ""

# Создаем systemd сервис для мониторинга безопасности
cat > "$SYSTEMD_DIR/crossposting-security-monitor.service" << 'EOF'
[Unit]
Description=Crossposting Service - Security Monitor
After=network.target

[Service]
Type=oneshot
User=root
WorkingDirectory=/root/crossposting_service
Environment="PATH=/root/crossposting_service/venv/bin:/usr/local/bin:/usr/bin:/bin"
ExecStart=/usr/bin/python3 /root/crossposting_service/scripts/security_monitor.py
StandardOutput=journal
StandardError=journal
SyslogIdentifier=crossposting-security-monitor

[Install]
WantedBy=multi-user.target
EOF

# Создаем systemd timer для запуска мониторинга каждые 6 часов
cat > "$SYSTEMD_DIR/crossposting-security-monitor.timer" << 'EOF'
[Unit]
Description=Crossposting Service - Security Monitor Timer
Requires=crossposting-security-monitor.service

[Timer]
OnBootSec=10min
OnUnitActiveSec=6h
AccuracySec=1min

[Install]
WantedBy=timers.target
EOF

echo "✅ Systemd сервис и timer созданы:"
echo "   - $SYSTEMD_DIR/crossposting-security-monitor.service"
echo "   - $SYSTEMD_DIR/crossposting-security-monitor.timer"
echo ""

# Копируем файлы в systemd
if [ -d "/etc/systemd/system" ]; then
    cp "$SYSTEMD_DIR/crossposting-security-monitor.service" /etc/systemd/system/
    cp "$SYSTEMD_DIR/crossposting-security-monitor.timer" /etc/systemd/system/
    systemctl daemon-reload
    echo "✅ Файлы скопированы в /etc/systemd/system/"
    echo ""
    
    # Предлагаем включить и запустить
    echo "Для активации мониторинга безопасности выполните:"
    echo "   sudo systemctl enable crossposting-security-monitor.timer"
    echo "   sudo systemctl start crossposting-security-monitor.timer"
    echo "   sudo systemctl status crossposting-security-monitor.timer"
    echo ""
    echo "Мониторинг будет запускаться автоматически каждые 6 часов."
else
    echo "⚠️  /etc/systemd/system не найден. Установите файлы вручную."
fi

echo ""
echo "Готово!"
