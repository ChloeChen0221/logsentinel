"""
Redis ZSET 滑动窗口分布式限流（webhook 级）

Key:      wecom:rl:{url_key}           # url_key = md5(webhook_url)[:12]
结构:     ZSET
member:   "{ts_ms}:{uuid8}"             # 同毫秒不去重
score:    ts_ms
TTL:      120s                          # window 60s × 2，空闲自动回收

语义：60s 内至多 20 条；超过则 sleep 到最老一条过期后重试 acquire。
Redis 异常 → 调用方 fail-open 退化到进程内 AsyncLimiter。
"""
from __future__ import annotations

import asyncio
import time
import uuid

from redis.asyncio import Redis

from engine.logger import get_logger


logger = get_logger(__name__)


# 企微官方：20 条 / 60 秒 / 机器人
RATE_LIMIT_COUNT = 20
RATE_LIMIT_WINDOW_MS = 60_000
# Redis key TTL（略大于窗口，避免空闲 key 堆积）
KEY_TTL_SECONDS = 120
# 单次 acquire 最多等待次数（防止死循环）
MAX_WAIT_ROUNDS = 10
# sleep 最小精度（毫秒），避免 busy loop
MIN_SLEEP_MS = 10


def _now_ms() -> int:
    return int(time.time() * 1000)


async def acquire(redis: Redis, url_key: str) -> None:
    """阻塞式分布式限流 acquire。

    Raises:
        redis 相关异常（RedisError / TimeoutError / ConnectionError）
        调用方必须捕获并走 fail-open 降级
    """
    key = f"wecom:rl:{url_key}"

    for attempt in range(MAX_WAIT_ROUNDS):
        now_ms = _now_ms()
        cutoff = now_ms - RATE_LIMIT_WINDOW_MS

        # pipeline: 清理 + 取 count
        pipe = redis.pipeline(transaction=False)
        pipe.zremrangebyscore(key, 0, cutoff)
        pipe.zcard(key)
        _, count = await pipe.execute()

        if count < RATE_LIMIT_COUNT:
            # 放行：写入本次 member
            member = f"{now_ms}:{uuid.uuid4().hex[:8]}"
            add_pipe = redis.pipeline(transaction=False)
            add_pipe.zadd(key, {member: now_ms})
            add_pipe.expire(key, KEY_TTL_SECONDS)
            await add_pipe.execute()
            return

        # 超限：取最老一条的 score 计算剩余等待毫秒
        oldest = await redis.zrange(key, 0, 0, withscores=True)
        if not oldest:
            # 理论不可能（count >= 20 但 zrange 为空），继续下一轮
            continue
        _, oldest_score = oldest[0]
        wait_ms = int(oldest_score) + RATE_LIMIT_WINDOW_MS - now_ms
        wait_ms = max(wait_ms, MIN_SLEEP_MS)
        logger.info(
            "wecom_ratelimit_wait",
            url_key=url_key,
            count=count,
            wait_ms=wait_ms,
            attempt=attempt + 1,
        )
        await asyncio.sleep(wait_ms / 1000.0)

    # 多轮仍拿不到配额：放行并告警（不应阻塞告警链路）
    logger.warning("wecom_ratelimit_acquire_exceeded_rounds", url_key=url_key)
