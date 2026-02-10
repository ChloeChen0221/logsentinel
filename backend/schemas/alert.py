"""
Alert Pydantic Schemas
告警管理 API 的响应模型
"""
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from datetime import datetime


class SampleLog(BaseModel):
    """样例日志"""
    timestamp: str = Field(..., description="日志时间戳")
    content: str = Field(..., description="日志内容")
    namespace: str = Field(..., description="命名空间")
    pod: str = Field(..., description="Pod 名称")
    container: Optional[str] = Field(None, description="容器名称")


class AlertResponse(BaseModel):
    """告警响应（列表项）"""
    id: int
    rule_id: int
    fingerprint: str
    severity: str
    status: str
    first_seen: datetime
    last_seen: datetime
    hit_count: int
    group_by: Dict[str, Any]
    sample_log: Dict[str, Any]
    last_notified_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    
    model_config = {"from_attributes": True}


class AlertListResponse(BaseModel):
    """告警列表响应（带分页）"""
    total: int = Field(..., description="总记录数")
    page: int = Field(..., description="当前页码")
    page_size: int = Field(..., description="每页数量")
    items: list[AlertResponse] = Field(..., description="告警列表")
