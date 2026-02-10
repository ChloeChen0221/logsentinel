"""
Alert 数据模型
告警记录
"""
from sqlalchemy import Column, Integer, String, DateTime, JSON, ForeignKey, Index
from sqlalchemy.orm import relationship
from datetime import datetime
from database.base import Base


class Alert(Base):
    """告警记录模型"""
    __tablename__ = "alerts"
    
    id = Column(Integer, primary_key=True)
    rule_id = Column(Integer, ForeignKey("rules.id", ondelete="CASCADE"), nullable=False)
    fingerprint = Column(String(64), nullable=False, unique=True)
    severity = Column(String(20), nullable=False)
    status = Column(String(20), nullable=False, default="active")
    first_seen = Column(DateTime, nullable=False)
    last_seen = Column(DateTime, nullable=False)
    hit_count = Column(Integer, nullable=False, default=1)
    group_by = Column(JSON, nullable=False)
    sample_log = Column(JSON, nullable=False)
    last_notified_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # 关系
    rule = relationship("Rule", back_populates="alerts")
    notifications = relationship("Notification", back_populates="alert", cascade="all, delete-orphan")
    
    # 索引
    __table_args__ = (
        Index("ix_alerts_fingerprint", "fingerprint", unique=True),
        Index("ix_alerts_rule_id", "rule_id"),
        Index("ix_alerts_last_seen", "last_seen"),
    )
