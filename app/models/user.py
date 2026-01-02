"""Модель пользователя."""
from sqlalchemy import Column, BigInteger, String, DateTime
from sqlalchemy.orm import relationship
from datetime import datetime
from config.database import Base


class User(Base):
    """Пользователь системы."""
    
    __tablename__ = "users"
    
    id = Column(BigInteger, primary_key=True, index=True)
    telegram_user_id = Column(BigInteger, unique=True, nullable=False, index=True)
    telegram_username = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationships
    telegram_channels = relationship("TelegramChannel", back_populates="user", cascade="all, delete-orphan")
    max_channels = relationship("MaxChannel", back_populates="user", cascade="all, delete-orphan")
    crossposting_links = relationship("CrosspostingLink", back_populates="user", cascade="all, delete-orphan")
    audit_logs = relationship("AuditLog", back_populates="user")







