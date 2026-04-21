"""
RedisWindowCounter 单元测试

覆盖三大场景：
1. 分组独立（不同 fingerprint Key 互不干扰）
2. 过期事件自动清理
3. 单 Key 上限截断
"""
import pytest
import pytest_asyncio
from datetime import datetime, timezone, timedelta

import fakeredis.aioredis as fakeredis_async

from backend.engine.window_counter import RedisWindowCounter, MAX_MEMBERS_PER_KEY
from backend.engine.fingerprint import compute_fingerprint


@pytest_asyncio.fixture
async def redis():
    client = fakeredis_async.FakeRedis(decode_responses=True)
    yield client
    await client.flushall()
    await client.aclose()


@pytest.mark.asyncio
async def test_group_isolation(redis):
    """场景 1：不同 fingerprint 的窗口计数互相独立"""
    fp_a = compute_fingerprint(1, {"namespace": "A"})
    fp_b = compute_fingerprint(1, {"namespace": "B"})
    counter_a = RedisWindowCounter(redis, rule_id=1, fingerprint=fp_a, window_seconds=300)
    counter_b = RedisWindowCounter(redis, rule_id=1, fingerprint=fp_b, window_seconds=300)

    now = datetime.now(timezone.utc)
    await counter_a.add([now - timedelta(seconds=i) for i in range(6)])
    await counter_b.add([now - timedelta(seconds=i) for i in range(5)])

    assert await counter_a.count(now) == 6
    assert await counter_b.count(now) == 5
    # 跨分组不会汇总成 11
    assert fp_a != fp_b


@pytest.mark.asyncio
async def test_expired_events_cleaned(redis):
    """场景 2：count 前自动清理窗口外事件"""
    fp = compute_fingerprint(2)
    counter = RedisWindowCounter(redis, rule_id=2, fingerprint=fp, window_seconds=60)

    now = datetime.now(timezone.utc)
    await counter.add([
        now - timedelta(seconds=120),  # 过期
        now - timedelta(seconds=90),   # 过期
        now - timedelta(seconds=30),   # 在窗口
        now - timedelta(seconds=10),   # 在窗口
        now,                           # 在窗口
    ])

    assert await counter.count(now) == 3


@pytest.mark.asyncio
async def test_truncate_when_exceeds_cap(redis, monkeypatch):
    """场景 3：单 Key 超过上限时截断最老元素"""
    # 降低上限避免测试塞 10w 条
    monkeypatch.setattr(
        "backend.engine.window_counter.MAX_MEMBERS_PER_KEY",
        50,
    )

    fp = compute_fingerprint(3)
    counter = RedisWindowCounter(redis, rule_id=3, fingerprint=fp, window_seconds=600)

    base = datetime.now(timezone.utc) - timedelta(seconds=300)
    # 写入 60 条递增时间戳
    timestamps = [base + timedelta(milliseconds=i) for i in range(60)]
    await counter.add(timestamps)

    # ZCARD 应被截断到上限
    zcard = await redis.zcard(counter.key)
    assert zcard == 50

    # 最老的 10 个被移除：剩下应为 10..59
    members = await redis.zrange(counter.key, 0, 0, withscores=True)
    assert members
    oldest_score = members[0][1]
    assert oldest_score >= int(timestamps[10].timestamp() * 1000)


@pytest.mark.asyncio
async def test_same_millisecond_not_deduplicated(redis):
    """同一毫秒多条事件不被 ZADD 去重（member 附加 uuid8）"""
    fp = compute_fingerprint(4)
    counter = RedisWindowCounter(redis, rule_id=4, fingerprint=fp, window_seconds=60)

    now = datetime.now(timezone.utc)
    await counter.add([now, now, now])
    assert await counter.count(now) == 3


@pytest.mark.asyncio
async def test_ttl_set_after_add(redis):
    """每次 ADD 后 EXPIRE 2×window"""
    fp = compute_fingerprint(5)
    counter = RedisWindowCounter(redis, rule_id=5, fingerprint=fp, window_seconds=120)

    await counter.add([datetime.now(timezone.utc)])
    ttl = await redis.ttl(counter.key)
    # TTL 应在 (0, 240] 区间
    assert 0 < ttl <= 240
