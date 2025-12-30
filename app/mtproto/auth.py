"""Простой скрипт авторизации MTProto по шагам."""
import asyncio
import sys
import os
from pathlib import Path
from pyrogram import Client
from config.settings import settings
from app.utils.logger import setup_logging

setup_logging()

# Путь к файлу phone_code_hash (в корне проекта)
PROJECT_ROOT = Path(__file__).parent.parent.parent
PHONE_CODE_HASH_FILE = PROJECT_ROOT / "phone_code_hash.txt"


async def step1_request_code():
    """Шаг 1: Запрос кода подтверждения."""
    print("=" * 60)
    print("ШАГ 1: Запрос кода подтверждения")
    print("=" * 60)
    print(f"\nНомер телефона: {settings.telegram_phone}")
    print(f"API ID: {settings.telegram_api_id}")
    print("\nПодключение к Telegram...")
    
    client = Client(
        "crossposting_session",
        api_id=settings.telegram_api_id_int,
        api_hash=settings.telegram_api_hash,
        phone_number=settings.telegram_phone
    )
    
    try:
        await client.connect()
        print("✅ Подключено к Telegram")
        
        print("\n📱 Запрос кода подтверждения...")
        print(f"   Номер телефона: {settings.telegram_phone}")
        print(f"   API ID: {settings.telegram_api_id}")
        
        try:
            sent_code = await client.send_code(settings.telegram_phone)
            
            print("✅ Код подтверждения отправлен!")
            print(f"   Способ доставки: {sent_code.type}")
            print(f"   Номер телефона: {settings.telegram_phone}")
            
            # Дополнительная информация о способе доставки
            if hasattr(sent_code.type, 'pattern'):
                print(f"   Паттерн SMS: {sent_code.type.pattern}")
            if hasattr(sent_code.type, 'length'):
                print(f"   Длина кода: {sent_code.type.length}")
                
        except Exception as e:
            error_str = str(e)
            print(f"\n❌ Ошибка при запросе кода: {error_str}")
            
            # Детальная диагностика ошибки
            if "PHONE_NUMBER_INVALID" in error_str:
                print("\n⚠️  Неверный номер телефона")
                print(f"   Проверьте формат: {settings.telegram_phone}")
                print("   Формат должен быть: +79991234567 (с кодом страны и знаком +)")
            elif "PHONE_NUMBER_FLOOD" in error_str:
                print("\n⚠️  Слишком частые запросы для этого номера")
                print("   Подождите некоторое время")
            elif "PHONE_NUMBER_BANNED" in error_str:
                print("\n⚠️  Номер телефона заблокирован")
            elif "FLOOD_WAIT" in error_str:
                import re
                wait_match = re.search(r'FLOOD_WAIT_(\d+)', error_str)
                if wait_match:
                    wait_seconds = int(wait_match.group(1))
                    wait_minutes = wait_seconds // 60
                    print(f"\n⚠️  Блокировка: подождите {wait_minutes} минут")
            else:
                print(f"\n⚠️  Неизвестная ошибка: {error_str}")
            
            raise
        
        # Сохраняем phone_code_hash для следующего шага
        print(f"\n💾 Сохранение phone_code_hash: {PHONE_CODE_HASH_FILE}")
        with open(PHONE_CODE_HASH_FILE, "w") as f:
            f.write(sent_code.phone_code_hash)
        print(f"✅ phone_code_hash сохранен: {sent_code.phone_code_hash[:10]}...")
        
        print("\n" + "=" * 60)
        print("⏳ Ожидание кода от пользователя...")
        print("=" * 60)
        print("\nПроверьте Telegram или SMS на номере", settings.telegram_phone)
        print("Когда получите код, выполните:")
        print("  python -m app.mtproto.auth <код>")
        
        await client.disconnect()
        return True
        
    except Exception as e:
        error_str = str(e)
        print(f"\n❌ Ошибка: {error_str}")
        
        if "FLOOD_WAIT" in error_str:
            import re
            wait_match = re.search(r'FLOOD_WAIT_(\d+)', error_str)
            if wait_match:
                wait_seconds = int(wait_match.group(1))
                wait_minutes = wait_seconds // 60
                wait_hours = wait_minutes // 60
                print(f"\n⚠️  Слишком частые запросы")
                if wait_hours > 0:
                    print(f"Подождите {wait_hours} часов {wait_minutes % 60} минут")
                elif wait_minutes > 0:
                    print(f"Подождите {wait_minutes} минут")
                else:
                    print(f"Подождите {wait_seconds} секунд")
        
        await client.disconnect()
        return False


async def step2_use_code(code):
    """Шаг 2: Использование кода для авторизации."""
    print("=" * 60)
    print("ШАГ 2: Авторизация с кодом")
    print("=" * 60)
    print(f"\nНомер телефона: {settings.telegram_phone}")
    print(f"Код: {code}")
    
    # Загружаем phone_code_hash
    print(f"\n📂 Загрузка phone_code_hash из: {PHONE_CODE_HASH_FILE}")
    try:
        with open(PHONE_CODE_HASH_FILE, "r") as f:
            phone_code_hash = f.read().strip()
        print(f"✅ phone_code_hash загружен: {phone_code_hash[:10]}...")
    except FileNotFoundError:
        print(f"\n❌ Ошибка: phone_code_hash не найден в {PHONE_CODE_HASH_FILE}")
        print("💡 Сначала выполните ШАГ 1:")
        print("   python -m app.mtproto.auth")
        return False
    
    client = Client(
        "crossposting_session",
        api_id=settings.telegram_api_id_int,
        api_hash=settings.telegram_api_hash,
        phone_number=settings.telegram_phone
    )
    
    try:
        await client.connect()
        print("✅ Подключено к Telegram")
        
        print(f"\n📝 Использование кода: {code}")
        print("Авторизация...")
        
        # Авторизуемся с кодом
        try:
            print(f"🔐 Попытка авторизации с кодом {code} и hash {phone_code_hash[:10]}...")
            await client.sign_in(settings.telegram_phone, phone_code_hash, code)
            print("✅ Код принят!")
        except Exception as e:
            error_str = str(e)
            print(f"\n🔍 Детали ошибки: {error_str}")
            if "PASSWORD" in error_str or "2FA" in error_str:
                print("\n⚠️  Требуется пароль двухфакторной аутентификации")
                password = input("Введите пароль 2FA: ")
                await client.check_password(password)
                print("✅ Пароль принят!")
            elif "PHONE_CODE_INVALID" in error_str:
                print("\n❌ Код неверный")
                print("💡 Проверьте правильность кода и запросите новый:")
                print("   python -m app.mtproto.auth")
                await client.disconnect()
                return False
            elif "PHONE_CODE_EXPIRED" in error_str:
                print("\n❌ Код истек")
                print("💡 Запросите новый код:")
                print("   python -m app.mtproto.auth")
                await client.disconnect()
                return False
            elif "PHONE_CODE" in error_str:
                print("\n❌ Проблема с кодом подтверждения")
                print(f"   Полная ошибка: {error_str}")
                print("💡 Запросите новый код:")
                print("   python -m app.mtproto.auth")
                await client.disconnect()
                return False
            else:
                raise
        
        # Сохраняем сессию
        print("\n💾 Сохранение сессии...")
        await client.disconnect()
        await client.connect()
        await client.start()  # Это сохранит сессию
        
        print("\n" + "=" * 60)
        print("✅ Авторизация успешна!")
        print("=" * 60)
        
        # Получаем информацию о себе
        me = await client.get_me()
        print(f"\n👤 Авторизован как: {me.first_name}")
        if me.username:
            print(f"   Username: @{me.username}")
        print(f"   Phone: {me.phone_number}")
        
        print("\n📁 Файл сессии создан: crossposting_session.session")
        
        # Удаляем временный файл
        if PHONE_CODE_HASH_FILE.exists():
            PHONE_CODE_HASH_FILE.unlink()
            print("🗑️  Временный файл phone_code_hash удален")
        
        print("\n🚀 Теперь можно запустить MTProto как сервис:")
        print("  sudo systemctl enable --now crossposting-mtproto")
        print("=" * 60)
        
        await client.stop()
        return True
        
    except Exception as e:
        error_str = str(e)
        print(f"\n❌ Ошибка: {error_str}")
        await client.disconnect()
        return False


if __name__ == "__main__":
    # Проверяем аргументы
    if len(sys.argv) > 1:
        # Шаг 2: Использование кода
        code = sys.argv[1]
        success = asyncio.run(step2_use_code(code))
    else:
        # Шаг 1: Запрос кода
        success = asyncio.run(step1_request_code())
    
    sys.exit(0 if success else 1)
