"""
Rule 数据模型
告警规则定义
"""
from sqlalchemy import Column, Integer, String, Boolean, Text, DateTime, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from database.base import Base


def _utcnow():
    return datetime.now(timezone.utc)


class Rule(Base):
    """告警规则模型"""
    __tablename__ = "rules"
    
    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    enabled = Column(Boolean, nullable=False, default=True)
    severity = Column(String(20), nullable=False)
    selector_namespace = Column(String(255), nullable=False)
    selector_labels = Column(JSONB, nullable=True)
    match_type = Column(String(20), nullable=False)
    match_pattern = Column(Text, nullable=False)
    window_seconds = Column(Integer, nullable=False, default=0)
    threshold = Column(Integer, nullable=False, default=1)
    group_by = Column(JSONB, nullable=False)
    cooldown_seconds = Column(Integer, nullable=False, default=300)
    last_query_time = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow)
    # rule_type: keyword / threshold / sequence（默认 keyword，向后兼容）
    rule_type = Column(String(20), nullable=False, default="keyword")
    # correlation_type: sequence（顺序关联）/ negative（否定关联），仅 rule_type=sequence 时有效
    correlation_type = Column(String(20), nullable=True)
    # notify_config: 通知渠道列表 [{"type":"wecom","name":"xx","webhook_url":"...","mentioned_mobile_list":[]}]
    notify_config = Column(JSONB, nullable=False, default=list, server_default='[]')
    
    # 关系
    alerts = relationship("Alert", back_populates="rule", cascade="all, delete-orphan")
    steps = relationship("RuleStep", back_populates="rule", cascade="all, delete-orphan", order_by="RuleStep.step_order")
    sequence_state = relationship("SequenceState", back_populates="rule", cascade="all, delete-orphan", uselist=False)
    
    # 索引
    __table_args__ = (
        Index("ix_rules_enabled", "enabled"),
        Index("ix_rules_enabled_last_query_time", "enabled", "last_query_time"),
    )
