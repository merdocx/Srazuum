"""API endpoints."""

from fastapi import APIRouter

api_router = APIRouter()

# Импортируем все роутеры
from app.api import auth, stats, system, users, channels, links, logs

api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(stats.router, prefix="/stats", tags=["stats"])
api_router.include_router(system.router, prefix="/system", tags=["system"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(channels.router, prefix="/channels", tags=["channels"])
api_router.include_router(links.router, prefix="/links", tags=["links"])
api_router.include_router(logs.router, prefix="/logs", tags=["logs"])
