"""
分组 fingerprint 计算

用于按 (rule_id, group_by_values) 区分窗口计数器、告警实例。
- group_by 为空时使用 {} 作为单一默认分组（与有分组场景代码路径一致）
- 同一规则 + 同一分组值集合 → 同一 fingerprint
"""
import hashlib
import json
from typing import Any, Dict, Mapping, Optional


def compute_fingerprint(rule_id: int, group_values: Optional[Mapping[str, Any]] = None) -> str:
    """计算分组 fingerprint

    Args:
        rule_id: 规则 ID
        group_values: 分组键值（如 {"namespace": "prod"}）；None/空 dict 视作单一默认分组

    Returns:
        16 字节 hex 字符串（SHA256 前 16 字节足够避免冲突且节省 Redis Key 长度）
    """
    normalized: Dict[str, Any] = dict(group_values) if group_values else {}
    payload = {
        "rule_id": rule_id,
        "group": {k: normalized[k] for k in sorted(normalized.keys())},
    }
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:32]
