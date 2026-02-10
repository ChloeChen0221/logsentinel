"""
规则引擎主循环
使用 APScheduler 定时执行规则评估
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
from engine.evaluator import RuleEvaluator

logger = get_logger(__name__)


class EngineWorker:
    """规则引擎 Worker"""
    
    def __init__(self, interval_seconds: Optional[int] = None):
        """
        初始化 Worker
        
        Args:
            interval_seconds: 执行间隔（秒），默认从配置读取
        """
        self.interval_seconds = interval_seconds or settings.ENGINE_INTERVAL_SECONDS
        self.scheduler: Optional[AsyncIOScheduler] = None
        self.is_running = False
        self._shutdown_event = asyncio.Event()
    
    async def _execute_cycle(self):
        """
        执行一轮规则评估循环
        """
        start_time = datetime.now(timezone.utc)
        
        logger.info(
            "Engine cycle started",
            cycle_time=start_time.isoformat()
        )
        
        try:
            # 加载并评估规则
            async with AsyncSessionLocal() as db:
                evaluator = RuleEvaluator(db)
                rules = await evaluator.load_enabled_rules()
                rule_count = len(rules)
                
                # 评估每条规则
                for rule in rules:
                    try:
                        await evaluator.evaluate_rule(rule)
                    except Exception as e:
                        logger.error(
                            "Rule evaluation error",
                            rule_id=rule.id,
                            rule_name=rule.name,
                            error=str(e)
                        )
            
            elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
            
            logger.info(
                "Engine cycle completed",
                rule_count=rule_count,
                elapsed_seconds=round(elapsed, 3)
            )
            
        except Exception as e:
            elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
            logger.error(
                "Engine cycle failed",
                error=str(e),
                error_type=type(e).__name__,
                elapsed_seconds=round(elapsed, 3)
            )
    
    def _setup_signal_handlers(self):
        """设置信号处理器（用于优雅停止）"""
        def signal_handler(signum, frame):
            logger.info("Shutdown signal received", signal=signum)
            self._shutdown_event.set()
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
    
    async def start(self):
        """启动引擎"""
        if self.is_running:
            logger.warning("Engine already running")
            return
        
        # 配置日志
        configure_logging(settings.LOG_LEVEL)
        
        logger.info(
            "Engine starting",
            interval_seconds=self.interval_seconds,
            loki_url=settings.LOKI_URL
        )
        
        # 创建调度器
        self.scheduler = AsyncIOScheduler()
        
        # 添加定时任务
        self.scheduler.add_job(
            self._execute_cycle,
            trigger=IntervalTrigger(seconds=self.interval_seconds),
            id="rule_evaluation",
            name="Rule Evaluation Cycle",
            max_instances=1,  # 防止并发执行
            coalesce=True     # 合并错过的执行
        )
        
        # 设置信号处理
        self._setup_signal_handlers()
        
        # 启动调度器
        self.scheduler.start()
        self.is_running = True
        
        logger.info("Engine started successfully")
        
        # 立即执行一次
        await self._execute_cycle()
        
        # 等待关闭信号
        await self._shutdown_event.wait()
        
        # 停止引擎
        await self.stop()
    
    async def stop(self):
        """停止引擎"""
        if not self.is_running:
            return
        
        logger.info("Engine stopping")
        
        if self.scheduler:
            self.scheduler.shutdown(wait=True)
        
        self.is_running = False
        logger.info("Engine stopped")


async def main():
    """主函数"""
    worker = EngineWorker()
    await worker.start()


if __name__ == "__main__":
    asyncio.run(main())
