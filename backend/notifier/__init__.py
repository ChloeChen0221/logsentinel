"""
通知模块
"""
from notifier.base import BaseNotifier
from notifier.console import ConsoleNotifier

__all__ = ["BaseNotifier", "ConsoleNotifier"]
