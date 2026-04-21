"""
Redis 分布式锁：SET NX EX + DEL

D4 已知风险：DEL 不带 value CAS 检查，若锁因 TTL 过期后被另一 Worker 获取，
原持有者执行完 DEL 会误删新持有者的锁。锁 TTL=60s 远大于单次评估耗时（<5s），
正常运行不触发；评估耗时接近 TTL 时升级为 Lua CAS。
"""
from contextlib import asynccontextmanager
from typing import AsyncIterator

from redis.asyncio import Redis


@asynccontextmanager
async def redis_lock(
    redis: Redis,
    key: str,
    value: str,
    ttl_seconds: int = 60,
) -> AsyncIterator[bool]:
    """
    分布式锁上下文管理器

    Args:
        redis: Redis 客户端
        key: 锁 Key（建议 lock:rule:{rid}）
        value: 锁持有者标识（用于日志/调试，未做 CAS 释放）
        ttl_seconds: 锁 TTL，超时自动释放

    Yields:
        acquired: True 表示成功抢到锁；False 表示锁已被占用
    """
    acquired = bool(await redis.set(key, value, nx=True, ex=ttl_seconds))
    try:
        yield acquired
    finally:
        if acquired:
            # 主动释放，加快后续 Worker rebalance
            try:
                await redis.delete(key)
            except Exception:
                # 删除失败不影响主流程，TTL 兜底
                pass
