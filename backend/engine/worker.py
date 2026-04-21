"""
规则引擎 Worker 主循环

P2 改造：
- 启动注册 Redis 心跳（resolve_worker_id 自动 fallback）
- 每轮先续期心跳 → 读存活列表 → 用哈希取模过滤"我"负责的规则
- 每条规则评估前抢 Redis 分布式锁，失败跳过（其他副本在做）
- asyncio.Semaphore 限制并发评估数
"""
import asyncio
import signal
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from datetime import datetime, timezone
from typing import Optional

from config import settings
from engine.logger import configure_logging, get_logger
from database.session import AsyncSessionLocal
from database.redis import get_redis_client, close_redis_pool
from engine.evaluator import RuleEvaluator
from engine.sharding import RuleSharding, resolve_worker_id, HEARTBEAT_INTERVAL_SECONDS
from engine.lock import redis_lock
from notifier.consumer import notifier_worker
from notifier.recovery import recover_pending_notifications

logger = get_logger(__name__)


# 每轮评估并发上限（可通过 ENGINE_CONCURRENCY 环境变量覆盖）
DEFAULT_CONCURRENCY = 10
RULE_LOCK_TTL_SECONDS = 60
# 通知消费者协程数（每 Worker 副本并发消费 queue）
DEFAULT_NOTIFIER_WORKERS = 3


class EngineWorker:
    """规则引擎 Worker"""

    def __init__(
        self,
        interval_seconds: Optional[int] = None,
        concurrency: int = DEFAULT_CONCURRENCY,
        notifier_workers: int = DEFAULT_NOTIFIER_WORKERS,
    ):
        self.interval_seconds = interval_seconds or settings.ENGINE_INTERVAL_SECONDS
        self.concurrency = concurrency
        self.notifier_workers = notifier_workers
        self.scheduler: Optional[AsyncIOScheduler] = None
        self.is_running = False
        self._shutdown_event = asyncio.Event()
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._notifier_tasks: list = []

        self.worker_id = resolve_worker_id()
        self.redis = get_redis_client()
        self.sharding = RuleSharding(self.redis, worker_id=self.worker_id)

    async def _evaluate_one(
        self,
        rule,
        semaphore: asyncio.Semaphore,
    ) -> None:
        """单规则评估：限并发 + 分布式锁兜底"""
        async with semaphore:
            lock_key = f"lock:rule:{rule.id}"
            async with redis_lock(self.redis, lock_key, self.worker_id, RULE_LOCK_TTL_SECONDS) as acquired:
                if not acquired:
                    logger.debug(
                        "Rule lock held by another worker, skip",
                        rule_id=rule.id,
                        worker_id=self.worker_id,
                    )
                    return
                async with AsyncSessionLocal() as db:
                    evaluator = RuleEvaluator(db, self.redis)
                    try:
                        await evaluator.evaluate_rule(rule)
                    except Exception as e:
                        logger.error(
                            "Rule evaluation error",
                            rule_id=rule.id,
                            rule_name=rule.name,
                            error=str(e),
                        )

    async def _execute_cycle(self):
        """单轮评估循环：取存活列表 → 过滤 my_rules → 并发评估

        心跳由独立任务维持（_heartbeat_loop），与评估周期解耦
        """
        cycle_start = datetime.now(timezone.utc)
        logger.info("Engine cycle started", worker_id=self.worker_id, cycle_time=cycle_start.isoformat())

        try:
            # 1. 读取存活列表（心跳由后台任务续期）
            alive = await self.sharding.alive_workers()

            # 2. 加载启用规则
            async with AsyncSessionLocal() as db:
                evaluator = RuleEvaluator(db, self.redis)
                all_rules = await evaluator.load_enabled_rules()

            # 3. 哈希取模过滤"我"负责的规则
            my_rules = [r for r in all_rules if self.sharding.owns(r.id, alive)]
            logger.info(
                "Cycle sharding result",
                worker_id=self.worker_id,
                alive_workers=len(alive),
                total_rules=len(all_rules),
                my_rules=len(my_rules),
            )

            # 4. 并发评估
            semaphore = asyncio.Semaphore(self.concurrency)
            await asyncio.gather(
                *[self._evaluate_one(rule, semaphore) for rule in my_rules],
                return_exceptions=True,
            )

            elapsed = (datetime.now(timezone.utc) - cycle_start).total_seconds()
            logger.info(
                "Engine cycle completed",
                worker_id=self.worker_id,
                rule_count=len(my_rules),
                elapsed_seconds=round(elapsed, 3),
            )

        except Exception as e:
            elapsed = (datetime.now(timezone.utc) - cycle_start).total_seconds()
            logger.error(
                "Engine cycle failed",
                worker_id=self.worker_id,
                error=str(e),
                error_type=type(e).__name__,
                elapsed_seconds=round(elapsed, 3),
            )

    def _setup_signal_handlers(self):
        def signal_handler(signum, frame):
            logger.info("Shutdown signal received", signal=signum)
            self._shutdown_event.set()

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

    async def _heartbeat_loop(self):
        """独立心跳协程：每 HEARTBEAT_INTERVAL_SECONDS 秒续期一次

        与评估周期解耦，确保 TTL=15s 不会被 30s 评估周期撑爆
        """
        while not self._shutdown_event.is_set():
            try:
                await self.sharding.heartbeat()
            except Exception as e:
                logger.warning("Heartbeat failed", worker_id=self.worker_id, error=str(e))
            try:
                await asyncio.wait_for(
                    self._shutdown_event.wait(),
                    timeout=HEARTBEAT_INTERVAL_SECONDS,
                )
            except asyncio.TimeoutError:
                continue

    async def start(self):
        if self.is_running:
            logger.warning("Engine already running")
            return

        configure_logging(settings.LOG_LEVEL)
        logger.info(
            "Engine starting",
            worker_id=self.worker_id,
            interval_seconds=self.interval_seconds,
            concurrency=self.concurrency,
            loki_url=settings.LOKI_URL,
        )

        # 启动即注册心跳，避免首轮被排除
        await self.sharding.heartbeat()

        # 启动独立心跳协程
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

        # P3：启动前补偿扫 pending 通知
        try:
            recovered = await recover_pending_notifications()
            logger.info("Notification recovery done", worker_id=self.worker_id, recovered=recovered)
        except Exception as e:
            logger.warning("Notification recovery failed", worker_id=self.worker_id, error=str(e))

        # P3：启动 N 个通知消费者协程
        self._notifier_tasks = [
            asyncio.create_task(notifier_worker(self._shutdown_event))
            for _ in range(self.notifier_workers)
        ]
        logger.info("Notifier workers started", count=self.notifier_workers)

        self.scheduler = AsyncIOScheduler()
        self.scheduler.add_job(
            self._execute_cycle,
            trigger=IntervalTrigger(seconds=self.interval_seconds),
            id="rule_evaluation",
            name="Rule Evaluation Cycle",
            max_instances=1,
            coalesce=True,
        )
        self._setup_signal_handlers()
        self.scheduler.start()
        self.is_running = True
        logger.info("Engine started successfully", worker_id=self.worker_id)

        await self._execute_cycle()
        await self._shutdown_event.wait()
        await self.stop()

    async def stop(self):
        if not self.is_running:
            return
        logger.info("Engine stopping", worker_id=self.worker_id)
        self._shutdown_event.set()
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except (asyncio.CancelledError, Exception):
                pass
        # 等通知消费者自然退出（有 1s 超时轮询）
        for t in self._notifier_tasks:
            try:
                await asyncio.wait_for(t, timeout=3.0)
            except (asyncio.TimeoutError, asyncio.CancelledError, Exception):
                t.cancel()
        if self.scheduler:
            self.scheduler.shutdown(wait=True)
        try:
            await self.sharding.unregister()
        except Exception as e:
            logger.warning("Failed to unregister heartbeat", error=str(e))
        await close_redis_pool()
        self.is_running = False
        logger.info("Engine stopped", worker_id=self.worker_id)


async def main():
    import os
    concurrency = int(os.getenv("ENGINE_CONCURRENCY", DEFAULT_CONCURRENCY))
    worker = EngineWorker(concurrency=concurrency)
    await worker.start()


if __name__ == "__main__":
    asyncio.run(main())
