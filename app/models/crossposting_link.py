"""Модель связи кросспостинга."""

from sqlalchemy import Column, BigInteger, DateTime, Boolean, ForeignKey, Index, UniqueConstraint, String
from sqlalchemy.orm import relationship
from datetime import datetime
from typing import Optional
from config.database import Base


class CrosspostingLink(Base):
    """Связь между Telegram и MAX каналами."""

    __tablename__ = "crossposting_links"

    id = Column(BigInteger, primary_key=True, index=True)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    telegram_channel_id = Column(
        BigInteger, ForeignKey("telegram_channels.id", ondelete="CASCADE"), nullable=False, index=True
    )
    max_channel_id = Column(BigInteger, ForeignKey("max_channels.id", ondelete="CASCADE"), nullable=False, index=True)
    is_enabled = Column(Boolean, default=True, nullable=False, index=True)

    # Поля подписки
    subscription_status = Column(String(50), default="free_trial", nullable=False, index=True)
    free_trial_end_date = Column(DateTime, nullable=True)
    subscription_end_date = Column(DateTime, nullable=True)
    is_first_link = Column(Boolean, default=False, nullable=False)
    last_payment_date = Column(DateTime, nullable=True)
    payment_id = Column(String(255), nullable=True)
    payment_status = Column(String(50), nullable=True)
    yookassa_payment_id = Column(String(255), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Unique constraint для предотвращения дублирования связей
    __table_args__ = (
        UniqueConstraint("telegram_channel_id", "max_channel_id", name="uq_telegram_max_channels"),
        Index("idx_telegram_channel", "telegram_channel_id"),
        Index("idx_max_channel", "max_channel_id"),
        Index("idx_is_enabled", "is_enabled"),
        Index("idx_subscription_status", "subscription_status"),
    )

    # Relationships
    user = relationship("User", back_populates="crossposting_links")
    telegram_channel = relationship("TelegramChannel", back_populates="crossposting_links")
    max_channel = relationship("MaxChannel", back_populates="crossposting_links")
    message_logs = relationship("MessageLog", back_populates="crossposting_link", cascade="all, delete-orphan")
    failed_messages = relationship("FailedMessage", back_populates="crossposting_link", cascade="all, delete-orphan")
