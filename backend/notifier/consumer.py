"""
通知消费者协程

从 notification_queue 取出任务 → 加载 Alert/Rule → 调用 Notifier → 3 次指数退避重试 →
CAS 更新 notifications 表终态（sent/failed）。

CAS 语义：UPDATE WHERE id=? AND status='pending' RETURNING 确保与补偿扫表抢占互斥。
"""
import asyncio
import json
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, update

from database.session import AsyncSessionLocal
from engine.logger import get_logger
from models import Alert, Notification, Rule
from notifier.console import ConsoleNotifier
from notifier.queue import NotificationTask, notification_queue

logger = get_logger(__name__)


MAX_RETRIES = 3
BACKOFFS = [1.0, 2.0, 4.0]


async def _send_once(alert: Alert, rule_name: str) -> dict:
    """执行一次发送（当前仅 console 渠道）"""
    return await ConsoleNotifier().send(alert, rule_name)


async def _cas_mark(
    notification_id: int,
    new_status: str,
    content: str = "",
    error_message: Optional[str] = None,
    retry_count: int = 0,
) -> bool:
    """CAS：仅当 status='pending' 时更新为终态；返回是否抢到

    UPDATE notifications SET ... WHERE id=? AND status='pending'
    受 PG `(status, created_at)` 索引加速；rowcount=1 表示抢占成功。
    """
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            update(Notification)
            .where(Notification.id == notification_id, Notification.status == "pending")
            .values(
                status=new_status,
                content=content,
                error_message=error_message,
                retry_count=retry_count,
                notified_at=now,
            )
        )
        await db.commit()
        return result.rowcount == 1


async def _process_one(task: NotificationTask) -> None:
    """处理单个通知任务：重试 + CAS 终态更新"""
    # 加载 alert 对象（rule_name 已在 task 内）
    async with AsyncSessionLocal() as db:
        alert = (await db.execute(select(Alert).where(Alert.id == task.alert_id))).scalar_one_or_none()
        if alert is None:
            logger.warning("consumer_alert_missing", notification_id=task.notification_id, alert_id=task.alert_id)
            await _cas_mark(task.notification_id, "failed", error_message="alert missing", retry_count=0)
            return

    last_error: Optional[str] = None
    for attempt in range(MAX_RETRIES):
        try:
            result = await _send_once(alert, task.rule_name)
            if result.get("success"):
                content = json.dumps(result.get("content", {}), ensure_ascii=False)
                acquired = await _cas_mark(
                    task.notification_id, "sent", content=content, retry_count=attempt
                )
                if acquired:
                    # 更新 alert.last_notified_at（独立短事务）
                    async with AsyncSessionLocal() as db:
                        await db.execute(
                            update(Alert)
                            .where(Alert.id == task.alert_id)
                            .values(last_notified_at=datetime.now(timezone.utc))
                        )
                        await db.commit()
                    logger.info(
                        "notification_sent",
                        notification_id=task.notification_id,
                        alert_id=task.alert_id,
                        attempt=attempt + 1,
                    )
                else:
                    logger.info(
                        "notification_cas_lost",
                        notification_id=task.notification_id,
                        reason="already processed by another worker",
                    )
                return
            last_error = result.get("error") or "send returned success=False"
        except Exception as e:
            last_error = str(e)

        logger.warning(
            "notification_retry",
            notification_id=task.notification_id,
            attempt=attempt + 1,
            error=last_error,
        )
        if attempt < MAX_RETRIES - 1:
            await asyncio.sleep(BACKOFFS[attempt])

    # 全部失败
    await _cas_mark(
        task.notification_id,
        "failed",
        error_message=last_error or "unknown",
        retry_count=MAX_RETRIES,
    )
    logger.error(
        "notification_failed_permanent",
        notification_id=task.notification_id,
        alert_id=task.alert_id,
        error=last_error,
    )


async def notifier_worker(shutdown_event: asyncio.Event) -> None:
    """消费者协程主循环（等待 shutdown_event 退出）"""
    while not shutdown_event.is_set():
        try:
            task = await asyncio.wait_for(notification_queue.get(), timeout=1.0)
        except asyncio.TimeoutError:
            continue
        try:
            await _process_one(task)
        except Exception as e:
            logger.error(
                "consumer_unhandled_error",
                notification_id=task.notification_id,
                error=str(e),
            )
        finally:
            notification_queue.task_done()
