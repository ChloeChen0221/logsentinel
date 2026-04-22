"""
通知消费者协程

从 notification_queue 取出任务 → 根据 channel_type 走 registry 分发 →
按 Notifier 返回的 retriable 决定重试 → CAS 更新 notifications 表终态。

CAS：UPDATE WHERE id=? AND status='pending' 与补偿扫表互斥。
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, update

from database.session import AsyncSessionLocal
from engine.logger import get_logger
from models import Alert, Notification
from notifier.queue import NotificationTask, notification_queue
from notifier.registry import get_notifier


logger = get_logger(__name__)


MAX_RETRIES = 3
DEFAULT_BACKOFFS = [1.0, 2.0, 4.0]
# 45009 速率超限：覆盖默认 backoff 为 60s
RATE_LIMIT_BACKOFF = 60.0
# 45033 并发超限：短 backoff 让并发数降下来
CONCURRENT_LIMIT_BACKOFF = 5.0


async def _cas_mark(
    notification_id: int,
    new_status: str,
    content: str = "",
    error_message: Optional[str] = None,
    retry_count: int = 0,
) -> bool:
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
    """单条任务的发送 + 重试 + 终态 CAS"""
    notifier = get_notifier(task.channel_type)
    if notifier is None:
        await _cas_mark(
            task.notification_id,
            "failed",
            error_message=f"unknown channel type: {task.channel_type}",
            retry_count=0,
        )
        return

    async with AsyncSessionLocal() as db:
        alert = (await db.execute(select(Alert).where(Alert.id == task.alert_id))).scalar_one_or_none()
        if alert is None:
            logger.warning("consumer_alert_missing", notification_id=task.notification_id, alert_id=task.alert_id)
            await _cas_mark(task.notification_id, "failed", error_message="alert missing", retry_count=0)
            return

    last_error: Optional[str] = None
    for attempt in range(MAX_RETRIES):
        try:
            result = await notifier.send(alert, task.rule_name, task.channel_config)
            if result.get("success"):
                content = json.dumps(result.get("content", {}), ensure_ascii=False)
                acquired = await _cas_mark(
                    task.notification_id, "sent", content=content, retry_count=attempt
                )
                if acquired:
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
                        channel_type=task.channel_type,
                        attempt=attempt + 1,
                    )
                else:
                    logger.info(
                        "notification_cas_lost",
                        notification_id=task.notification_id,
                        reason="already processed by another worker",
                    )
                return

            # 发送返回 success=False
            last_error = result.get("error") or "send returned success=False"
            errcode = result.get("errcode")
            retriable = result.get("retriable", True)
            if not retriable:
                # 鉴权 / 参数错误：不重试直接失败
                await _cas_mark(
                    task.notification_id,
                    "failed",
                    error_message=f"{last_error} (errcode={errcode})",
                    retry_count=attempt,
                )
                logger.error(
                    "notification_failed_not_retriable",
                    notification_id=task.notification_id,
                    alert_id=task.alert_id,
                    channel_type=task.channel_type,
                    error=last_error,
                    errcode=errcode,
                )
                return

            # 可重试：决定 backoff 时长
            if errcode == 45009:
                backoff = RATE_LIMIT_BACKOFF
                logger.warning(
                    "notification_rate_limited",
                    notification_id=task.notification_id,
                    attempt=attempt + 1,
                    backoff=backoff,
                )
            elif errcode == 45033:
                backoff = CONCURRENT_LIMIT_BACKOFF
                logger.warning(
                    "notification_concurrent_limited",
                    notification_id=task.notification_id,
                    attempt=attempt + 1,
                    backoff=backoff,
                )
            else:
                backoff = DEFAULT_BACKOFFS[attempt] if attempt < len(DEFAULT_BACKOFFS) else DEFAULT_BACKOFFS[-1]

        except Exception as e:
            last_error = str(e)
            backoff = DEFAULT_BACKOFFS[attempt] if attempt < len(DEFAULT_BACKOFFS) else DEFAULT_BACKOFFS[-1]

        logger.warning(
            "notification_retry",
            notification_id=task.notification_id,
            attempt=attempt + 1,
            channel_type=task.channel_type,
            error=last_error,
        )
        if attempt < MAX_RETRIES - 1:
            await asyncio.sleep(backoff)

    # 重试耗尽
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
        channel_type=task.channel_type,
        error=last_error,
    )


async def notifier_worker(shutdown_event: asyncio.Event) -> None:
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
