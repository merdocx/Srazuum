"""Обработчик медиа-файлов из Telegram."""
import asyncio
import os
import uuid
from pathlib import Path
from typing import Optional, Dict, Any, Tuple
from datetime import datetime, timedelta
from pyrogram.types import Message
from pyrogram import Client
from app.utils.logger import get_logger
from app.utils.exceptions import MediaProcessingError
from config.settings import settings

logger = get_logger(__name__)

# Создаем директорию для медиа, если её нет
MEDIA_STORAGE_PATH = Path(settings.media_storage_path)
MEDIA_STORAGE_PATH.mkdir(parents=True, exist_ok=True)


async def download_and_store_media(
    client: Client,
    message: Message,
    file_type: str
) -> Tuple[Optional[str], Optional[str]]:
    """
    Скачать медиа-файл из Telegram и сохранить на сервере.
    
    Args:
        client: Pyrogram клиент
        message: Сообщение с медиа
        file_type: Тип файла (photo, video, document, audio, voice, sticker)
    
    Returns:
        Кортеж (публичный URL файла, локальный путь к файлу) или (None, None)
    """
    try:
        # Определяем медиа-объект
        media_obj = None
        if file_type == "photo" and message.photo:
            media_obj = message.photo
        elif file_type == "video" and message.video:
            media_obj = message.video
        elif file_type == "document" and message.document:
            media_obj = message.document
        elif file_type == "audio" and message.audio:
            media_obj = message.audio
        elif file_type == "voice" and message.voice:
            media_obj = message.voice
        elif file_type == "sticker" and message.sticker:
            media_obj = message.sticker
        
        if not media_obj:
            return None, None
        
        # Генерируем уникальное имя файла
        file_id = getattr(media_obj, 'file_id', str(uuid.uuid4()))
        file_ext = getattr(media_obj, 'file_name', '').split('.')[-1] if hasattr(media_obj, 'file_name') else 'jpg'
        if not file_ext or file_ext == file_id:
            # Определяем расширение по типу
            ext_map = {
                "photo": "jpg",
                "video": "mp4",
                "document": "bin",
                "audio": "mp3",
                "voice": "ogg",
                "sticker": "webp"
            }
            file_ext = ext_map.get(file_type, "bin")
        
        # Создаем уникальное имя файла
        unique_filename = f"{uuid.uuid4().hex}.{file_ext}"
        local_file_path = MEDIA_STORAGE_PATH / unique_filename
        
        # Скачиваем файл
        logger.info("downloading_media", file_type=file_type, file_id=file_id[:20])
        downloaded_path = await client.download_media(media_obj, file_name=str(local_file_path))
        
        if not downloaded_path or not os.path.exists(downloaded_path):
            logger.error("media_download_failed", file_type=file_type)
            return None, None
        
        # Устанавливаем права для чтения nginx (644 = rw-r--r--)
        os.chmod(downloaded_path, 0o644)
        
        # Проверяем размер файла
        file_size = os.path.getsize(downloaded_path) / (1024 * 1024)  # MB
        if file_size > settings.media_max_file_size_mb:
            logger.warning("media_file_too_large", file_type=file_type, size_mb=file_size)
            os.remove(downloaded_path)
            return None, None
        
        # Формируем публичный URL
        public_url = f"{settings.media_public_url}/{unique_filename}"
        
        logger.info(
            "media_stored",
            file_type=file_type,
            file_path=str(downloaded_path),
            public_url=public_url,
            size_mb=round(file_size, 2)
        )
        
        return public_url, str(downloaded_path)
    
    except Exception as e:
        logger.error("media_download_error", file_type=file_type, error=str(e))
        raise MediaProcessingError(f"Ошибка загрузки {file_type}: {e}")


async def delete_media_file(public_url: str) -> bool:
    """
    Удалить медиа-файл по публичному URL.
    
    Args:
        public_url: Публичный URL файла
    
    Returns:
        True если файл удален, False в противном случае
    """
    try:
        # Извлекаем имя файла из URL
        filename = public_url.split('/')[-1]
        file_path = MEDIA_STORAGE_PATH / filename
        
        if file_path.exists():
            os.remove(file_path)
            logger.info("media_deleted", file_path=str(file_path))
            return True
        else:
            logger.warning("media_file_not_found", file_path=str(file_path))
            return False
    
    except Exception as e:
        logger.error("media_delete_error", public_url=public_url, error=str(e))
        return False


async def cleanup_old_media_files(max_age_hours: int = 24) -> int:
    """
    Удалить старые медиа-файлы.
    
    Args:
        max_age_hours: Максимальный возраст файла в часах
    
    Returns:
        Количество удаленных файлов
    """
    try:
        deleted_count = 0
        cutoff_time = datetime.now() - timedelta(hours=max_age_hours)
        
        for file_path in MEDIA_STORAGE_PATH.iterdir():
            if file_path.is_file():
                file_mtime = datetime.fromtimestamp(file_path.stat().st_mtime)
                if file_mtime < cutoff_time:
                    try:
                        file_path.unlink()
                        deleted_count += 1
                        logger.debug("old_media_deleted", file_path=str(file_path))
                    except Exception as e:
                        logger.warning("failed_to_delete_old_media", file_path=str(file_path), error=str(e))
        
        if deleted_count > 0:
            logger.info("cleanup_completed", deleted_count=deleted_count)
        
        return deleted_count
    
    except Exception as e:
        logger.error("cleanup_error", error=str(e))
        return 0


async def get_media_url(
    client: Client,
    message: Message
) -> Optional[str]:
    """
    Получить публичный URL медиа-файла.
    Скачивает файл из Telegram и сохраняет на сервере.
    
    Args:
        client: Pyrogram клиент
        message: Сообщение с медиа
    
    Returns:
        Публичный URL файла или None
    """
    try:
        if message.photo:
            public_url, _ = await download_and_store_media(client, message, "photo")
            return public_url
        elif message.video:
            public_url, _ = await download_and_store_media(client, message, "video")
            return public_url
        elif message.document:
            public_url, _ = await download_and_store_media(client, message, "document")
            return public_url
        elif message.audio:
            public_url, _ = await download_and_store_media(client, message, "audio")
            return public_url
        elif message.voice:
            public_url, _ = await download_and_store_media(client, message, "voice")
            return public_url
        elif message.sticker:
            public_url, _ = await download_and_store_media(client, message, "sticker")
            return public_url
        
        return None
    
    except Exception as e:
        logger.error("media_url_error", error=str(e))
        return None

