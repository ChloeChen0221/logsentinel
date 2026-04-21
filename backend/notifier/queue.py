"""
通知队列（进程内 asyncio.Queue）

设计（D7）：
- 入队先在 PG 写 status=pending 的 notifications 记录
- 再 put_nowait 到内存队列（超时则记日志但不阻塞评估）
- 崩溃补偿扫 status=pending 的记录重新入队（CAS 抢占）
"""
import asyncio
from dataclasses import dataclass
from typing import Optional

from models import Notification
from sqlalchemy.ext.asyncio import AsyncSession

from engine.logger import get_logger

logger = get_logger(__name__)


# 全局队列；consumer 协程从这里取；queue 尺寸决定背压阈值
QUEUE_MAX_SIZE = 10_000
notification_queue: asyncio.Queue = asyncio.Queue(maxsize=QUEUE_MAX_SIZE)


@dataclass
class NotificationTask:
    """通知任务（引用 Notification 表记录 id）"""
    notification_id: int
    alert_id: int
    rule_name: str


async def enqueue_notification(
    db: AsyncSession,
    alert_id: int,
    rule_name: str,
    channel: str,
) -> Optional[int]:
    """创建 pending 通知记录并入队

    Returns:
        notification_id；若队列满则写入 DB 但不入队（由 recovery 启动时补发）
    """
    notification = Notification(
        alert_id=alert_id,
        channel=channel,
        status="pending",
        content="",
    )
    db.add(notification)
    await db.flush()
    nid = notification.id
    await db.commit()

    try:
        notification_queue.put_nowait(
            NotificationTask(notification_id=nid, alert_id=alert_id, rule_name=rule_name)
        )
        logger.debug("notification_enqueued", notification_id=nid, alert_id=alert_id)
    except asyncio.QueueFull:
        logger.warning(
            "notification_queue_full_deferred",
            notification_id=nid,
            alert_id=alert_id,
            queue_size=notification_queue.qsize(),
        )
        # 不抛异常：记录已落 PG pending，recovery 会补发

    return nid
