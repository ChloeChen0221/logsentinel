"""
企微 Markdown 消息格式化

严重度 → 企微 font color 映射：
  critical/high → warning（橙红）
  medium        → comment（灰）
  low/info      → info（绿）

消息总长度硬限 4096 字节，超长时优先截断 sample_log。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from typing import Any, Dict

from models import Alert


# 企微 markdown content 字节上限
_WECOM_MARKDOWN_LIMIT = 4096
# 样本日志最多展示字节数（给模板其他部分留出预算）
_SAMPLE_LOG_MAX_BYTES = 1200
# 告警时间统一按东八区展示（与前端一致）
_CST = timezone(timedelta(hours=8))


def _fmt_cst(dt: datetime | None) -> str:
    if not dt:
        return "-"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_CST).strftime("%Y-%m-%d %H:%M:%S")


def _color_for(severity: str) -> str:
    s = (severity or "").lower()
    if s in ("critical", "high", "error"):
        return "warning"
    if s == "medium" or s == "warning":
        return "comment"
    return "info"


def _severity_label(severity: str) -> str:
    s = (severity or "").lower()
    if s == "critical":
        return "严重"
    if s == "high":
        return "高"
    if s == "medium":
        return "中"
    if s == "low":
        return "低"
    return s or "info"


def _truncate_bytes(text: str, max_bytes: int) -> str:
    """按字节截断（UTF-8），尾部加 ...(truncated)"""
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    # 留 15 字节给 "...(truncated)"
    cut = encoded[: max(0, max_bytes - 16)]
    # 回退到合法 UTF-8 边界
    while cut and (cut[-1] & 0xC0) == 0x80:
        cut = cut[:-1]
    return cut.decode("utf-8", errors="ignore") + "...(truncated)"


def _format_group_by(group_by: Any) -> str:
    if not group_by:
        return "-"
    if isinstance(group_by, dict):
        return " ".join(f"{k}={v}" for k, v in group_by.items() if v)
    return str(group_by)


def _format_sample(sample: Any) -> str:
    if not sample:
        return "-"
    if isinstance(sample, dict):
        # sample_log 通常含 {content, namespace, pod, timestamp}
        text = sample.get("content") or json.dumps(sample, ensure_ascii=False)
    else:
        text = str(sample)
    return _truncate_bytes(text, _SAMPLE_LOG_MAX_BYTES)


def build_markdown(alert: Alert, rule_name: str) -> str:
    """构造企微 markdown 正文"""
    color = _color_for(alert.severity)
    label = _severity_label(alert.severity)

    first_seen = _fmt_cst(alert.first_seen)
    last_seen = _fmt_cst(alert.last_seen)

    lines = [
        f'# <font color="{color}">[{label}]</font> {rule_name}',
        "",
        f"**规则 ID**: {alert.rule_id}",
        f"**告警 ID**: {alert.id}",
        f"**命中**: <font color=\"{color}\">{alert.hit_count} 次</font>",
        f"**首次**: {first_seen} CST",
        f"**最近**: {last_seen} CST",
        f"**分组**: {_format_group_by(alert.group_by)}",
        "",
        "**样本日志**:",
        f"> {_format_sample(alert.sample_log)}",
    ]
    content = "\n".join(lines)
    # 整体兜底截断
    return _truncate_bytes(content, _WECOM_MARKDOWN_LIMIT)


def build_mention_text(mobiles: list[str]) -> str | None:
    """构造伴随 @消息（企微 markdown 不支持 at，所以用单独 text 消息伴随）"""
    if not mobiles:
        return None
    parts = []
    for m in mobiles:
        parts.append("@所有人" if m == "@all" else f"@{m}")
    return " ".join(parts)
