"""Скрипт для создания первого администратора."""
import asyncio
import sys
from pathlib import Path

# Добавляем путь к проекту
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import select
from config.database import async_session_maker
from app.models.admin import Admin
from app.core.security import get_password_hash


async def create_admin(username: str, password: str, email: str = None):
    """Создать администратора."""
    async with async_session_maker() as session:
        # Проверяем, существует ли администратор
        result = await session.execute(
            select(Admin).where(Admin.username == username)
        )
        existing_admin = result.scalar_one_or_none()
        
        if existing_admin:
            print(f"Администратор с именем '{username}' уже существует!")
            return
        
        # Создаем нового администратора
        password_hash = get_password_hash(password)
        admin = Admin(
            username=username,
            password_hash=password_hash,
            email=email,
            is_active=True
        )
        
        session.add(admin)
        await session.commit()
        
        print(f"Администратор '{username}' успешно создан!")


if __name__ == "__main__":
    import getpass
    
    if len(sys.argv) < 3:
        print("Использование: python create_admin.py <username> [email]")
        print("Пароль будет запрошен интерактивно")
        sys.exit(1)
    
    username = sys.argv[1]
    email = sys.argv[2] if len(sys.argv) > 2 else None
    password = getpass.getpass("Введите пароль: ")
    password_confirm = getpass.getpass("Подтвердите пароль: ")
    
    if password != password_confirm:
        print("Пароли не совпадают!")
        sys.exit(1)
    
    if len(password) < 8:
        print("Пароль должен содержать минимум 8 символов!")
        sys.exit(1)
    
    asyncio.run(create_admin(username, password, email))

