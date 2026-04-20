from datetime import datetime, timezone, timedelta
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from sqlalchemy.orm import selectinload

from models import Rule, Alert
from engine.loki_client import LokiClient, LogEntry
from engine.alert_manager import AlertManager
from engine.window_counter import WindowCounter
from engine.sequence_state_manager import SequenceStateManager
from engine.logger import get_logger
from notifier.console import ConsoleNotifier

logger = get_logger(__name__)


class RuleEvaluator:
    """规则评估器"""

    def __init__(self, db: AsyncSession, loki_client: Optional[LokiClient] = None):
        self.db = db
        self.loki_client = loki_client or LokiClient()
        self.window_counters: dict[int, WindowCounter] = {}

    async def load_enabled_rules(self) -> List[Rule]:
        """加载已启用的规则（含序列步骤）"""
        result = await self.db.execute(
            select(Rule)
            .options(selectinload(Rule.steps))
            .where(Rule.enabled == True)
        )
        rules = result.scalars().all()
        logger.debug("Loaded enabled rules", count=len(rules))
        return list(rules)

    async def evaluate_rule(self, rule: Rule) -> bool:
        """评估单条规则，按 rule_type 分发"""
        try:
            if rule.rule_type == "sequence":
                return await self._evaluate_sequence(rule)
            else:
                return await self._evaluate_single_condition(rule)
        except Exception as e:
            logger.error(
                "Rule evaluation failed",
                rule_id=rule.id,
                rule_name=rule.name,
                error=str(e),
                error_type=type(e).__name__,
            )
            return False

    # ------------------------------------------------------------------ #
    # 单条件评估（原有逻辑，keyword / threshold）
    # ------------------------------------------------------------------ #

    async def _evaluate_single_condition(self, rule: Rule) -> bool:
        end_time = datetime.now(timezone.utc)
        start_time = rule.last_query_time if rule.last_query_time else end_time - timedelta(minutes=5)

        logger.debug(
            "Evaluating single-condition rule",
            rule_id=rule.id,
            rule_name=rule.name,
        )

        entries = await self._query_logs(rule, start_time, end_time)
        matched_entries = await self._match_rule(rule, entries, end_time)

        logger.info(
            "Rule evaluated",
            rule_id=rule.id,
            rule_name=rule.name,
            rule_type="window" if rule.window_seconds > 0 else "keyword",
            total_logs=len(entries),
            matched=len(matched_entries),
        )

        alert_generated = False
        if matched_entries:
            alert_manager = AlertManager(self.db)
            alert = await alert_manager.create_or_update_alert(rule, matched_entries)
            alert_generated = alert is not None
            if alert:
                await self._handle_notification(alert, rule, alert_manager)

        await self._update_last_query_time(rule.id, end_time)
        return alert_generated

    # ------------------------------------------------------------------ #
    # 序列评估（新增）
    # ------------------------------------------------------------------ #

    async def _evaluate_sequence(self, rule: Rule) -> bool:
        """评估序列规则，维护 SequenceState 状态机"""
        steps = sorted(rule.steps, key=lambda s: s.step_order)
        if len(steps) < 2:
            logger.warning("Sequence rule has fewer than 2 steps, skipping", rule_id=rule.id)
            return False

        mgr = SequenceStateManager(self.db)
        state = await mgr.load_or_create(rule.id)

        now = datetime.now(timezone.utc)

        # 1. 超时检查：当前步骤等待超时则重置
        if state.current_step > 0 and mgr.is_expired(state):
            logger.debug("Sequence state expired, checking negative correlation", rule_id=rule.id)

            if rule.correlation_type == "negative":
                # 否定关联：A 命中后超时未出现 B → 触发告警
                alert_generated = await self._fire_sequence_alert(rule, state, steps)
            else:
                alert_generated = False

            await mgr.reset(state)
            await mgr.save(state)
            return alert_generated

        # 2. 按 current_step 查询对应步骤
        current_idx = state.current_step
        if current_idx >= len(steps):
            # 状态异常，重置
            await mgr.reset(state)
            await mgr.save(state)
            return False

        step = steps[current_idx]
        end_time = now
        start_time = (
            rule.last_query_time if rule.last_query_time and current_idx == 0
            else end_time - timedelta(seconds=step.window_seconds)
        )

        entries = await self._query_logs(rule, start_time, end_time)
        matched = self._match_step(step, entries)

        logger.info(
            "Sequence step evaluated",
            rule_id=rule.id,
            step=current_idx,
            total_logs=len(entries),
            matched=len(matched),
        )

        alert_generated = False

        if matched:
            # 步骤命中，推进状态
            await mgr.advance(state, step, now)

            if state.current_step >= len(steps):
                # 所有步骤完成
                if rule.correlation_type == "sequence":
                    # 顺序关联：全部命中 → 告警
                    alert_generated = await self._fire_sequence_alert(rule, state, steps)
                # negative 类型全部命中 → 不告警（B出现了，不需要告警）
                await mgr.reset(state)
        # else: 步骤未命中，状态不变，等待下一轮

        await mgr.save(state)
        await self._update_last_query_time(rule.id, now)
        return alert_generated

    async def _fire_sequence_alert(self, rule: Rule, state, steps) -> bool:
        """触发序列告警"""
        # 使用最后一个已命中步骤的日志作为 sample
        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(seconds=60)
        last_step = steps[min(state.current_step, len(steps)) - 1]
        entries = await self._query_logs(rule, start_time, end_time)
        matched = self._match_step(last_step, entries) or entries[:1]

        alert_manager = AlertManager(self.db)
        alert = await alert_manager.create_or_update_alert(rule, matched)
        if alert:
            await self._handle_notification(alert, rule, alert_manager)
            return True
        return False

    def _match_step(self, step, entries: List[LogEntry]) -> List[LogEntry]:
        """匹配单个序列步骤"""
        if step.match_type == "contains":
            return [e for e in entries if step.match_pattern in e.content]
        elif step.match_type == "regex":
            import re
            try:
                pattern = re.compile(step.match_pattern)
                return [e for e in entries if pattern.search(e.content)]
            except re.error:
                return []
        return []

    # ------------------------------------------------------------------ #
    # 共用工具函数
    # ------------------------------------------------------------------ #

    async def _query_logs(self, rule: Rule, start_time: datetime, end_time: datetime) -> List[LogEntry]:
        return await self.loki_client.query_range(
            namespace=rule.selector_namespace,
            start_time=start_time,
            end_time=end_time,
            labels=rule.selector_labels,
            limit=1000,
        )

    async def _match_rule(self, rule: Rule, entries: List[LogEntry], current_time: datetime) -> List[LogEntry]:
        keyword_matched = self._match_keyword(rule, entries)
        if rule.window_seconds > 0:
            return await self._match_window_threshold(rule, keyword_matched, current_time)
        return keyword_matched

    async def _match_window_threshold(self, rule: Rule, matched_entries: List[LogEntry], current_time: datetime) -> List[LogEntry]:
        if rule.id not in self.window_counters:
            self.window_counters[rule.id] = WindowCounter(rule.window_seconds)
        counter = self.window_counters[rule.id]
        for entry in matched_entries:
            counter.add(entry.timestamp)
        window_count = counter.count(current_time)
        if window_count >= rule.threshold:
            logger.debug("Window threshold met", rule_id=rule.id, window_count=window_count, threshold=rule.threshold)
            return matched_entries
        logger.debug("Window threshold not met", rule_id=rule.id, window_count=window_count, threshold=rule.threshold)
        return []

    def _match_keyword(self, rule: Rule, entries: List[LogEntry]) -> List[LogEntry]:
        if rule.match_type == "contains":
            return self._match_contains(rule.match_pattern, entries)
        elif rule.match_type == "regex":
            logger.warning("Regex match not implemented yet", rule_id=rule.id, rule_name=rule.name)
            return []
        logger.error("Unknown match type", rule_id=rule.id, match_type=rule.match_type)
        return []

    def _match_contains(self, pattern: str, entries: List[LogEntry]) -> List[LogEntry]:
        return [e for e in entries if pattern in e.content]

    async def _update_last_query_time(self, rule_id: int, query_time: datetime):
        await self.db.execute(
            update(Rule)
            .where(Rule.id == rule_id)
            .values(last_query_time=query_time, updated_at=datetime.now(timezone.utc))
        )
        await self.db.commit()

    async def _handle_notification(self, alert: Alert, rule: Rule, alert_manager: AlertManager):
        if not self.should_notify(alert, rule):
            logger.info("Notification skipped (cooldown active)", alert_id=alert.id, rule_id=rule.id)
            return
        notifier = ConsoleNotifier()
        try:
            result = await notifier.send(alert, rule.name)
            import json
            if result["success"]:
                await alert_manager.record_notification(
                    alert=alert, channel="console",
                    content=json.dumps(result["content"], ensure_ascii=False), success=True,
                )
                logger.info("Notification sent successfully", alert_id=alert.id, rule_id=rule.id)
            else:
                await alert_manager.record_notification(
                    alert=alert, channel="console", content="", success=False,
                    error_message=result.get("error", "Unknown error"),
                )
                logger.error("Notification failed", alert_id=alert.id, error=result.get("error"))
        except Exception as e:
            logger.error("Notification error", alert_id=alert.id, error=str(e))

    def should_notify(self, alert: Alert, rule: Rule) -> bool:
        if alert.last_notified_at is None:
            return True
        now = datetime.now(timezone.utc)
        last_notified = alert.last_notified_at
        if last_notified.tzinfo is None:
            last_notified = last_notified.replace(tzinfo=timezone.utc)
        return (now - last_notified).total_seconds() >= rule.cooldown_seconds
