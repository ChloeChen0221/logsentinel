"""
控制台通知器
使用 structlog 输出结构化日志
"""
from typing import Dict, Any

import structlog

from notifier.base import BaseNotifier
from models import Alert


logger = structlog.get_logger(__name__)


class ConsoleNotifier(BaseNotifier):
    """控制台通知器"""

    async def send(
        self,
        alert: Alert,
        rule_name: str,
        channel_config: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        try:
            notification_content = {
                "rule_name": rule_name,
                "rule_id": alert.rule_id,
                "severity": alert.severity,
                "fingerprint": alert.fingerprint,
                "first_seen": alert.first_seen.isoformat(),
                "last_seen": alert.last_seen.isoformat(),
                "hit_count": alert.hit_count,
                "group_by": alert.group_by,
                "sample_log": alert.sample_log,
            }
            logger.info("alert_notification", channel="console", alert_id=alert.id, **notification_content)
            return {
                "success": True,
                "retriable": False,
                "content": notification_content,
                "error": None,
                "errcode": 0,
            }
        except Exception as e:
            logger.error("notification_failed", channel="console", alert_id=alert.id, error=str(e))
            return {
                "success": False,
                "retriable": True,
                "content": {},
                "error": str(e),
                "errcode": -1,
            }
