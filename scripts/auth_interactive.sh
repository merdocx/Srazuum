#!/bin/bash
# Интерактивная авторизация MTProto
# Запустите этот скрипт в терминале для авторизации

cd "$(dirname "$0")/.." || exit 1

# Получаем номер телефона из .env файла
TELEGRAM_PHONE=$(grep "^TELEGRAM_PHONE=" .env 2>/dev/null | cut -d'=' -f2 | tr -d '"' | tr -d "'")

echo "=========================================="
echo "Интерактивная авторизация MTProto"
echo "=========================================="
echo ""
echo "Этот скрипт запросит код подтверждения"
echo "и будет ждать ввода в том же процессе."
echo ""

if [ -n "$TELEGRAM_PHONE" ]; then
    echo "Номер телефона: $TELEGRAM_PHONE"
else
    echo "Номер телефона: (из настроек .env)"
fi

echo ""
echo "Нажмите Enter для продолжения..."
read -r

source venv/bin/activate
python -m app.mtproto.auth_interactive
