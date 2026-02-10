"""
通知接口基类
"""
from abc import ABC, abstractmethod
from typing import Dict, Any
from models import Alert


class BaseNotifier(ABC):
    """通知接口抽象类"""
    
    @abstractmethod
    async def send(self, alert: Alert, rule_name: str) -> Dict[str, Any]:
        """
        发送告警通知
        
        Args:
            alert: 告警对象
            rule_name: 规则名称
        
        Returns:
            通知结果字典，包含：
            - success: 是否成功
            - channel: 通知渠道
            - error: 错误信息（如果失败）
        """
        pass
