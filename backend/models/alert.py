"""
Alert 数据模型
告警记录
"""
from sqlalchemy import Column, Integer, BigInteger, String, DateTime, ForeignKey, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from database.base import Base


def _utcnow():
    return datetime.now(timezone.utc)


class Alert(Base):
    """告警记录模型"""
    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True)
    rule_id = Column(Integer, ForeignKey("rules.id", ondelete="CASCADE"), nullable=False)
    fingerprint = Column(String(64), nullable=False, unique=True)
    severity = Column(String(20), nullable=False)
    status = Column(String(20), nullable=False, default="active")
    first_seen = Column(DateTime(timezone=True), nullable=False)
    last_seen = Column(DateTime(timezone=True), nullable=False)
    hit_count = Column(BigInteger, nullable=False, default=1)
    group_by = Column(JSONB, nullable=False)
    sample_log = Column(JSONB, nullable=False)
    last_notified_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow)

    # 关系
    rule = relationship("Rule", back_populates="alerts")
    notifications = relationship("Notification", back_populates="alert", cascade="all, delete-orphan")

    # 索引
    __table_args__ = (
        Index("ix_alerts_fingerprint", "fingerprint", unique=True),
        Index("ix_alerts_rule_id_last_seen", "rule_id", "last_seen"),
    )
