"""
通知相关 Pydantic schema
"""
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel


class NotificationItem(BaseModel):
    id: int
    alert_id: int
    channel: str
    status: str
    retry_count: int
    content: Optional[str] = None
    error_message: Optional[str] = None
    notified_at: Optional[datetime] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class NotificationListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: List[NotificationItem]
