from datetime import datetime, timezone, timedelta
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from models import SequenceState, RuleStep
from engine.logger import get_logger

logger = get_logger(__name__)


class SequenceStateManager:
    """序列状态管理器：维护序列规则的跨轮次状态"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def load_or_create(self, rule_id: int) -> SequenceState:
        """加载规则的序列状态，不存在则创建初始状态"""
        result = await self.db.execute(
            select(SequenceState).where(SequenceState.rule_id == rule_id)
        )
        state = result.scalar_one_or_none()
        if state is None:
            state = SequenceState(
                rule_id=rule_id,
                current_step=0,
                step_timestamps=[],
                started_at=None,
                expires_at=None,
            )
            self.db.add(state)
            await self.db.flush()
            logger.debug("SequenceState created", rule_id=rule_id)
        return state

    async def advance(self, state: SequenceState, step: RuleStep, timestamp: datetime) -> None:
        """推进步骤：记录命中时间戳，更新 current_step 和 expires_at"""
        timestamps = list(state.step_timestamps or [])
        # 确保列表长度与 step_order 对齐
        while len(timestamps) <= step.step_order:
            timestamps.append(None)
        timestamps[step.step_order] = timestamp.isoformat()

        state.step_timestamps = timestamps
        state.current_step = step.step_order + 1

        if state.started_at is None:
            state.started_at = timestamp

        state.expires_at = timestamp + timedelta(seconds=step.window_seconds)
        logger.debug(
            "SequenceState advanced",
            rule_id=state.rule_id,
            current_step=state.current_step,
            expires_at=state.expires_at.isoformat(),
        )

    async def reset(self, state: SequenceState) -> None:
        """重置状态到初始值"""
        state.current_step = 0
        state.step_timestamps = []
        state.started_at = None
        state.expires_at = None
        logger.debug("SequenceState reset", rule_id=state.rule_id)

    def is_expired(self, state: SequenceState) -> bool:
        """检查当前步骤是否已超时"""
        if state.expires_at is None:
            return False
        now = datetime.now(timezone.utc)
        expires = state.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        return now > expires

    async def save(self, state: SequenceState) -> None:
        """持久化状态"""
        await self.db.commit()
