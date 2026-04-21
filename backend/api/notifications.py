"""
通知查询 API —— 支持按 status 过滤（pending/sent/failed），分页
"""
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import Notification
from schemas.notification import NotificationItem, NotificationListResponse

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


@router.get("", response_model=NotificationListResponse)
async def list_notifications(
    status: Optional[str] = Query(None, description="过滤状态：pending / sent / failed"),
    alert_id: Optional[int] = Query(None, description="按 alert_id 过滤"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """查询通知记录列表（按 notified_at DESC，为空时按 created_at DESC）"""
    filters = []
    if status:
        filters.append(Notification.status == status)
    if alert_id is not None:
        filters.append(Notification.alert_id == alert_id)

    # 总数
    count_stmt = select(func.count(Notification.id))
    if filters:
        count_stmt = count_stmt.where(*filters)
    total = (await db.execute(count_stmt)).scalar_one()

    # 分页数据：notified_at 可能为空（pending），用 coalesce 回落到 created_at
    order_col = func.coalesce(Notification.notified_at, Notification.created_at)
    stmt = (
        select(Notification)
        .order_by(desc(order_col))
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    if filters:
        stmt = stmt.where(*filters)

    items = (await db.execute(stmt)).scalars().all()

    return NotificationListResponse(
        total=total,
        page=page,
        page_size=page_size,
        items=[NotificationItem.model_validate(n) for n in items],
    )
