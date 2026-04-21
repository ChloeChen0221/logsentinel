"""initial schema for pg

Revision ID: 20260420_0001
Revises:
Create Date: 2026-04-20 20:30:00

包含全部 5 个表：rules / rule_steps / sequence_states / alerts / notifications
注：本迁移为手工版（无可用 PG 实例做 autogenerate），按 backend/models 当前定义编排。
首次接入真实 PG 后建议执行一次 `alembic check` 校验是否与 models 同步。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260420_0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ---------------- rules ----------------
    op.create_table(
        "rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("selector_namespace", sa.String(length=255), nullable=False),
        sa.Column("selector_labels", postgresql.JSONB(), nullable=True),
        sa.Column("match_type", sa.String(length=20), nullable=False),
        sa.Column("match_pattern", sa.Text(), nullable=False),
        sa.Column("window_seconds", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("threshold", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("group_by", postgresql.JSONB(), nullable=False),
        sa.Column("cooldown_seconds", sa.Integer(), nullable=False, server_default="300"),
        sa.Column("last_query_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("rule_type", sa.String(length=20), nullable=False, server_default="keyword"),
        sa.Column("correlation_type", sa.String(length=20), nullable=True),
    )
    op.create_index("ix_rules_enabled", "rules", ["enabled"])
    op.create_index("ix_rules_enabled_last_query_time", "rules", ["enabled", "last_query_time"])

    # ---------------- rule_steps ----------------
    op.create_table(
        "rule_steps",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("rule_id", sa.Integer(), sa.ForeignKey("rules.id", ondelete="CASCADE"), nullable=False),
        sa.Column("step_order", sa.Integer(), nullable=False),
        sa.Column("match_type", sa.String(length=20), nullable=False),
        sa.Column("match_pattern", sa.Text(), nullable=False),
        sa.Column("window_seconds", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("threshold", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_index("ix_rule_steps_rule_id", "rule_steps", ["rule_id"])

    # ---------------- sequence_states ----------------
    op.create_table(
        "sequence_states",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("rule_id", sa.Integer(), sa.ForeignKey("rules.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("current_step", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("step_timestamps", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_sequence_states_rule_id", "sequence_states", ["rule_id"])

    # ---------------- alerts ----------------
    op.create_table(
        "alerts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("rule_id", sa.Integer(), sa.ForeignKey("rules.id", ondelete="CASCADE"), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False, unique=True),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("first_seen", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=False),
        sa.Column("hit_count", sa.BigInteger(), nullable=False, server_default="1"),
        sa.Column("group_by", postgresql.JSONB(), nullable=False),
        sa.Column("sample_log", postgresql.JSONB(), nullable=False),
        sa.Column("last_notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_alerts_fingerprint", "alerts", ["fingerprint"], unique=True)
    op.create_index("ix_alerts_rule_id_last_seen", "alerts", ["rule_id", "last_seen"])

    # ---------------- notifications ----------------
    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("alert_id", sa.Integer(), sa.ForeignKey("alerts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("channel", sa.String(length=50), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_notifications_alert_id_notified_at", "notifications", ["alert_id", "notified_at"])
    op.create_index("ix_notifications_status_created_at", "notifications", ["status", "created_at"])


def downgrade() -> None:
    # 反向 drop 顺序：先有外键依赖的表，后被依赖的表
    op.drop_index("ix_notifications_status_created_at", table_name="notifications")
    op.drop_index("ix_notifications_alert_id_notified_at", table_name="notifications")
    op.drop_table("notifications")

    op.drop_index("ix_alerts_rule_id_last_seen", table_name="alerts")
    op.drop_index("ix_alerts_fingerprint", table_name="alerts")
    op.drop_table("alerts")

    op.drop_index("ix_sequence_states_rule_id", table_name="sequence_states")
    op.drop_table("sequence_states")

    op.drop_index("ix_rule_steps_rule_id", table_name="rule_steps")
    op.drop_table("rule_steps")

    op.drop_index("ix_rules_enabled_last_query_time", table_name="rules")
    op.drop_index("ix_rules_enabled", table_name="rules")
    op.drop_table("rules")
