"""
Notifier 注册表：type -> Notifier 实例
"""
from __future__ import annotations

from typing import Dict

from notifier.base import BaseNotifier
from notifier.console import ConsoleNotifier
from notifier.wecom import WecomNotifier


_NOTIFIERS: Dict[str, BaseNotifier] = {
    "console": ConsoleNotifier(),
    "wecom": WecomNotifier(),
}


def get_notifier(channel_type: str) -> BaseNotifier | None:
    return _NOTIFIERS.get(channel_type)


def supported_types() -> list[str]:
    return list(_NOTIFIERS.keys())
