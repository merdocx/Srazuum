"""Авторизация MTProto с использованием session string."""
import asyncio
import sys
from pathlib import Path
from pyrogram import Client
from config.settings import settings
from app.utils.logger import setup_logging, get_logger

setup_logging()
logger = get_logger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent.parent
SESSION_STRING_FILE = PROJECT_ROOT / "session_string.txt"


async def authorize_with_session_string(session_string: str = None):
    """
    Авторизация с использованием session string.
    
    Args:
        session_string: Session string из Telegram Desktop (опционально)
    """
    print("=" * 60)
    print("Авторизация MTProto с использованием session string")
    print("=" * 60)
    
    # Если session string не передан, пытаемся прочитать из файла
    if not session_string:
        if SESSION_STRING_FILE.exists():
            print(f"\n📄 Чтение session string из файла: {SESSION_STRING_FILE}")
            with open(SESSION_STRING_FILE, "r") as f:
                session_string = f.read().strip()
            print("✅ Session string прочитан из файла")
        else:
            print("\n❌ Session string не найден!")
            print("\nДля получения session string:")
            print("1. Установите Telegram Desktop")
            print("2. Авторизуйтесь в Telegram Desktop")
            print("3. Используйте скрипт для экспорта session string")
            print("   Или используйте интерактивную авторизацию")
            return False
    
    if not session_string:
        print("\n❌ Session string пуст!")
        return False
    
    print(f"\n📱 Номер телефона: {settings.telegram_phone}")
    print(f"🔑 API ID: {settings.telegram_api_id}")
    print("\n🔐 Подключение с использованием session string...")
    
    try:
        # Создаем клиент с session string
        client = Client(
            "crossposting_session",
            api_id=settings.telegram_api_id_int,
            api_hash=settings.telegram_api_hash,
            session_string=session_string
        )
        
        await client.start()
        
        # Проверяем авторизацию
        me = await client.get_me()
        print(f"\n✅ Авторизация успешна!")
        print(f"   Имя: {me.first_name}")
        print(f"   Фамилия: {me.last_name or 'нет'}")
        print(f"   Username: @{me.username or 'нет'}")
        print(f"   ID: {me.id}")
        print(f"   Телефон: {me.phone_number or 'нет'}")
        
        await client.stop()
        print("\n✅ Сессия сохранена в файл: crossposting_session.session")
        return True
        
    except Exception as e:
        logger.error(f"Ошибка авторизации: {e}")
        print(f"\n❌ Ошибка авторизации: {e}")
        print("\nВозможные причины:")
        print("1. Session string недействителен или истек")
        print("2. Неверные API credentials")
        print("3. Сессия была отозвана")
        print("\nПопробуйте:")
        print("- Получить новый session string")
        print("- Использовать интерактивную авторизацию")
        return False


async def export_session_string():
    """
    Экспорт session string из существующей сессии.
    Используется, если сессия уже создана через интерактивную авторизацию.
    """
    print("=" * 60)
    print("Экспорт session string из существующей сессии")
    print("=" * 60)
    
    session_file = PROJECT_ROOT / "crossposting_session.session"
    
    if not session_file.exists():
        print(f"\n❌ Файл сессии не найден: {session_file}")
        print("\nСначала нужно создать сессию через интерактивную авторизацию")
        return None
    
    try:
        client = Client(
            "crossposting_session",
            api_id=settings.telegram_api_id_int,
            api_hash=settings.telegram_api_hash
        )
        
        await client.start()
        
        # Получаем session string
        session_string = await client.export_session_string()
        
        # Сохраняем в файл
        with open(SESSION_STRING_FILE, "w") as f:
            f.write(session_string)
        
        print(f"\n✅ Session string экспортирован!")
        print(f"   Сохранен в: {SESSION_STRING_FILE}")
        print(f"\n📋 Session string (первые 50 символов):")
        print(f"   {session_string[:50]}...")
        
        await client.stop()
        return session_string
        
    except Exception as e:
        logger.error(f"Ошибка экспорта session string: {e}")
        print(f"\n❌ Ошибка экспорта: {e}")
        return None


if __name__ == "__main__":
    if len(sys.argv) > 1:
        command = sys.argv[1]
        
        if command == "export":
            # Экспорт session string из существующей сессии
            asyncio.run(export_session_string())
        elif command == "auth":
            # Авторизация с session string
            session_string = sys.argv[2] if len(sys.argv) > 2 else None
            asyncio.run(authorize_with_session_string(session_string))
        else:
            print("Использование:")
            print("  python -m app.mtproto.auth_with_session_string export  # Экспорт session string")
            print("  python -m app.mtproto.auth_with_session_string auth [session_string]  # Авторизация")
    else:
        print("Использование:")
        print("  python -m app.mtproto.auth_with_session_string export  # Экспорт session string")
        print("  python -m app.mtproto.auth_with_session_string auth [session_string]  # Авторизация")






