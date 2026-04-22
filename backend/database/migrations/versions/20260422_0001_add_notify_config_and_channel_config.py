"""add notify_config and channel_config

Revision ID: 20260422_0001
Revises: 20260420_0001
Create Date: 2026-04-22

为企微通知多渠道扇出方案新增两个 JSONB 字段：
- rules.notify_config: 规则维度的渠道列表
- notifications.channel_config: 触发时的渠道快照
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260422_0001"
down_revision: Union[str, Sequence[str], None] = "20260420_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "rules",
        sa.Column(
            "notify_config",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "notifications",
        sa.Column(
            "channel_config",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("notifications", "channel_config")
    op.drop_column("rules", "notify_config")
