"""
通知接口基类

Notifier 协议返回字段：
- success: bool  发送是否成功
- retriable: bool  失败是否应重试（鉴权错误返回 False，直接失败）
- content: dict  成功时返回的内容摘要（JSON 可序列化）
- error: str     失败时的错误描述
- errcode: int   渠道原始错误码（可选）
"""
from abc import ABC, abstractmethod
from typing import Dict, Any

from models import Alert


class BaseNotifier(ABC):
    """通知接口抽象类"""

    @abstractmethod
    async def send(
        self,
        alert: Alert,
        rule_name: str,
        channel_config: Dict[str, Any],
    ) -> Dict[str, Any]:
        """发送告警通知

        Args:
            alert: 告警对象
            rule_name: 规则名称
            channel_config: 渠道配置快照（含 webhook_url 等连接参数）

        Returns:
            dict 含字段：success, retriable, content, error, errcode
        """
        ...
