"""
通知相关 Pydantic schema
"""
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, computed_field


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
    channel_config: Optional[Dict[str, Any]] = None

    @computed_field  # type: ignore[misc]
    @property
    def channel_name(self) -> Optional[str]:
        if self.channel_config and isinstance(self.channel_config, dict):
            return self.channel_config.get("name")
        return None

    model_config = {"from_attributes": True}


class NotificationListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: List[NotificationItem]
