#!/bin/bash
# Скрипт для запуска backend админ-панели
cd "$(dirname "$0")"
cd ../..
source venv/bin/activate
export PYTHONPATH="/root/crossposting_service/admin_panel/backend:/root/crossposting_service:$PYTHONPATH"
cd admin_panel/backend
uvicorn main:app --host 0.0.0.0 --port 8001 --reload
