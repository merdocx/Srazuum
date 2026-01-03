"""Скрипт для создания первого администратора."""
import asyncio
import sys
from pathlib import Path

# Добавляем путь к проекту
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(Path(__file__).parent))

from sqlalchemy import select, text
from app.core.database import AsyncSessionLocal
from app.models.admin import Admin
from app.core.security import get_password_hash


async def create_admin(username: str, password: str, email: str = None):
    """Создать администратора."""
    async with AsyncSessionLocal() as session:
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
    if len(sys.argv) < 3:
        print("Использование: python create_admin_script.py <username> <password> [email]")
        sys.exit(1)
    
    username = sys.argv[1]
    password = sys.argv[2]
    email = sys.argv[3] if len(sys.argv) > 3 else None
    
    if len(password) < 8:
        print("Пароль должен содержать минимум 8 символов!")
        sys.exit(1)
    
    asyncio.run(create_admin(username, password, email))

