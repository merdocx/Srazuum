"""Скрипт для извлечения session string из Telegram Desktop на Mac."""
import json
import sys
from pathlib import Path
import os

def find_telegram_desktop_sessions():
    """
    Поиск файлов сессий Telegram Desktop на Mac.
    
    Returns:
        list: Список путей к файлам сессий
    """
    home = Path.home()
    telegram_data_path = home / "Library/Application Support/Telegram Desktop/tdata"
    
    sessions = []
    
    if telegram_data_path.exists():
        print(f"✅ Найден путь к данным Telegram Desktop: {telegram_data_path}")
        
        # Ищем файлы сессий (обычно это файлы с расширением или без)
        # Telegram Desktop хранит сессии в файлах вида: D877F783D5D3EF8C, A7FDF864FBC10B77 и т.д.
        for file in telegram_data_path.iterdir():
            if file.is_file() and not file.name.startswith('.') and len(file.name) == 16:
                # Это может быть файл сессии
                sessions.append(file)
    
    return sessions, telegram_data_path


def extract_session_string_manual():
    """
    Инструкция для ручного извлечения session string.
    
    Примечание: Прямое извлечение session string из файлов Telegram Desktop
    сложно, так как они зашифрованы. Рекомендуется использовать альтернативные методы.
    """
    print("=" * 70)
    print("Извлечение Session String из Telegram Desktop на Mac")
    print("=" * 70)
    print()
    
    sessions, telegram_path = find_telegram_desktop_sessions()
    
    if sessions:
        print(f"📁 Найдено {len(sessions)} потенциальных файлов сессий:")
        for i, session in enumerate(sessions, 1):
            print(f"   {i}. {session.name}")
        print()
    else:
        print("⚠️  Файлы сессий не найдены в стандартном расположении")
        print(f"   Ожидаемый путь: {telegram_path}")
        print()
    
    print("=" * 70)
    print("СПОСОБЫ ПОЛУЧЕНИЯ SESSION STRING:")
    print("=" * 70)
    print()
    
    print("📌 СПОСОБ 1: Использование Telegram Desktop через Pyrogram")
    print("-" * 70)
    print("1. Установите Telegram Desktop на Mac")
    print("2. Авторизуйтесь в Telegram Desktop")
    print("3. Используйте Pyrogram для экспорта session string:")
    print()
    print("   python -m app.mtproto.auth_with_session_string export")
    print()
    print("   (Этот способ работает, если у вас уже есть авторизованная")
    print("   сессия Pyrogram, созданная через интерактивную авторизацию)")
    print()
    
    print("📌 СПОСОБ 2: Интерактивная авторизация через Pyrogram")
    print("-" * 70)
    print("1. Запустите интерактивную авторизацию:")
    print()
    print("   cd /root/crossposting_service")
    print("   source venv/bin/activate")
    print("   python -m app.mtproto.auth_interactive")
    print()
    print("2. Введите код подтверждения из Telegram")
    print("3. После успешной авторизации экспортируйте session string:")
    print()
    print("   python -m app.mtproto.auth_with_session_string export")
    print()
    
    print("📌 СПОСОБ 3: Использование Telegram Web (экспериментально)")
    print("-" * 70)
    print("1. Откройте https://web.telegram.org в браузере")
    print("2. Авторизуйтесь через QR-код")
    print("3. Используйте DevTools для извлечения session (требует знаний)")
    print()
    print("   ⚠️  Этот способ сложен и не рекомендуется")
    print()
    
    print("📌 СПОСОБ 4: Использование готовых инструментов")
    print("-" * 70)
    print("Существуют сторонние инструменты для извлечения session string:")
    print()
    print("1. TelegramSessionExtractor (требует установки)")
    print("2. telethon-session-extractor (для Telethon)")
    print()
    print("   ⚠️  Используйте на свой риск, проверяйте безопасность")
    print()
    
    print("=" * 70)
    print("РЕКОМЕНДАЦИЯ:")
    print("=" * 70)
    print()
    print("✅ Самый простой и безопасный способ:")
    print("   1. Используйте интерактивную авторизацию Pyrogram")
    print("   2. После успешной авторизации экспортируйте session string")
    print()
    print("   Это не требует доступа к файлам Telegram Desktop и")
    print("   работает на любой платформе (Mac, Linux, Windows)")
    print()


def check_telegram_desktop_installed():
    """Проверка, установлен ли Telegram Desktop."""
    home = Path.home()
    telegram_path = home / "Library/Application Support/Telegram Desktop"
    
    if telegram_path.exists():
        print(f"✅ Telegram Desktop установлен: {telegram_path}")
        return True
    else:
        print(f"⚠️  Telegram Desktop не найден в стандартном расположении")
        print(f"   Ожидаемый путь: {telegram_path}")
        return False


if __name__ == "__main__":
    print()
    check_telegram_desktop_installed()
    print()
    extract_session_string_manual()
    
    print()
    print("=" * 70)
    print("СЛЕДУЮЩИЕ ШАГИ:")
    print("=" * 70)
    print()
    print("1. Если у вас уже есть авторизованная сессия Pyrogram:")
    print("   python -m app.mtproto.auth_with_session_string export")
    print()
    print("2. Если сессии нет, создайте её через интерактивную авторизацию:")
    print("   python -m app.mtproto.auth_interactive")
    print()
    print("3. После создания сессии экспортируйте session string:")
    print("   python -m app.mtproto.auth_with_session_string export")
    print()




