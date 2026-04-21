"""
Worker 分片：Redis 心跳 + 哈希取模

设计：
- 每个 Worker 启动后通过 SET worker:{id} EX 15 注册并续期心跳
- 每轮评估周期通过 KEYS worker:* 列出存活副本列表
- 规则归属判定：sorted(workers)[rule_id % len(workers)] == self.id
- Worker 宕机 15s 后心跳失效，其他副本下一轮自动接管
"""
import os
import uuid
from typing import List, Optional

from redis.asyncio import Redis


HEARTBEAT_KEY_PREFIX = "worker:"
HEARTBEAT_TTL_SECONDS = 15
# 心跳续期间隔必须 < TTL/2，保证存活视图稳定
HEARTBEAT_INTERVAL_SECONDS = 5


def resolve_worker_id() -> str:
    """Worker ID 来源 fallback：WORKER_ID > HOSTNAME > local-{uuid8}"""
    return (
        os.getenv("WORKER_ID")
        or os.getenv("HOSTNAME")
        or f"local-{uuid.uuid4().hex[:8]}"
    )


class RuleSharding:
    """规则分片管理器"""

    def __init__(self, redis: Redis, worker_id: Optional[str] = None):
        self.redis = redis
        self.worker_id = worker_id or resolve_worker_id()
        self._heartbeat_key = f"{HEARTBEAT_KEY_PREFIX}{self.worker_id}"

    async def heartbeat(self) -> None:
        """续期心跳（覆盖式 SET 重置 TTL）"""
        await self.redis.set(self._heartbeat_key, "1", ex=HEARTBEAT_TTL_SECONDS)

    async def alive_workers(self) -> List[str]:
        """列出当前存活 Worker，按 ID 排序保证所有副本视图一致"""
        keys = await self.redis.keys(f"{HEARTBEAT_KEY_PREFIX}*")
        worker_ids = [k[len(HEARTBEAT_KEY_PREFIX):] for k in keys]
        return sorted(worker_ids)

    def owns(self, rule_id: int, alive: List[str]) -> bool:
        """哈希取模判定：当前 Worker 是否拥有 rule_id 的执行权

        若存活列表为空则不拥有任何规则（异常态，等下一轮 heartbeat 后恢复）
        """
        if not alive:
            return False
        return alive[rule_id % len(alive)] == self.worker_id

    async def unregister(self) -> None:
        """优雅退出时主动删除心跳 Key"""
        await self.redis.delete(self._heartbeat_key)
