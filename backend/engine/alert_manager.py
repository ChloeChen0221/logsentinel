"""
告警管理器
负责告警生成、去重、合并
"""
import hashlib
import json
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from models import Rule, Alert, Notification
from engine.loki_client import LogEntry
from engine.logger import get_logger
from database.redis import get_redis_client

logger = get_logger(__name__)


ALERTS_CHANNEL = "alerts:new"


async def _publish_alert(alert: Alert) -> None:
    """事务提交后 PUBLISH 到 Redis pub/sub（供 API 副本的 WebSocket 订阅）"""
    try:
        redis = get_redis_client()
        payload = json.dumps({
            "id": alert.id,
            "rule_id": alert.rule_id,
            "fingerprint": alert.fingerprint,
            "severity": alert.severity,
            "status": alert.status,
            "hit_count": alert.hit_count,
            "last_seen": alert.last_seen.isoformat() if alert.last_seen else None,
            "group_by": alert.group_by or {},
        }, ensure_ascii=False)
        await redis.publish(ALERTS_CHANNEL, payload)
    except Exception as e:
        # 失败不影响告警落库，前端重连时可通过 REST 补齐
        logger.warning("alert_publish_failed", alert_id=alert.id, error=str(e))


class AlertManager:
    """告警管理器"""
    
    def __init__(self, db: AsyncSession):
        """
        初始化管理器
        
        Args:
            db: 数据库会话
        """
        self.db = db
    
    def generate_fingerprint(
        self,
        rule_id: int,
        group_by_values: Dict[str, str]
    ) -> str:
        """
        生成告警指纹
        
        Args:
            rule_id: 规则 ID
            group_by_values: 分组维度值
        
        Returns:
            SHA256 指纹
        """
        # 构造指纹输入：rule_id + 排序后的分组维度值
        fingerprint_input = {
            "rule_id": rule_id,
            "group_by": dict(sorted(group_by_values.items()))
        }
        
        # 转换为 JSON 字符串
        fingerprint_str = json.dumps(fingerprint_input, sort_keys=True)
        
        # 计算 SHA256 哈希
        fingerprint = hashlib.sha256(fingerprint_str.encode()).hexdigest()
        
        return fingerprint
    
    def extract_group_by_values(
        self,
        entry: LogEntry,
        group_by: List[str]
    ) -> Dict[str, str]:
        """
        从日志条目中提取分组维度值
        
        Args:
            entry: 日志条目
            group_by: 分组维度列表
        
        Returns:
            分组维度值字典
        """
        values = {}
        
        for dimension in group_by:
            if dimension == "namespace":
                values["namespace"] = entry.namespace
            elif dimension == "pod":
                values["pod"] = entry.pod
            elif dimension == "container" and entry.container:
                values["container"] = entry.container
        
        return values
    
    async def create_or_update_alert(
        self,
        rule: Rule,
        matched_entries: List[LogEntry]
    ) -> Optional[Alert]:
        """
        创建或更新告警
        
        Args:
            rule: 规则对象
            matched_entries: 匹配的日志条目列表
        
        Returns:
            告警对象（如果有匹配的日志）
        """
        if not matched_entries:
            return None
        
        # 使用最新的日志作为样例
        latest_entry = matched_entries[-1]
        
        # 提取分组维度值
        group_by_values = self.extract_group_by_values(latest_entry, rule.group_by)
        
        # 生成指纹
        fingerprint = self.generate_fingerprint(rule.id, group_by_values)
        
        # 查询是否已存在同一指纹的告警
        result = await self.db.execute(
            select(Alert).where(Alert.fingerprint == fingerprint)
        )
        existing_alert = result.scalar_one_or_none()
        
        now = datetime.now(timezone.utc)
        
        if existing_alert:
            # 更新现有告警
            existing_alert.last_seen = now
            existing_alert.hit_count += len(matched_entries)
            existing_alert.sample_log = latest_entry.to_dict()
            existing_alert.updated_at = now
            
            await self.db.commit()
            await self.db.refresh(existing_alert)
            
            logger.info(
                "Alert updated",
                alert_id=existing_alert.id,
                rule_id=rule.id,
                fingerprint=fingerprint,
                hit_count=existing_alert.hit_count
            )

            # P3：事务提交后 PUBLISH 通知 WebSocket 订阅者
            await _publish_alert(existing_alert)

            return existing_alert
        else:
            # 创建新告警
            alert = Alert(
                rule_id=rule.id,
                fingerprint=fingerprint,
                severity=rule.severity,
                status="active",
                first_seen=now,
                last_seen=now,
                hit_count=len(matched_entries),
                group_by=group_by_values,
                sample_log=latest_entry.to_dict()
            )
            
            self.db.add(alert)
            await self.db.commit()
            await self.db.refresh(alert)
            
            logger.info(
                "Alert created",
                alert_id=alert.id,
                rule_id=rule.id,
                rule_name=rule.name,
                fingerprint=fingerprint,
                severity=rule.severity,
                hit_count=alert.hit_count
            )

            # P3：事务提交后 PUBLISH 通知 WebSocket 订阅者
            await _publish_alert(alert)

            return alert
    
    async def record_notification(
        self,
        alert: Alert,
        channel: str,
        content: str,
        success: bool,
        error_message: Optional[str] = None
    ) -> Notification:
        """
        记录通知历史
        
        Args:
            alert: 告警对象
            channel: 通知渠道
            content: 通知内容
            success: 是否成功
            error_message: 错误信息（如果失败）
        
        Returns:
            通知记录对象
        """
        now = datetime.now(timezone.utc)
        
        # 创建通知记录
        # 注：当前仍是同步直发模式（沿用 MVP 行为），故跳过 pending 直接落终态。
        # P3 改造（asyncio.Queue + 补偿扫表）后，入队时将先写 pending、消费者再 CAS 更新到 sent/failed。
        notification = Notification(
            alert_id=alert.id,
            notified_at=now,
            channel=channel,
            content=content,
            status="sent" if success else "failed",
            error_message=error_message,
        )
        
        self.db.add(notification)
        
        # 更新告警的 last_notified_at
        if success:
            alert.last_notified_at = now
            alert.updated_at = now
        
        await self.db.commit()
        await self.db.refresh(notification)
        
        logger.info(
            "Notification recorded",
            notification_id=notification.id,
            alert_id=alert.id,
            channel=channel,
            status=notification.status
        )
        
        return notification