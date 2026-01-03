"""Общие модели из основного проекта (для использования в админке)."""

from sqlalchemy import Column, BigInteger, String, Text, Integer, DateTime, Boolean, ForeignKey, JSON, Index, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


class User(Base):
    """Модель пользователя (копия из основного проекта)."""

    __tablename__ = "users"

    id = Column(BigInteger, primary_key=True, index=True)
    telegram_user_id = Column(BigInteger, unique=True, nullable=False, index=True)
    telegram_username = Column(String, nullable=True)
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)


class TelegramChannel(Base):
    """Модель Telegram канала (копия из основного проекта)."""

    __tablename__ = "telegram_channels"

    id = Column(BigInteger, primary_key=True, index=True)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    channel_id = Column(BigInteger, nullable=False, index=True)
    channel_username = Column(String, nullable=True)
    channel_title = Column(String, nullable=True)
    bot_added_at = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)


class MaxChannel(Base):
    """Модель MAX канала (копия из основного проекта)."""

    __tablename__ = "max_channels"

    id = Column(BigInteger, primary_key=True, index=True)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    channel_id = Column(BigInteger, nullable=False, index=True)
    channel_username = Column(String, nullable=True)
    channel_title = Column(String, nullable=True)
    bot_added_at = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)


class CrosspostingLink(Base):
    """Модель связи кросспостинга (копия из основного проекта)."""

    __tablename__ = "crossposting_links"

    id = Column(BigInteger, primary_key=True, index=True)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    telegram_channel_id = Column(
        BigInteger, ForeignKey("telegram_channels.id", ondelete="CASCADE"), nullable=False, index=True
    )
    max_channel_id = Column(BigInteger, ForeignKey("max_channels.id", ondelete="CASCADE"), nullable=False, index=True)
    is_enabled = Column(Boolean, default=True, nullable=False, index=True)
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)


class MessageLog(Base):
    """Модель лога сообщений (копия из основного проекта)."""

    __tablename__ = "messages_log"

    id = Column(BigInteger, primary_key=True, index=True)
    crossposting_link_id = Column(BigInteger, ForeignKey("crossposting_links.id", ondelete="CASCADE"), nullable=False)
    telegram_message_id = Column(BigInteger, nullable=False, index=True)
    max_message_id = Column(String, nullable=True)
    status = Column(String, nullable=False, index=True)
    error_message = Column(Text, nullable=True)
    message_type = Column(String, nullable=True)
    file_size = Column(BigInteger, nullable=True)
    processing_time_ms = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=func.now(), nullable=False, index=True)
    sent_at = Column(DateTime, nullable=True)


class FailedMessage(Base):
    """Модель неудачных сообщений (копия из основного проекта)."""

    __tablename__ = "failed_messages"

    id = Column(BigInteger, primary_key=True, index=True)
    crossposting_link_id = Column(
        BigInteger, ForeignKey("crossposting_links.id", ondelete="CASCADE"), nullable=False, index=True
    )
    telegram_message_id = Column(BigInteger, nullable=False)
    error_message = Column(Text, nullable=False)
    retry_count = Column(Integer, default=0, nullable=False)
    last_retry_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=func.now(), nullable=False)
    resolved_at = Column(DateTime, nullable=True, index=True)


class AuditLog(Base):
    """Модель аудита (копия из основного проекта)."""

    __tablename__ = "audit_log"

    id = Column(BigInteger, primary_key=True, index=True)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    action = Column(String, nullable=False)
    entity_type = Column(String, nullable=False)
    entity_id = Column(BigInteger, nullable=False)
    details = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=func.now(), nullable=False, index=True)
