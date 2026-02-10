"""
规则管理 API
提供规则 CRUD 和启停功能
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete
from typing import List, Optional
from datetime import datetime

from database import get_db
from models import Rule
from schemas import RuleCreate, RuleUpdate, RuleResponse

router = APIRouter(prefix="/api/rules", tags=["rules"])


@router.get("", response_model=List[RuleResponse])
async def get_rules(
    enabled: Optional[bool] = None,
    db: AsyncSession = Depends(get_db)
):
    """
    查询规则列表
    支持按启用状态筛选
    """
    query = select(Rule)
    
    if enabled is not None:
        query = query.where(Rule.enabled == enabled)
    
    result = await db.execute(query)
    rules = result.scalars().all()
    
    return rules


@router.post("", response_model=RuleResponse, status_code=status.HTTP_201_CREATED)
async def create_rule(
    rule_data: RuleCreate,
    db: AsyncSession = Depends(get_db)
):
    """创建规则"""
    rule = Rule(
        name=rule_data.name,
        enabled=rule_data.enabled,
        severity=rule_data.severity,
        selector_namespace=rule_data.selector_namespace,
        selector_labels=rule_data.selector_labels,
        match_type=rule_data.match_type,
        match_pattern=rule_data.match_pattern,
        window_seconds=rule_data.window_seconds,
        threshold=rule_data.threshold,
        group_by=rule_data.group_by,
        cooldown_seconds=rule_data.cooldown_seconds,
    )
    
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    
    return rule


@router.get("/{rule_id}", response_model=RuleResponse)
async def get_rule(
    rule_id: int,
    db: AsyncSession = Depends(get_db)
):
    """查询规则详情"""
    result = await db.execute(select(Rule).where(Rule.id == rule_id))
    rule = result.scalar_one_or_none()
    
    if not rule:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="规则不存在"
        )
    
    return rule


@router.put("/{rule_id}", response_model=RuleResponse)
async def update_rule(
    rule_id: int,
    rule_data: RuleUpdate,
    db: AsyncSession = Depends(get_db)
):
    """更新规则"""
    result = await db.execute(select(Rule).where(Rule.id == rule_id))
    rule = result.scalar_one_or_none()
    
    if not rule:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="规则不存在"
        )
    
    # 更新字段
    update_data = rule_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(rule, field, value)
    
    rule.updated_at = datetime.utcnow()
    
    await db.commit()
    await db.refresh(rule)
    
    return rule


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rule(
    rule_id: int,
    db: AsyncSession = Depends(get_db)
):
    """删除规则（级联删除关联的告警）"""
    result = await db.execute(select(Rule).where(Rule.id == rule_id))
    rule = result.scalar_one_or_none()
    
    if not rule:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="规则不存在"
        )
    
    await db.delete(rule)
    await db.commit()


@router.patch("/{rule_id}/enable", response_model=RuleResponse)
async def enable_rule(
    rule_id: int,
    db: AsyncSession = Depends(get_db)
):
    """启用规则"""
    result = await db.execute(select(Rule).where(Rule.id == rule_id))
    rule = result.scalar_one_or_none()
    
    if not rule:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="规则不存在"
        )
    
    rule.enabled = True
    rule.updated_at = datetime.utcnow()
    
    await db.commit()
    await db.refresh(rule)
    
    return rule


@router.patch("/{rule_id}/disable", response_model=RuleResponse)
async def disable_rule(
    rule_id: int,
    db: AsyncSession = Depends(get_db)
):
    """停用规则"""
    result = await db.execute(select(Rule).where(Rule.id == rule_id))
    rule = result.scalar_one_or_none()
    
    if not rule:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="规则不存在"
        )
    
    rule.enabled = False
    rule.updated_at = datetime.utcnow()
    
    await db.commit()
    await db.refresh(rule)
    
    return rule
