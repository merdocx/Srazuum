"""Интерактивная авторизация MTProto - запрашивает код и сразу ждет ввода."""
import asyncio
import sys
from pyrogram import Client
from config.settings import settings
from app.utils.logger import setup_logging

setup_logging()


async def authorize_interactive():
    """Интерактивная авторизация - запрашивает код и сразу ждет ввода."""
    print("=" * 60)
    print("ИНТЕРАКТИВНАЯ АВТОРИЗАЦИЯ MTProto")
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
        # Используем интерактивный режим Pyrogram
        # Он сам запросит код и будет ждать ввода в том же процессе
        print("\n📱 Запрос кода подтверждения...")
        print("   (Код будет запрошен автоматически)")
        print("\n⏳ Ожидание кода...")
        print("   Когда код придет в Telegram/SMS, введите его ниже:")
        print("")
        
        await client.start()
        
        print("\n" + "=" * 60)
        print("✅ Авторизация успешна!")
        print("=" * 60)
        print("\nФайл сессии создан: crossposting_session.session")
        
        # Получаем информацию о себе
        me = await client.get_me()
        print(f"\n👤 Авторизован как: {me.first_name}")
        if me.username:
            print(f"   Username: @{me.username}")
        print(f"   Phone: {me.phone_number}")
        
        print("\n🚀 Теперь можно запустить MTProto как сервис:")
        print("  sudo systemctl enable --now crossposting-mtproto")
        print("=" * 60)
        
        await client.stop()
        return True
        
    except KeyboardInterrupt:
        print("\n\nАвторизация отменена")
        return False
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
                print(f"\n⚠️  Слишком частые запросы кодов")
                if wait_hours > 0:
                    print(f"Подождите {wait_hours} часов {wait_minutes % 60} минут")
                elif wait_minutes > 0:
                    print(f"Подождите {wait_minutes} минут")
                else:
                    print(f"Подождите {wait_seconds} секунд")
        elif "PHONE_CODE" in error_str:
            print("\n⚠️  Проблема с кодом подтверждения")
            if "INVALID" in error_str:
                print("Код неверный")
            elif "EXPIRED" in error_str:
                print("Код истек - попробуйте еще раз")
            else:
                print("Проверьте, что код введен правильно")
        elif "EOF" in error_str:
            print("\n⚠️  Не удалось получить ввод кода")
            print("💡 Убедитесь, что запускаете скрипт в интерактивном терминале")
        
        return False


if __name__ == "__main__":
    try:
        success = asyncio.run(authorize_interactive())
        if success:
            sys.exit(0)
        else:
            sys.exit(1)
    except KeyboardInterrupt:
        print("\n\nАвторизация отменена")
        sys.exit(0)
