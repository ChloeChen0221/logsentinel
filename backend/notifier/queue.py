"""
通知队列（进程内 asyncio.Queue）

扇出语义（D1）：
- 规则 notify_config 含 N 个渠道 → 写 N 条 notifications → put_nowait N 次
- 每条 notifications 带独立的 channel_config 快照（D3），消费者不再反查 rules
- notify_config 为空时 fallback 到 console 渠道（保持向后兼容）

持久化先行（D7）：
- 入队前先写 DB pending 记录，再 put_nowait 到内存队列
- 队列满 → DB 已落 pending，由 recovery 启动时补发
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from engine.logger import get_logger
from models import Notification


logger = get_logger(__name__)


QUEUE_MAX_SIZE = 10_000
notification_queue: asyncio.Queue = asyncio.Queue(maxsize=QUEUE_MAX_SIZE)

# notify_config 为空时的默认 fallback 渠道
_DEFAULT_FALLBACK: List[Dict[str, Any]] = [{"type": "console", "name": "console"}]


@dataclass
class NotificationTask:
    """通知任务（对应一条 notifications 记录 + 一个渠道快照）"""
    notification_id: int
    alert_id: int
    rule_name: str
    channel_type: str
    channel_config: Dict[str, Any] = field(default_factory=dict)


async def enqueue_notification(
    db: AsyncSession,
    alert_id: int,
    rule_name: str,
    channels: Optional[List[Dict[str, Any]]] = None,
) -> List[int]:
    """告警触发时扇出通知

    Args:
        db: 当前评估事务（函数内提交）
        alert_id: 告警 ID
        rule_name: 规则名（写入 task，避免 consumer 再查库）
        channels: 规则的 notify_config；空/None 时 fallback 到 console

    Returns:
        写入的 notification_id 列表
    """
    effective_channels = list(channels) if channels else list(_DEFAULT_FALLBACK)

    created_ids: List[int] = []
    records = []
    for ch in effective_channels:
        ch_type = ch.get("type", "console")
        record = Notification(
            alert_id=alert_id,
            channel=ch_type,
            channel_config=ch,
            status="pending",
            content="",
        )
        db.add(record)
        records.append((record, ch_type, ch))

    await db.flush()
    for rec, _ch_type, _ch in records:
        created_ids.append(rec.id)
    await db.commit()

    # 提交后入队（顺序无关）
    for rec, ch_type, ch in records:
        task = NotificationTask(
            notification_id=rec.id,
            alert_id=alert_id,
            rule_name=rule_name,
            channel_type=ch_type,
            channel_config=ch,
        )
        try:
            notification_queue.put_nowait(task)
            logger.debug(
                "notification_enqueued",
                notification_id=rec.id,
                alert_id=alert_id,
                channel_type=ch_type,
            )
        except asyncio.QueueFull:
            logger.warning(
                "notification_queue_full_deferred",
                notification_id=rec.id,
                alert_id=alert_id,
                channel_type=ch_type,
                queue_size=notification_queue.qsize(),
            )
            # DB 已 pending，recovery 会补发

    return created_ids
