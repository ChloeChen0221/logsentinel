from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Optional

from database import get_db
from models import SequenceState
from schemas import SequenceStateResponse

router = APIRouter(prefix="/api/sequence-states", tags=["sequence-states"])


@router.get("", response_model=List[SequenceStateResponse])
async def get_sequence_states(
    rule_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db)
):
    """查询序列状态（可按 rule_id 过滤）"""
    query = select(SequenceState)
    if rule_id is not None:
        query = query.where(SequenceState.rule_id == rule_id)
    result = await db.execute(query)
    return result.scalars().all()
