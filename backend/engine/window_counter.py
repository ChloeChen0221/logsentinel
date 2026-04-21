"""
基于 Redis ZSET 的滑动窗口计数器

D5：
- Key: window:{rule_id}:{fingerprint}
- Member: {ts_ms}:{uuid8}（同毫秒多事件不被去重）
- Score: ts_ms
- TTL: 2 × window_seconds（每次 ADD 后 EXPIRE）
- 上限: 100000，超出 ZREMRANGEBYRANK 截断最老元素
"""
import uuid
from datetime import datetime
from typing import Iterable

from redis.asyncio import Redis

from engine.logger import get_logger

logger = get_logger(__name__)

MAX_MEMBERS_PER_KEY = 100_000


class RedisWindowCounter:
    """基于 Redis ZSET 的滑动窗口计数器（按 fingerprint 分组）"""

    def __init__(self, redis: Redis, rule_id: int, fingerprint: str, window_seconds: int):
        self.redis = redis
        self.rule_id = rule_id
        self.fingerprint = fingerprint
        self.window_seconds = window_seconds
        self.key = f"window:{rule_id}:{fingerprint}"
        # TTL 设为 2 倍窗口，让停止活跃的分组在 Redis 内自动回收
        self._expire_seconds = max(window_seconds * 2, 1)

    @staticmethod
    def _to_ms(ts: datetime) -> int:
        return int(ts.timestamp() * 1000)

    async def add(self, timestamps: Iterable[datetime]) -> None:
        """批量写入事件时间戳，并维护 TTL 与上限

        member 必须唯一，否则 ZADD 会被去重；附加 uuid8 后缀避免同毫秒事件丢失。
        """
        items = list(timestamps)
        if not items:
            return

        mapping = {}
        for ts in items:
            ts_ms = self._to_ms(ts)
            member = f"{ts_ms}:{uuid.uuid4().hex[:8]}"
            mapping[member] = ts_ms

        pipe = self.redis.pipeline(transaction=False)
        pipe.zadd(self.key, mapping)
        pipe.expire(self.key, self._expire_seconds)
        pipe.zcard(self.key)
        results = await pipe.execute()
        zcard = results[-1] or 0

        # 上限保护：超出后截断最老元素
        if zcard > MAX_MEMBERS_PER_KEY:
            to_remove = zcard - MAX_MEMBERS_PER_KEY
            await self.redis.zremrangebyrank(self.key, 0, to_remove - 1)
            logger.warning(
                "window_counter_truncated",
                rule_id=self.rule_id,
                fingerprint=self.fingerprint,
                window_seconds=self.window_seconds,
                removed=to_remove,
                cap=MAX_MEMBERS_PER_KEY,
            )

    async def count(self, current_time: datetime) -> int:
        """读取窗口内计数前先清理过期事件"""
        now_ms = self._to_ms(current_time)
        window_start_ms = now_ms - self.window_seconds * 1000

        pipe = self.redis.pipeline(transaction=False)
        # 删除窗口外（含等于左边界）；左闭右开等价 [-inf, window_start_ms)
        pipe.zremrangebyscore(self.key, "-inf", f"({window_start_ms}")
        pipe.zcard(self.key)
        results = await pipe.execute()
        return int(results[-1] or 0)

    async def reset(self) -> None:
        """清空当前 Key（测试或重置场景使用）"""
        await self.redis.delete(self.key)
