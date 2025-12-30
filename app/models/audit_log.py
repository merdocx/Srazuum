"""Модель аудита действий."""
from sqlalchemy import Column, BigInteger, String, Integer, DateTime, ForeignKey, JSON, Index
from sqlalchemy.orm import relationship
from datetime import datetime
from config.database import Base


class AuditLog(Base):
    """Лог действий пользователей."""
    
    __tablename__ = "audit_log"
    
    id = Column(BigInteger, primary_key=True, index=True)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    action = Column(String, nullable=False)  # 'create_link', 'delete_link', 'enable_link', 'disable_link'
    entity_type = Column(String, nullable=False)  # 'crossposting_link', 'channel'
    entity_id = Column(BigInteger, nullable=False)
    details = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    
    __table_args__ = (
        Index('idx_user_created', 'user_id', 'created_at'),
        Index('idx_action_created', 'action', 'created_at'),
    )
    
    # Relationships
    user = relationship("User", back_populates="audit_logs")



