"""Модель лога сообщений."""
from sqlalchemy import Column, BigInteger, String, Text, Integer, DateTime, ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import relationship
from datetime import datetime
from config.database import Base


class MessageLog(Base):
    """Лог отправленных сообщений."""
    
    __tablename__ = "messages_log"
    
    id = Column(BigInteger, primary_key=True, index=True)
    crossposting_link_id = Column(BigInteger, ForeignKey("crossposting_links.id", ondelete="CASCADE"), nullable=False)
    telegram_message_id = Column(BigInteger, nullable=False, index=True)
    max_message_id = Column(String, nullable=True)
    status = Column(String, nullable=False, index=True)  # 'pending', 'success', 'failed'
    error_message = Column(Text, nullable=True)
    message_type = Column(String, nullable=True)  # 'text', 'photo', 'video', etc.
    file_size = Column(BigInteger, nullable=True)
    processing_time_ms = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    sent_at = Column(DateTime, nullable=True)
    
    # Unique constraint для предотвращения дублирования отправок
    __table_args__ = (
        UniqueConstraint('crossposting_link_id', 'telegram_message_id', name='uq_link_message'),
        Index('idx_status', 'status'),
        Index('idx_created_at', 'created_at'),
        Index('idx_link_created', 'crossposting_link_id', 'created_at'),
    )
    
    # Relationships
    crossposting_link = relationship("CrosspostingLink", back_populates="message_logs")



