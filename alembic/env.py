"""Alembic environment configuration."""
from logging.config import fileConfig
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config
from alembic import context

# Import models and base
from config.database import Base
from app.models import *  # noqa: F401, F403

# this is the Alembic Config object
config = context.config

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Import settings for database URL
from config.settings import settings

# Set the database URL from settings
config.set_main_option("sqlalchemy.url", settings.database_url.replace("+asyncpg", ""))

# add your model's MetaData object here for 'autogenerate' support
target_metadata = Base.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    # Для offline режима используем синхронный URL
    url = config.get_main_option("sqlalchemy.url")
    # Убираем +asyncpg для синхронного режима
    if url and "+asyncpg" in url:
        url = url.replace("+asyncpg", "")
    
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    # Для миграций используем синхронный драйвер
    from sqlalchemy import create_engine
    from sqlalchemy.engine import Connection
    
    # Убираем +asyncpg и используем psycopg2
    sync_url = settings.database_url.replace("+asyncpg", "").replace("postgresql+asyncpg", "postgresql")
    
    connectable = create_engine(
        sync_url,
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    import asyncio
    asyncio.run(run_migrations_online())

