"""Простой HTTP сервер для отдачи медиа-файлов."""
import asyncio
import os
from pathlib import Path
from aiohttp import web
from app.utils.logger import get_logger
from config.settings import settings

logger = get_logger(__name__)

MEDIA_STORAGE_PATH = Path(settings.media_storage_path)


async def serve_media_file(request: web.Request) -> web.Response:
    """Отдать медиа-файл по запросу."""
    filename = request.match_info.get('filename')
    if not filename:
        return web.Response(status=404, text="File not found")
    
    file_path = MEDIA_STORAGE_PATH / filename
    
    # Безопасность: проверяем, что файл находится в разрешенной директории
    try:
        file_path.resolve().relative_to(MEDIA_STORAGE_PATH.resolve())
    except ValueError:
        logger.warning("unauthorized_file_access_attempt", filename=filename)
        return web.Response(status=403, text="Forbidden")
    
    if not file_path.exists() or not file_path.is_file():
        logger.debug("file_not_found", filename=filename)
        return web.Response(status=404, text="File not found")
    
    # Определяем MIME тип
    mime_type = "application/octet-stream"
    ext = file_path.suffix.lower()
    mime_map = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".mp4": "video/mp4",
        ".mp3": "audio/mpeg",
        ".ogg": "audio/ogg",
    }
    mime_type = mime_map.get(ext, mime_type)
    
    # Отдаем файл
    return web.Response(
        body=file_path.read_bytes(),
        content_type=mime_type,
        headers={
            "Cache-Control": "public, max-age=3600",
            "X-Content-Type-Options": "nosniff",
        }
    )


def create_media_server_app() -> web.Application:
    """Создать приложение aiohttp для отдачи медиа."""
    app = web.Application()
    app.router.add_get('/media/{filename}', serve_media_file)
    return app


async def run_media_server(host: str = "0.0.0.0", port: int = 8080):
    """Запустить сервер для отдачи медиа-файлов."""
    app = create_media_server_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    logger.info("media_server_started", host=host, port=port)
    return runner


if __name__ == "__main__":
    # Для тестирования
    async def main():
        runner = await run_media_server()
        try:
            await asyncio.Event().wait()
        except KeyboardInterrupt:
            logger.info("media_server_stopping")
        finally:
            await runner.cleanup()
    
    asyncio.run(main())

