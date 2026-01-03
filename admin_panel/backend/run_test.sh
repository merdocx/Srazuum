#!/bin/bash
export PYTHONPATH="/root/crossposting_service:/root/crossposting_service/admin_panel/backend"
cd /root/crossposting_service/admin_panel/backend
/root/crossposting_service/venv/bin/uvicorn main:app --host 0.0.0.0 --port 8001
