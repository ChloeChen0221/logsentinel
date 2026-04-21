from sqlalchemy import Column, Integer, DateTime, ForeignKey, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from database.base import Base


class SequenceState(Base):
    """序列规则跨轮次执行状态"""
    __tablename__ = "sequence_states"

    id = Column(Integer, primary_key=True)
    rule_id = Column(Integer, ForeignKey("rules.id", ondelete="CASCADE"), nullable=False, unique=True)
    current_step = Column(Integer, nullable=False, default=0)               # 当前待匹配步骤索引
    step_timestamps = Column(JSONB, nullable=False, default=list)           # 各步骤命中时间戳数组
    started_at = Column(DateTime(timezone=True), nullable=True)             # 第一步命中时间
    expires_at = Column(DateTime(timezone=True), nullable=True)             # 当前步骤超时时间

    rule = relationship("Rule", back_populates="sequence_state")

    __table_args__ = (
        Index("ix_sequence_states_rule_id", "rule_id"),
    )
