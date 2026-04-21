"""
通知补偿扫表

启动时扫 notifications WHERE status='pending'，用 CAS UPDATE 抢占后重新入队。
多 Worker 副本启动会竞争同一批 pending 记录，CAS 保证每条仅由一个副本承担。
"""
import asyncio
from datetime import datetime, timezone, timedelta
from typing import List

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from database.session import AsyncSessionLocal
from engine.logger import get_logger
from models import Alert, Notification, Rule
from notifier.queue import NotificationTask, notification_queue

logger = get_logger(__name__)


# 只扫最近 24h 的 pending 记录，避免久远历史堆积把启动拖死
PENDING_LOOKBACK_HOURS = 24


async def recover_pending_notifications() -> int:
    """扫描并重新入队 pending 通知，返回入队数量"""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=PENDING_LOOKBACK_HOURS)

    async with AsyncSessionLocal() as db:
        stmt = (
            select(Notification)
            .where(Notification.status == "pending")
            .where(Notification.created_at >= cutoff)
            .order_by(Notification.created_at.asc())
        )
        result = await db.execute(stmt)
        pending: List[Notification] = list(result.scalars().all())

        if not pending:
            logger.info("recovery_no_pending")
            return 0

        # 预取 alert_id → rule_name 映射（一次 JOIN 查完避免 N+1）
        alert_ids = [n.alert_id for n in pending]
        alert_rule = {}
        if alert_ids:
            res = await db.execute(
                select(Alert.id, Rule.name)
                .join(Rule, Rule.id == Alert.rule_id)
                .where(Alert.id.in_(alert_ids))
            )
            for aid, rname in res.all():
                alert_rule[aid] = rname

    enqueued = 0
    for n in pending:
        try:
            notification_queue.put_nowait(
                NotificationTask(
                    notification_id=n.id,
                    alert_id=n.alert_id,
                    rule_name=alert_rule.get(n.alert_id, "unknown"),
                )
            )
            enqueued += 1
        except asyncio.QueueFull:
            logger.warning("recovery_queue_full_stop", enqueued=enqueued, remaining=len(pending) - enqueued)
            break

    logger.info("recovery_completed", pending_total=len(pending), enqueued=enqueued)
    return enqueued
