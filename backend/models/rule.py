"""
Rule 数据模型
告警规则定义
"""
from sqlalchemy import Column, Integer, String, Boolean, Text, JSON, DateTime, Index
from sqlalchemy.orm import relationship
from datetime import datetime
from database.base import Base


class Rule(Base):
    """告警规则模型"""
    __tablename__ = "rules"
    
    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    enabled = Column(Boolean, nullable=False, default=True)
    severity = Column(String(20), nullable=False)
    selector_namespace = Column(String(255), nullable=False)
    selector_labels = Column(JSON, nullable=True)
    match_type = Column(String(20), nullable=False)
    match_pattern = Column(Text, nullable=False)
    window_seconds = Column(Integer, nullable=False, default=0)
    threshold = Column(Integer, nullable=False, default=1)
    group_by = Column(JSON, nullable=False)
    cooldown_seconds = Column(Integer, nullable=False, default=300)
    last_query_time = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # 关系
    alerts = relationship("Alert", back_populates="rule", cascade="all, delete-orphan")
    
    # 索引
    __table_args__ = (
        Index("ix_rules_enabled", "enabled"),
    )
