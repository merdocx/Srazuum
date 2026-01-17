"""Точка входа для админ-панели."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from prometheus_fastapi_instrumentator import Instrumentator
from app.api import api_router
from app.core.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Инициализация rate limiter
limiter = Limiter(key_func=get_remote_address)

# Проверка обязательных настроек при старте
if not settings.secret_key or len(settings.secret_key) < 32:
    raise ValueError(
        "SECRET_KEY must be set in .env file and be at least 32 characters long. "
        "Generate a secure random string for production."
    )

app = FastAPI(
    title="Srazuum Admin Panel API",
    description="API для админ-панели Srazuum",
    version="1.5.4",
)

# Подключаем rate limiter к приложению
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "Accept"],
)

# Mount static files for legal documents (before routers to avoid conflicts)
app.mount("/docs", StaticFiles(directory="/var/www/docs", html=True), name="docs")

# Подключаем роутеры
app.include_router(api_router, prefix="/api")

# Mount static files for frontend (must be AFTER all routers to avoid conflicts)
import os
from pathlib import Path
frontend_dist_path = Path(__file__).parent.parent.parent / "admin_panel" / "frontend" / "dist"
if frontend_dist_path.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dist_path), html=True), name="frontend")

# Настраиваем экспорт метрик Prometheus
instrumentator = Instrumentator(
    should_group_status_codes=False,
    should_ignore_untemplated=True,
    should_instrument_requests_inprogress=True,
    excluded_handlers=["/metrics", "/health", "/health/detailed"],
    inprogress_name="http_requests_inprogress",
    inprogress_labels=True,
)
instrumentator.instrument(app).expose(app, endpoint="/metrics")


@app.get("/")
async def root():
    """Корневой эндпоинт."""
    return {"message": "Srazuum Admin Panel API", "version": "1.5.3", "docs": "/docs"}


@app.get("/health")
async def health():
    """Health check - базовая проверка."""
    return {"status": "ok"}


@app.get("/health/detailed")
async def health_detailed():
    """Детальный health check с проверкой БД и системных ресурсов."""
    from datetime import datetime
    from app.core.database import engine
    from sqlalchemy import text
    import psutil

    status = {"status": "ok", "timestamp": datetime.utcnow().isoformat(), "checks": {}}

    # Проверка базы данных
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        status["checks"]["database"] = {"status": "ok"}
    except Exception as e:
        status["status"] = "degraded"
        status["checks"]["database"] = {"status": "error", "error": str(e)}

    # Проверка системных ресурсов
    try:
        cpu_percent = psutil.cpu_percent(interval=0.1)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage("/")

        status["checks"]["system"] = {
            "status": "ok",
            "cpu_percent": cpu_percent,
            "memory": {"percent": memory.percent, "available_mb": round(memory.available / (1024 * 1024), 2)},
            "disk": {"percent": disk.percent, "free_gb": round(disk.free / (1024 * 1024 * 1024), 2)},
        }

        # Предупреждение при высокой нагрузке
        if cpu_percent > 90 or memory.percent > 90 or disk.percent > 90:
            status["status"] = "warning"
    except Exception as e:
        status["checks"]["system"] = {"status": "error", "error": str(e)}

    return status


# Настройка планировщика задач для синхронизации платежей
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from app.tasks.payment_sync import sync_all_payments

scheduler = AsyncIOScheduler()

# Запускаем синхронизацию платежей каждый час
scheduler.add_job(
    sync_all_payments,
    trigger=CronTrigger(minute=0),  # Каждый час в 0 минут
    id="sync_payments",
    name="Синхронизация статусов платежей с YooKassa",
    replace_existing=True,
)


@app.on_event("startup")
async def startup_event():
    """События при запуске приложения."""
    logger.info("admin_panel_startup: starting scheduler")
    scheduler.start()
    logger.info("admin_panel_startup: scheduler started")


@app.on_event("shutdown")
async def shutdown_event():
    """События при остановке приложения."""
    logger.info("admin_panel_shutdown: stopping scheduler")
    scheduler.shutdown()
    logger.info("admin_panel_shutdown: scheduler stopped")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=settings.admin_panel_host,
        port=settings.admin_panel_port,
        reload=True,
    )
