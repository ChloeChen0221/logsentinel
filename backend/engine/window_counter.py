"""
时间窗口计数器
用于统计时间窗口内的日志数量
"""
from collections import deque
from datetime import datetime, timezone
from typing import Deque


class WindowCounter:
    """时间窗口计数器"""
    
    def __init__(self, window_seconds: int):
        """
        初始化计数器
        
        Args:
            window_seconds: 窗口大小（秒）
        """
        self.window_seconds = window_seconds
        self.timestamps: Deque[datetime] = deque()
    
    def add(self, timestamp: datetime) -> None:
        """
        添加新的时间戳
        
        Args:
            timestamp: 日志时间戳
        """
        # 先清理过期的时间戳
        self._cleanup(timestamp)
        
        # 添加新时间戳
        self.timestamps.append(timestamp)
    
    def count(self, current_time: datetime) -> int:
        """
        获取窗口内的计数
        
        Args:
            current_time: 当前时间
        
        Returns:
            窗口内的日志数量
        """
        # 清理过期的时间戳
        self._cleanup(current_time)
        
        # 返回剩余的数量
        return len(self.timestamps)
    
    def _cleanup(self, current_time: datetime) -> None:
        """
        清理过期的时间戳
        
        Args:
            current_time: 当前时间
        """
        # 计算窗口起始时间
        window_start = current_time.timestamp() - self.window_seconds
        
        # 移除所有早于窗口起始时间的时间戳
        while self.timestamps and self.timestamps[0].timestamp() < window_start:
            self.timestamps.popleft()
    
    def reset(self) -> None:
        """重置计数器"""
        self.timestamps.clear()
