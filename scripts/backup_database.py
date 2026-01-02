#!/usr/bin/env python3
"""Скрипт для автоматического бэкапа базы данных PostgreSQL."""
import asyncio
import os
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional
import subprocess
import shutil

# Добавляем корневую директорию проекта в путь
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from config.settings import settings
from app.utils.logger import setup_logging, get_logger

setup_logging()
logger = get_logger(__name__)

# Настройки бэкапов
BACKUP_DIR = Path("/root/crossposting_service/backups")
BACKUP_RETENTION_DAYS = 7  # Хранить бэкапы 7 дней
BACKUP_COMPRESS = True  # Сжимать бэкапы


def parse_database_url(url: str) -> dict:
    """
    Парсинг database_url для получения параметров подключения.
    
    Формат: postgresql+asyncpg://user:password@host:port/database
    """
    try:
        # Убираем префикс postgresql+asyncpg://
        url = url.replace("postgresql+asyncpg://", "").replace("postgresql://", "")
        
        # Разделяем на части
        if "@" in url:
            auth_part, rest = url.split("@", 1)
            if ":" in auth_part:
                user, password = auth_part.split(":", 1)
            else:
                user = auth_part
                password = ""
        else:
            user = "postgres"
            password = ""
            rest = url
        
        if "/" in rest:
            host_port, database = rest.split("/", 1)
            if ":" in host_port:
                host, port = host_port.split(":")
            else:
                host = host_port
                port = "5432"
        else:
            host = rest.split(":")[0] if ":" in rest else rest
            port = "5432"
            database = "postgres"
        
        return {
            "host": host,
            "port": port,
            "user": user,
            "password": password,
            "database": database
        }
    except Exception as e:
        logger.error("failed_to_parse_database_url", error=str(e))
        raise


async def create_backup() -> Optional[Path]:
    """
    Создать бэкап базы данных.
    
    Returns:
        Путь к созданному файлу бэкапа или None при ошибке
    """
    try:
        # Парсим database_url
        db_params = parse_database_url(settings.database_url)
        
        # Создаем директорию для бэкапов
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        
        # Формируем имя файла бэкапа
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_filename = f"crossposting_backup_{timestamp}.sql"
        backup_path = BACKUP_DIR / backup_filename
        
        # Команда pg_dump
        env = os.environ.copy()
        if db_params["password"]:
            env["PGPASSWORD"] = db_params["password"]
        
        pg_dump_cmd = [
            "pg_dump",
            "-h", db_params["host"],
            "-p", db_params["port"],
            "-U", db_params["user"],
            "-d", db_params["database"],
            "-F", "p",  # Plain text format
            "-f", str(backup_path),
            "--no-owner",  # Не включать команды владельца
            "--no-acl",  # Не включать команды прав доступа
        ]
        
        logger.info("starting_backup", backup_path=str(backup_path))
        
        # Выполняем pg_dump
        result = subprocess.run(
            pg_dump_cmd,
            env=env,
            capture_output=True,
            text=True
        )
        
        if result.returncode != 0:
            logger.error(
                "backup_failed",
                error=result.stderr,
                returncode=result.returncode
            )
            return None
        
        # Проверяем, что файл создан и не пустой
        if not backup_path.exists() or backup_path.stat().st_size == 0:
            logger.error("backup_file_empty_or_missing", backup_path=str(backup_path))
            return None
        
        logger.info(
            "backup_created",
            backup_path=str(backup_path),
            size_mb=round(backup_path.stat().st_size / (1024 * 1024), 2)
        )
        
        # Сжимаем бэкап, если включено
        if BACKUP_COMPRESS:
            compressed_path = backup_path.with_suffix(".sql.gz")
            logger.info("compressing_backup", source=str(backup_path))
            
            result = subprocess.run(
                ["gzip", "-c", str(backup_path)],
                stdout=open(compressed_path, "wb"),
                stderr=subprocess.PIPE
            )
            
            if result.returncode == 0:
                # Удаляем несжатый файл
                backup_path.unlink()
                backup_path = compressed_path
                logger.info(
                    "backup_compressed",
                    backup_path=str(backup_path),
                    size_mb=round(backup_path.stat().st_size / (1024 * 1024), 2)
                )
            else:
                logger.warning("backup_compression_failed", error=result.stderr.decode())
        
        return backup_path
        
    except Exception as e:
        logger.error("backup_error", error=str(e), exc_info=True)
        return None


def cleanup_old_backups():
    """Удалить старые бэкапы (старше BACKUP_RETENTION_DAYS дней)."""
    try:
        if not BACKUP_DIR.exists():
            return
        
        from datetime import timedelta
        cutoff_date = datetime.now() - timedelta(days=BACKUP_RETENTION_DAYS)
        
        deleted_count = 0
        deleted_size = 0
        
        for backup_file in BACKUP_DIR.glob("crossposting_backup_*"):
            try:
                # Получаем дату из имени файла
                # Формат: crossposting_backup_YYYYMMDD_HHMMSS.sql[.gz]
                filename = backup_file.stem  # Убираем .gz если есть
                if filename.endswith(".sql"):
                    filename = filename[:-4]  # Убираем .sql
                
                timestamp_str = filename.replace("crossposting_backup_", "")
                file_date = datetime.strptime(timestamp_str, "%Y%m%d_%H%M%S")
                
                if file_date < cutoff_date:
                    file_size = backup_file.stat().st_size
                    backup_file.unlink()
                    deleted_count += 1
                    deleted_size += file_size
                    logger.info("old_backup_deleted", backup_path=str(backup_file))
            except Exception as e:
                logger.warning("failed_to_delete_old_backup", backup_path=str(backup_file), error=str(e))
        
        if deleted_count > 0:
            logger.info(
                "cleanup_completed",
                deleted_count=deleted_count,
                freed_mb=round(deleted_size / (1024 * 1024), 2)
            )
        else:
            logger.info("no_old_backups_to_cleanup")
            
    except Exception as e:
        logger.error("cleanup_error", error=str(e), exc_info=True)


async def main():
    """Главная функция."""
    logger.info("backup_script_started")
    
    # Создаем бэкап
    backup_path = await create_backup()
    
    if backup_path:
        logger.info("backup_successful", backup_path=str(backup_path))
    else:
        logger.error("backup_failed")
        sys.exit(1)
    
    # Очищаем старые бэкапы
    cleanup_old_backups()
    
    logger.info("backup_script_completed")


if __name__ == "__main__":
    asyncio.run(main())

