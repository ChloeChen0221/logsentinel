"""
规则评估器
加载规则、查询日志、执行匹配逻辑
"""
from datetime import datetime, timezone, timedelta
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from models import Rule, Alert
from engine.loki_client import LokiClient, LogEntry
from engine.alert_manager import AlertManager
from engine.window_counter import WindowCounter
from engine.logger import get_logger
from notifier.console import ConsoleNotifier

logger = get_logger(__name__)


class RuleEvaluator:
    """规则评估器"""
    
    def __init__(self, db: AsyncSession, loki_client: Optional[LokiClient] = None):
        """
        初始化评估器
        
        Args:
            db: 数据库会话
            loki_client: Loki 客户端（可选，用于测试注入）
        """
        self.db = db
        self.loki_client = loki_client or LokiClient()
        # 窗口计数器字典（key: rule_id, value: WindowCounter）
        self.window_counters: dict[int, WindowCounter] = {}
    
    async def load_enabled_rules(self) -> List[Rule]:
        """
        从数据库加载已启用的规则
        
        Returns:
            已启用的规则列表
        """
        result = await self.db.execute(
            select(Rule).where(Rule.enabled == True)
        )
        rules = result.scalars().all()
        
        logger.debug("Loaded enabled rules", count=len(rules))
        return list(rules)
    
    async def evaluate_rule(self, rule: Rule) -> bool:
        """
        评估单条规则
        
        Args:
            rule: 规则对象
        
        Returns:
            是否生成了告警
        """
        # 确定查询时间范围
        end_time = datetime.now(timezone.utc)
        
        if rule.last_query_time:
            start_time = rule.last_query_time
        else:
            # 首次查询：查询最近 5 分钟
            start_time = end_time - timedelta(minutes=5)
        
        logger.debug(
            "Evaluating rule",
            rule_id=rule.id,
            rule_name=rule.name,
            start_time=start_time.isoformat(),
            end_time=end_time.isoformat()
        )
        
        try:
            # 查询 Loki
            entries = await self._query_logs(rule, start_time, end_time)
            
            # 执行规则匹配（关键词或窗口阈值）
            matched_entries = await self._match_rule(rule, entries, end_time)
            
            match_count = len(matched_entries)
            
            logger.info(
                "Rule evaluated",
                rule_id=rule.id,
                rule_name=rule.name,
                rule_type="window" if rule.window_seconds > 0 else "keyword",
                total_logs=len(entries),
                matched=match_count
            )
            
            # 生成或更新告警
            alert_generated = False
            if matched_entries:
                alert_manager = AlertManager(self.db)
                alert = await alert_manager.create_or_update_alert(rule, matched_entries)
                alert_generated = alert is not None
                
                # 处理通知
                if alert:
                    await self._handle_notification(alert, rule, alert_manager)
            
            # 更新 last_query_time（仅成功时更新）
            await self._update_last_query_time(rule.id, end_time)
            
            return alert_generated
            
        except Exception as e:
            logger.error(
                "Rule evaluation failed",
                rule_id=rule.id,
                rule_name=rule.name,
                error=str(e),
                error_type=type(e).__name__
            )
            # 失败时不更新 last_query_time，下次重试
            return False
    
    async def _query_logs(
        self,
        rule: Rule,
        start_time: datetime,
        end_time: datetime
    ) -> List[LogEntry]:
        """
        从 Loki 查询日志
        
        Args:
            rule: 规则对象
            start_time: 起始时间
            end_time: 结束时间
        
        Returns:
            日志条目列表
        """
        entries = await self.loki_client.query_range(
            namespace=rule.selector_namespace,
            start_time=start_time,
            end_time=end_time,
            labels=rule.selector_labels,
            limit=1000
        )
        
        return entries
    
    async def _match_rule(
        self,
        rule: Rule,
        entries: List[LogEntry],
        current_time: datetime
    ) -> List[LogEntry]:
        """
        执行规则匹配
        
        Args:
            rule: 规则对象
            entries: 日志条目列表
            current_time: 当前时间
        
        Returns:
            匹配的日志条目列表
        """
        # 首先执行关键词匹配
        keyword_matched = self._match_keyword(rule, entries)
        
        # 如果是窗口阈值规则，进一步检查窗口内计数
        if rule.window_seconds > 0:
            return await self._match_window_threshold(rule, keyword_matched, current_time)
        else:
            # 关键词规则：所有匹配的日志都算
            return keyword_matched
    
    async def _match_window_threshold(
        self,
        rule: Rule,
        matched_entries: List[LogEntry],
        current_time: datetime
    ) -> List[LogEntry]:
        """
        执行窗口阈值匹配
        
        Args:
            rule: 规则对象
            matched_entries: 关键词匹配的日志条目
            current_time: 当前时间
        
        Returns:
            满足阈值条件的日志条目列表
        """
        # 获取或创建窗口计数器
        if rule.id not in self.window_counters:
            self.window_counters[rule.id] = WindowCounter(rule.window_seconds)
        
        counter = self.window_counters[rule.id]
        
        # 将所有匹配的日志时间戳添加到计数器
        for entry in matched_entries:
            counter.add(entry.timestamp)
        
        # 检查窗口内的计数是否达到阈值
        window_count = counter.count(current_time)
        
        if window_count >= rule.threshold:
            logger.debug(
                "Window threshold met",
                rule_id=rule.id,
                window_count=window_count,
                threshold=rule.threshold
            )
            return matched_entries
        else:
            logger.debug(
                "Window threshold not met",
                rule_id=rule.id,
                window_count=window_count,
                threshold=rule.threshold
            )
            return []
    
    def _match_keyword(self, rule: Rule, entries: List[LogEntry]) -> List[LogEntry]:
        """
        执行关键词匹配
        
        Args:
            rule: 规则对象
            entries: 日志条目列表
        
        Returns:
            匹配的日志条目列表
        """
        if rule.match_type == "contains":
            return self._match_contains(rule.match_pattern, entries)
        elif rule.match_type == "regex":
            # TODO: T009 仅实现 contains，regex 在后续实现
            logger.warning(
                "Regex match not implemented yet",
                rule_id=rule.id,
                rule_name=rule.name
            )
            return []
        else:
            logger.error(
                "Unknown match type",
                rule_id=rule.id,
                match_type=rule.match_type
            )
            return []
    
    def _match_contains(self, pattern: str, entries: List[LogEntry]) -> List[LogEntry]:
        """
        关键词包含匹配
        
        Args:
            pattern: 关键词
            entries: 日志条目列表
        
        Returns:
            匹配的日志条目列表
        """
        matched = []
        
        for entry in entries:
            if pattern in entry.content:
                matched.append(entry)
        
        return matched
    
    async def _update_last_query_time(self, rule_id: int, query_time: datetime):
        """
        更新规则的 last_query_time
        
        Args:
            rule_id: 规则 ID
            query_time: 查询时间
        """
        await self.db.execute(
            update(Rule)
            .where(Rule.id == rule_id)
            .values(
                last_query_time=query_time,
                updated_at=datetime.now(timezone.utc)
            )
        )
        await self.db.commit()
    
    async def _handle_notification(
        self,
        alert: Alert,
        rule: Rule,
        alert_manager: AlertManager
    ):
        """
        处理告警通知（含冷却期检查）
        
        Args:
            alert: 告警对象
            rule: 规则对象
            alert_manager: 告警管理器实例
        """
        # 检查是否需要发送通知（冷却期检查）
        if not self.should_notify(alert, rule):
            logger.info(
                "Notification skipped (cooldown active)",
                alert_id=alert.id,
                rule_id=rule.id,
                rule_name=rule.name,
                hit_count=alert.hit_count
            )
            return
        
        # 发送通知
        notifier = ConsoleNotifier()
        try:
            result = await notifier.send(alert, rule.name)
            
            if result["success"]:
                # 记录通知历史
                import json
                await alert_manager.record_notification(
                    alert=alert,
                    channel="console",
                    content=json.dumps(result["content"], ensure_ascii=False),
                    success=True
                )
                
                logger.info(
                    "Notification sent successfully",
                    alert_id=alert.id,
                    rule_id=rule.id,
                    rule_name=rule.name,
                    channel="console"
                )
            else:
                # 记录失败的通知
                await alert_manager.record_notification(
                    alert=alert,
                    channel="console",
                    content="",
                    success=False,
                    error_message=result.get("error", "Unknown error")
                )
                
                logger.error(
                    "Notification failed",
                    alert_id=alert.id,
                    rule_id=rule.id,
                    error=result.get("error")
                )
        
        except Exception as e:
            logger.error(
                "Notification error",
                alert_id=alert.id,
                rule_id=rule.id,
                error=str(e),
                error_type=type(e).__name__
            )
    
    def should_notify(self, alert: Alert, rule: Rule) -> bool:
        """
        判断是否应该发送通知（冷却期检查）
        
        Args:
            alert: 告警对象
            rule: 规则对象
        
        Returns:
            是否应该发送通知
        """
        # 首次触发（未发送过通知）
        if alert.last_notified_at is None:
            logger.debug(
                "First notification",
                alert_id=alert.id,
                rule_id=rule.id
            )
            return True
        
        # 检查冷却期
        now = datetime.now(timezone.utc)
        
        # 确保 last_notified_at 有时区信息
        last_notified = alert.last_notified_at
        if last_notified.tzinfo is None:
            last_notified = last_notified.replace(tzinfo=timezone.utc)
        
        time_since_last_notification = (now - last_notified).total_seconds()
        
        if time_since_last_notification >= rule.cooldown_seconds:
            logger.debug(
                "Cooldown period ended",
                alert_id=alert.id,
                rule_id=rule.id,
                time_since_last=time_since_last_notification,
                cooldown_seconds=rule.cooldown_seconds
            )
            return True
        else:
            logger.debug(
                "In cooldown period",
                alert_id=alert.id,
                rule_id=rule.id,
                time_since_last=time_since_last_notification,
                cooldown_seconds=rule.cooldown_seconds
            )
            return False