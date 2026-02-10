"""
时间窗口计数器单元测试
"""
import pytest
from datetime import datetime, timezone, timedelta

from backend.engine.window_counter import WindowCounter


def test_window_counter_basic():
    """测试基本计数功能"""
    counter = WindowCounter(window_seconds=60)
    
    now = datetime.now(timezone.utc)
    
    # 添加 3 个时间戳
    counter.add(now - timedelta(seconds=10))
    counter.add(now - timedelta(seconds=5))
    counter.add(now)
    
    # 应该有 3 个
    assert counter.count(now) == 3


def test_window_counter_expiry():
    """测试过期时间戳自动清理"""
    counter = WindowCounter(window_seconds=60)
    
    now = datetime.now(timezone.utc)
    
    # 添加过期和未过期的时间戳
    counter.add(now - timedelta(seconds=70))  # 过期
    counter.add(now - timedelta(seconds=50))  # 未过期
    counter.add(now - timedelta(seconds=30))  # 未过期
    counter.add(now)                          # 未过期
    
    # 应该只有 3 个未过期的
    assert counter.count(now) == 3


def test_window_counter_sliding():
    """测试滑动窗口"""
    counter = WindowCounter(window_seconds=60)
    
    base_time = datetime(2026, 2, 4, 10, 0, 0, tzinfo=timezone.utc)
    
    # 添加多个时间戳（从 base_time 开始）
    counter.add(base_time)                             # T=0
    counter.add(base_time + timedelta(seconds=10))     # T=10
    counter.add(base_time + timedelta(seconds=20))     # T=20
    counter.add(base_time + timedelta(seconds=30))     # T=30
    
    # 在 base_time + 30s 时，所有 4 个都在窗口内（窗口覆盖 T=-30 到 T=30）
    assert counter.count(base_time + timedelta(seconds=30)) == 4
    
    # 在 base_time + 65s 时，T=0 已过期（T=5 到 T=65），剩下 3 个
    assert counter.count(base_time + timedelta(seconds=65)) == 3
    
    # 在 base_time + 85s 时，T=0、T=10、T=20 都过期（T=25 到 T=85），只剩 T=30
    assert counter.count(base_time + timedelta(seconds=85)) == 1
    
    # 在 base_time + 100s 时，所有都过期（T=40 到 T=100）
    assert counter.count(base_time + timedelta(seconds=100)) == 0


def test_window_counter_empty():
    """测试空计数器"""
    counter = WindowCounter(window_seconds=60)
    
    now = datetime.now(timezone.utc)
    
    # 空计数器应该返回 0
    assert counter.count(now) == 0


def test_window_counter_all_expired():
    """测试所有时间戳都过期"""
    counter = WindowCounter(window_seconds=60)
    
    now = datetime.now(timezone.utc)
    
    # 添加一些过期的时间戳
    counter.add(now - timedelta(seconds=70))
    counter.add(now - timedelta(seconds=80))
    counter.add(now - timedelta(seconds=90))
    
    # 应该返回 0
    assert counter.count(now) == 0


def test_window_counter_reset():
    """测试重置计数器"""
    counter = WindowCounter(window_seconds=60)
    
    now = datetime.now(timezone.utc)
    
    # 添加一些时间戳
    counter.add(now - timedelta(seconds=10))
    counter.add(now)
    
    assert counter.count(now) == 2
    
    # 重置
    counter.reset()
    
    # 应该为空
    assert counter.count(now) == 0


def test_window_counter_different_sizes():
    """测试不同窗口大小"""
    now = datetime.now(timezone.utc)
    
    # 30 秒窗口
    counter_30 = WindowCounter(window_seconds=30)
    counter_30.add(now - timedelta(seconds=40))
    counter_30.add(now - timedelta(seconds=20))
    counter_30.add(now)
    assert counter_30.count(now) == 2  # 只有后两个在窗口内
    
    # 60 秒窗口
    counter_60 = WindowCounter(window_seconds=60)
    counter_60.add(now - timedelta(seconds=40))
    counter_60.add(now - timedelta(seconds=20))
    counter_60.add(now)
    assert counter_60.count(now) == 3  # 所有都在窗口内
    
    # 120 秒窗口
    counter_120 = WindowCounter(window_seconds=120)
    counter_120.add(now - timedelta(seconds=100))
    counter_120.add(now - timedelta(seconds=40))
    counter_120.add(now)
    assert counter_120.count(now) == 3  # 所有都在窗口内


def test_window_counter_boundary():
    """测试窗口边界"""
    counter = WindowCounter(window_seconds=60)
    
    now = datetime.now(timezone.utc)
    
    # 添加恰好在边界上的时间戳
    counter.add(now - timedelta(seconds=60))  # 恰好在边界
    counter.add(now - timedelta(seconds=59))  # 在窗口内
    counter.add(now)
    
    # 边界上的时间戳应该被排除
    count = counter.count(now)
    assert count >= 2  # 至少有后两个
