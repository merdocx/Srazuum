"""Вспомогательные утилиты для тестов."""

from sqlalchemy import TypeDecorator, BigInteger, Integer
from sqlalchemy.dialects import sqlite, postgresql


class BigIntegerAuto(TypeDecorator):
    """
    BigInteger с автоинкрементом, работающий в SQLite и PostgreSQL.
    
    В SQLite использует INTEGER для автоинкремента,
    в PostgreSQL использует BIGINT.
    """

    impl = BigInteger
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "sqlite":
            return dialect.type_descriptor(Integer())
        else:
            return dialect.type_descriptor(BigInteger())

