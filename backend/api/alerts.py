"""
告警管理 API
提供告警列表和详情查询
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc
from typing import Optional

from database import get_db
from models import Alert, Rule
from schemas.alert import AlertResponse, AlertListResponse

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


@router.get("", response_model=AlertListResponse)
async def get_alerts(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    severity: Optional[str] = Query(None, description="筛选严重级别"),
    rule_id: Optional[int] = Query(None, description="筛选规则 ID"),
    db: AsyncSession = Depends(get_db)
):
    """
    查询告警列表
    支持分页和筛选
    """
    # 构建基础查询
    query = select(Alert)
    
    # 应用筛选条件
    if severity:
        query = query.where(Alert.severity == severity)
    
    if rule_id:
        query = query.where(Alert.rule_id == rule_id)
    
    # 默认按 last_seen 倒序排列
    query = query.order_by(desc(Alert.last_seen))
    
    # 计算总数
    count_query = select(func.count()).select_from(Alert)
    if severity:
        count_query = count_query.where(Alert.severity == severity)
    if rule_id:
        count_query = count_query.where(Alert.rule_id == rule_id)
    
    result = await db.execute(count_query)
    total = result.scalar()
    
    # 分页
    offset = (page - 1) * page_size
    query = query.offset(offset).limit(page_size)
    
    # 执行查询
    result = await db.execute(query)
    alerts = result.scalars().all()
    
    return AlertListResponse(
        total=total,
        page=page,
        page_size=page_size,
        items=list(alerts)
    )


@router.get("/{alert_id}", response_model=AlertResponse)
async def get_alert(
    alert_id: int,
    db: AsyncSession = Depends(get_db)
):
    """查询告警详情"""
    result = await db.execute(select(Alert).where(Alert.id == alert_id))
    alert = result.scalar_one_or_none()
    
    if not alert:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="告警不存在"
        )
    
    return alert
