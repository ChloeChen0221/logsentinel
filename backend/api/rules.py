from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete
from sqlalchemy.orm import selectinload
from typing import List, Optional
from datetime import datetime

from database import get_db
from models import Rule, RuleStep
from schemas import RuleCreate, RuleUpdate, RuleResponse

router = APIRouter(prefix="/api/rules", tags=["rules"])


async def _load_rule_with_steps(db: AsyncSession, rule_id: int) -> Optional[Rule]:
    result = await db.execute(
        select(Rule).options(selectinload(Rule.steps)).where(Rule.id == rule_id)
    )
    return result.scalar_one_or_none()


@router.get("", response_model=List[RuleResponse])
async def get_rules(
    enabled: Optional[bool] = None,
    db: AsyncSession = Depends(get_db)
):
    """查询规则列表（含步骤）"""
    query = select(Rule).options(selectinload(Rule.steps))
    if enabled is not None:
        query = query.where(Rule.enabled == enabled)
    result = await db.execute(query)
    return result.scalars().all()


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
        rule_type=rule_data.rule_type,
        correlation_type=rule_data.correlation_type,
    )
    db.add(rule)
    await db.flush()  # 获取 rule.id

    if rule_data.rule_type == "sequence" and rule_data.steps:
        for step_data in rule_data.steps:
            step = RuleStep(
                rule_id=rule.id,
                step_order=step_data.step_order,
                match_type=step_data.match_type,
                match_pattern=step_data.match_pattern,
                window_seconds=step_data.window_seconds,
                threshold=step_data.threshold,
            )
            db.add(step)

    await db.commit()
    return await _load_rule_with_steps(db, rule.id)


@router.get("/{rule_id}", response_model=RuleResponse)
async def get_rule(
    rule_id: int,
    db: AsyncSession = Depends(get_db)
):
    """查询规则详情（含步骤）"""
    rule = await _load_rule_with_steps(db, rule_id)
    if not rule:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="规则不存在")
    return rule


@router.put("/{rule_id}", response_model=RuleResponse)
async def update_rule(
    rule_id: int,
    rule_data: RuleUpdate,
    db: AsyncSession = Depends(get_db)
):
    """更新规则（含步骤替换）"""
    rule = await _load_rule_with_steps(db, rule_id)
    if not rule:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="规则不存在")

    update_data = rule_data.model_dump(exclude_unset=True, exclude={"steps"})
    for field, value in update_data.items():
        setattr(rule, field, value)
    rule.updated_at = datetime.utcnow()

    # 如果提交了 steps，删旧建新
    if rule_data.steps is not None:
        await db.execute(delete(RuleStep).where(RuleStep.rule_id == rule_id))
        for step_data in rule_data.steps:
            step = RuleStep(
                rule_id=rule_id,
                step_order=step_data.step_order,
                match_type=step_data.match_type,
                match_pattern=step_data.match_pattern,
                window_seconds=step_data.window_seconds,
                threshold=step_data.threshold,
            )
            db.add(step)

    await db.commit()
    return await _load_rule_with_steps(db, rule_id)


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rule(
    rule_id: int,
    db: AsyncSession = Depends(get_db)
):
    """删除规则（级联删除关联告警、步骤、序列状态）"""
    rule = await _load_rule_with_steps(db, rule_id)
    if not rule:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="规则不存在")
    await db.delete(rule)
    await db.commit()


@router.patch("/{rule_id}/enable", response_model=RuleResponse)
async def enable_rule(
    rule_id: int,
    db: AsyncSession = Depends(get_db)
):
    """启用规则"""
    rule = await _load_rule_with_steps(db, rule_id)
    if not rule:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="规则不存在")
    rule.enabled = True
    rule.updated_at = datetime.utcnow()
    await db.commit()
    return await _load_rule_with_steps(db, rule_id)


@router.patch("/{rule_id}/disable", response_model=RuleResponse)
async def disable_rule(
    rule_id: int,
    db: AsyncSession = Depends(get_db)
):
    """停用规则"""
    rule = await _load_rule_with_steps(db, rule_id)
    if not rule:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="规则不存在")
    rule.enabled = False
    rule.updated_at = datetime.utcnow()
    await db.commit()
    return await _load_rule_with_steps(db, rule_id)
