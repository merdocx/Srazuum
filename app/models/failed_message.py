"""Модель неудачных сообщений."""
from sqlalchemy import Column, BigInteger, Text, Integer, DateTime, ForeignKey, Index
from sqlalchemy.orm import relationship
from datetime import datetime
from config.database import Base


class FailedMessage(Base):
    """Неудачные отправки сообщений."""
    
    __tablename__ = "failed_messages"
    
    id = Column(BigInteger, primary_key=True, index=True)
    crossposting_link_id = Column(BigInteger, ForeignKey("crossposting_links.id", ondelete="CASCADE"), nullable=False, index=True)
    telegram_message_id = Column(BigInteger, nullable=False)
    error_message = Column(Text, nullable=False)
    retry_count = Column(Integer, default=0, nullable=False)
    last_retry_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    resolved_at = Column(DateTime, nullable=True, index=True)
    
    __table_args__ = (
        Index('idx_retry', 'retry_count', 'last_retry_at'),
    )
    
    # Relationships
    crossposting_link = relationship("CrosspostingLink", back_populates="failed_messages")










