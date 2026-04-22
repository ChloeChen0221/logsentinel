"""
通知渠道工具接口：测试发送
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from notifier.wecom import send_wecom_payload


router = APIRouter(prefix="/api/channels", tags=["channels"])


_WECOM_PREFIX = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send"


class WecomTestRequest(BaseModel):
    webhook_url: str = Field(..., description="企微 webhook URL")
    mentioned_mobile_list: Optional[List[str]] = Field(default_factory=list)

    @field_validator("webhook_url")
    @classmethod
    def _validate_url(cls, v: str) -> str:
        if not v.startswith(_WECOM_PREFIX):
            raise ValueError(f"webhook_url 必须以 {_WECOM_PREFIX} 开头")
        if "key=" not in v:
            raise ValueError("webhook_url 必须包含 key 参数")
        return v


@router.post("/test")
async def test_wecom_channel(req: WecomTestRequest):
    """同步发送一条测试消息到 webhook，不入库不入队"""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    content = f"LogSentinel 连通性测试 {now}"
    mentions = req.mentioned_mobile_list or []
    payload = {
        "msgtype": "text",
        "text": {
            "content": content,
            **({"mentioned_mobile_list": mentions} if mentions else {}),
        },
    }
    result = await send_wecom_payload(req.webhook_url, payload)
    if result["success"]:
        return {"success": True, "errcode": 0, "errmsg": "ok"}
    raise HTTPException(
        status_code=400,
        detail={
            "success": False,
            "errcode": result.get("errcode"),
            "errmsg": result.get("errmsg"),
        },
    )
