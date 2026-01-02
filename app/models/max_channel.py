"""Модель MAX канала."""
from sqlalchemy import Column, BigInteger, String, DateTime, Boolean, ForeignKey, Index
from sqlalchemy.orm import relationship
from datetime import datetime
from config.database import Base


class MaxChannel(Base):
    """MAX канал."""
    
    __tablename__ = "max_channels"
    
    id = Column(BigInteger, primary_key=True, index=True)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    channel_id = Column(String, nullable=False, index=True)
    channel_username = Column(String, nullable=True)
    channel_title = Column(String, nullable=False)
    bot_added_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    
    # Relationships
    user = relationship("User", back_populates="max_channels")
    crossposting_links = relationship("CrosspostingLink", back_populates="max_channel", cascade="all, delete-orphan")







