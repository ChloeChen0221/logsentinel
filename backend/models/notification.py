"""
Notification 数据模型
通知记录 —— 至少一次交付的状态机：pending → sent / failed
"""
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from database.base import Base


def _utcnow():
    return datetime.now(timezone.utc)


class Notification(Base):
    """通知记录模型"""
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True)
    alert_id = Column(Integer, ForeignKey("alerts.id", ondelete="CASCADE"), nullable=False)
    channel = Column(String(50), nullable=False)
    content = Column(Text, nullable=False)
    # status: pending（入队待发送） / sent（成功） / failed（重试耗尽）
    status = Column(String(16), nullable=False, default="pending")
    retry_count = Column(Integer, nullable=False, default=0)
    error_message = Column(Text, nullable=True)
    notified_at = Column(DateTime(timezone=True), nullable=True)  # 终态时间（sent 或 failed）
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    # channel_config: 触发时渠道配置快照（webhook_url/name/mentioned_mobile_list 等）
    channel_config = Column(JSONB, nullable=False, default=dict, server_default='{}')

    # 关系
    alert = relationship("Alert", back_populates="notifications")

    # 索引
    __table_args__ = (
        Index("ix_notifications_alert_id_notified_at", "alert_id", "notified_at"),
        Index("ix_notifications_status_created_at", "status", "created_at"),
    )