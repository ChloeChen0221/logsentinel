"""
Notification 数据模型
通知记录
"""
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Index
from sqlalchemy.orm import relationship
from datetime import datetime
from database.base import Base


class Notification(Base):
    """通知记录模型"""
    __tablename__ = "notifications"
    
    id = Column(Integer, primary_key=True)
    alert_id = Column(Integer, ForeignKey("alerts.id", ondelete="CASCADE"), nullable=False)
    notified_at = Column(DateTime, nullable=False)
    channel = Column(String(50), nullable=False)
    content = Column(Text, nullable=False)
    status = Column(String(20), nullable=False)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    
    # 关系
    alert = relationship("Alert", back_populates="notifications")
    
    # 索引
    __table_args__ = (
        Index("ix_notifications_alert_id", "alert_id"),
        Index("ix_notifications_notified_at", "notified_at"),
    )
