from sqlalchemy import Column, Integer, String, Text, ForeignKey, Index
from sqlalchemy.orm import relationship
from database.base import Base


class RuleStep(Base):
    """序列规则步骤模型"""
    __tablename__ = "rule_steps"

    id = Column(Integer, primary_key=True)
    rule_id = Column(Integer, ForeignKey("rules.id", ondelete="CASCADE"), nullable=False)
    step_order = Column(Integer, nullable=False)  # 步骤序号，从 0 开始
    match_type = Column(String(20), nullable=False)   # contains / regex
    match_pattern = Column(Text, nullable=False)
    window_seconds = Column(Integer, nullable=False, default=60)  # 该步骤超时窗口
    threshold = Column(Integer, nullable=False, default=1)        # 命中次数阈值

    rule = relationship("Rule", back_populates="steps")

    __table_args__ = (
        Index("ix_rule_steps_rule_id", "rule_id"),
    )
