"""Точка входа для админ-панели."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api import api_router
from app.core.config import settings

app = FastAPI(
    title="Srazuum Admin Panel API",
    description="API для админ-панели Srazuum",
    version="1.0.0",
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Подключаем роутеры
app.include_router(api_router, prefix="/api")


@app.get("/")
async def root():
    """Корневой эндпоинт."""
    return {
        "message": "Srazuum Admin Panel API",
        "version": "1.0.0",
        "docs": "/docs"
    }


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
    
    status = {
        "status": "ok",
        "timestamp": datetime.utcnow().isoformat(),
        "checks": {}
    }
    
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
        disk = psutil.disk_usage('/')
        
        status["checks"]["system"] = {
            "status": "ok",
            "cpu_percent": cpu_percent,
            "memory": {
                "percent": memory.percent,
                "available_mb": round(memory.available / (1024 * 1024), 2)
            },
            "disk": {
                "percent": disk.percent,
                "free_gb": round(disk.free / (1024 * 1024 * 1024), 2)
            }
        }
        
        # Предупреждение при высокой нагрузке
        if cpu_percent > 90 or memory.percent > 90 or disk.percent > 90:
            status["status"] = "warning"
    except Exception as e:
        status["checks"]["system"] = {"status": "error", "error": str(e)}
    
    return status


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.admin_panel_host,
        port=settings.admin_panel_port,
        reload=True,
    )

