"""API для системной информации."""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
import subprocess
import psutil

from app.core.database import get_db
from app.api.auth import get_current_admin
from app.models.admin import Admin

router = APIRouter()


@router.get("/status")
async def get_system_status(
    current_admin: Admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """Получить статус системных сервисов."""
    services = [
        "crossposting-bot.service",
        "crossposting-mtproto.service",
        "crossposting-backup.service",
        "crossposting-backup.timer",
    ]
    
    service_status = {}
    for service in services:
        try:
            # Используем systemctl list-units для более точной проверки активных сервисов
            list_result = subprocess.run(
                ["systemctl", "list-units", "--type=service", f"{service}"],
                capture_output=True,
                text=True,
                timeout=2
            )
            
            # Если сервис в списке активных - он active, иначе проверяем детали
            is_listed_active = service in list_result.stdout and "active" in list_result.stdout
            
            # Получаем детальную информацию
            show_result = subprocess.run(
                ["systemctl", "show", service, "--property=ActiveState,SubState,LoadState"],
                capture_output=True,
                text=True,
                timeout=2
            )
            
            active_state = "unknown"
            sub_state = ""
            load_state = "unknown"
            
            if show_result.returncode == 0:
                for line in show_result.stdout.strip().split('\n'):
                    if line.startswith('ActiveState='):
                        active_state = line.split('=', 1)[1]
                    elif line.startswith('SubState='):
                        sub_state = line.split('=', 1)[1]
                    elif line.startswith('LoadState='):
                        load_state = line.split('=', 1)[1]
            
            # Определяем статус для отображения
            if service == "crossposting-backup.service":
                # Для oneshot сервисов проверяем активность timer'а
                timer_result = subprocess.run(
                    ["systemctl", "is-active", "crossposting-backup.timer"],
                    capture_output=True,
                    text=True,
                    timeout=2
                )
                timer_active = timer_result.stdout.strip() == "active"
                display_status = "active" if timer_active else "inactive"
                is_active = timer_active
            else:
                # Для обычных сервисов: если в списке active или ActiveState=active - active
                if is_listed_active or active_state == "active":
                    display_status = "active"
                    is_active = True
                elif active_state == "activating":
                    display_status = "activating"
                    is_active = False
                elif active_state == "failed":
                    display_status = "failed"
                    is_active = False
                else:
                    display_status = active_state if active_state else "inactive"
                    is_active = False
            
            service_status[service] = {
                "status": display_status,
                "active": is_active,
                "active_state": active_state,
                "sub_state": sub_state,
                "load_state": load_state
            }
        except Exception as e:
            service_status[service] = {
                "status": "unknown",
                "active": False,
                "error": str(e)
            }
    
    # Проверка БД
    db_status = "unknown"
    try:
        from sqlalchemy import text
        await db.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception:
        db_status = "disconnected"
    
    # Системные метрики
    cpu_percent = psutil.cpu_percent(interval=0.1)
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    
    return {
        "services": service_status,
        "database": {
            "status": db_status
        },
        "system": {
            "cpu_percent": cpu_percent,
            "memory": {
                "total": memory.total,
                "used": memory.used,
                "percent": memory.percent
            },
            "disk": {
                "total": disk.total,
                "used": disk.used,
                "percent": disk.percent
            }
        }
    }
