#!/usr/bin/env python3
"""Скрипт для получения списка всех доступных чатов MAX."""
import asyncio
import json
import sys
from pathlib import Path

# Добавляем корневую директорию проекта в путь
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.max_api.client import MaxAPIClient
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def list_all_chats():
    """Получить и вывести список всех доступных чатов."""
    max_client = MaxAPIClient()
    
    try:
        print("\n" + "="*80)
        print("СПИСОК ВСЕХ ДОСТУПНЫХ ЧАТОВ MAX")
        print("="*80 + "\n")
        
        chats = await max_client.get_available_chats()
        
        print(f"Всего доступно чатов: {len(chats)}\n")
        
        if not chats:
            print("❌ Список чатов пуст. Убедитесь, что бот добавлен в каналы как администратор.")
            return
        
        for idx, chat in enumerate(chats, 1):
            print(f"\n{'─'*80}")
            print(f"ЧАТ #{idx}")
            print(f"{'─'*80}")
            
            # Выводим все поля чата
            print("\n📋 Полная структура данных:")
            print(json.dumps(chat, indent=2, ensure_ascii=False))
            
            # Выводим основные поля в читаемом виде
            print("\n📝 Основная информация:")
            if 'id' in chat:
                print(f"  ID: {chat['id']}")
            if 'chat_id' in chat:
                print(f"  Chat ID: {chat['chat_id']}")
            if 'title' in chat:
                print(f"  Название: {chat['title']}")
            if 'name' in chat:
                print(f"  Имя: {chat['name']}")
            if 'username' in chat:
                print(f"  Username: {chat['username']}")
            if 'slug' in chat:
                print(f"  Slug: {chat['slug']}")
            if 'type' in chat:
                print(f"  Тип: {chat['type']}")
            
            # Выводим все ключи для справки
            print(f"\n🔑 Все доступные ключи: {', '.join(chat.keys())}")
        
        print("\n" + "="*80)
        print("КОНЕЦ СПИСКА")
        print("="*80 + "\n")
        
    except Exception as e:
        print(f"\n❌ Ошибка при получении списка чатов: {e}")
        logger.error("failed_to_list_chats", error=str(e), exc_info=True)
    finally:
        await max_client.close()


if __name__ == "__main__":
    asyncio.run(list_all_chats())







