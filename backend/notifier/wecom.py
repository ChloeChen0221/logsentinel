"""
企业微信群机器人 Notifier

限流设计（双层）：
- 主：Redis ZSET 滑动窗口（wecom:rl:{url_key}），所有副本共享 → 总速率 ≤ 20/60s
- 兜底：进程内 AsyncLimiter(20, 60)，Redis 故障时 fail-open 使用
- 并发控制：Per-URL asyncio.Semaphore(2)，规避企微 45033 并发超限

errcode：0 成功；45009 速率超限；45033 并发超限；其他 != 0 不重试
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Any, Dict, Optional

import aiohttp
from aiolimiter import AsyncLimiter
from redis.exceptions import RedisError

from database.redis import get_redis_client
from engine.logger import get_logger
from models import Alert
from notifier import rate_limiter
from notifier.base import BaseNotifier
from notifier.formatter import build_markdown, build_mention_text


logger = get_logger(__name__)


# 企微官方限速：20 次 / 60 秒 / 机器人
_WECOM_RATE_LIMIT = 20
_WECOM_RATE_PERIOD = 60
# 单进程对同一 webhook 的并发上限（规避 45033）
_WECOM_CONCURRENCY = 2
# HTTP 超时（发送 + 连接）
_HTTP_TIMEOUT = aiohttp.ClientTimeout(total=10, connect=5)

# Per-URL 兜底限流器（Redis 故障时启用）
_fallback_limiters: Dict[str, AsyncLimiter] = {}
# Per-URL 并发信号量
_semaphores: Dict[str, asyncio.Semaphore] = {}
_session: Optional[aiohttp.ClientSession] = None
_session_lock = asyncio.Lock()


def _url_key(url: str) -> str:
    return hashlib.md5(url.encode("utf-8")).hexdigest()[:12]


def _get_fallback_limiter(url_key: str) -> AsyncLimiter:
    if url_key not in _fallback_limiters:
        _fallback_limiters[url_key] = AsyncLimiter(_WECOM_RATE_LIMIT, _WECOM_RATE_PERIOD)
    return _fallback_limiters[url_key]


def _get_semaphore(url_key: str) -> asyncio.Semaphore:
    if url_key not in _semaphores:
        _semaphores[url_key] = asyncio.Semaphore(_WECOM_CONCURRENCY)
    return _semaphores[url_key]


async def _acquire_rate_limit(url_key: str) -> None:
    """分布式限流 acquire，Redis 异常时 fail-open 到进程内 AsyncLimiter"""
    try:
        redis = get_redis_client()
        await rate_limiter.acquire(redis, url_key)
        return
    except (RedisError, asyncio.TimeoutError, ConnectionError, OSError) as e:
        logger.warning(
            "wecom_ratelimit_fallback",
            url_key=url_key,
            error=str(e),
        )
    # 兜底：进程内限流
    await _get_fallback_limiter(url_key).acquire()


async def _get_session() -> aiohttp.ClientSession:
    global _session
    if _session is None or _session.closed:
        async with _session_lock:
            if _session is None or _session.closed:
                _session = aiohttp.ClientSession(timeout=_HTTP_TIMEOUT)
    return _session


async def _post_json(webhook_url: str, payload: dict) -> Dict[str, Any]:
    """单次 POST，返回 {success, retriable, errcode, errmsg, http_status}

    不做模块外的重试/限流（限流由调用方 acquire）。
    """
    key = _url_key(webhook_url)
    try:
        session = await _get_session()
        async with session.post(webhook_url, json=payload) as resp:
            status = resp.status
            text = await resp.text()
            if status >= 500:
                return {
                    "success": False,
                    "retriable": True,
                    "errcode": -1,
                    "errmsg": f"http {status}",
                    "http_status": status,
                    "raw": text[:200],
                }
            if 400 <= status < 500:
                return {
                    "success": False,
                    "retriable": False,
                    "errcode": -1,
                    "errmsg": f"http {status}",
                    "http_status": status,
                    "raw": text[:200],
                }
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                return {
                    "success": False,
                    "retriable": False,
                    "errcode": -1,
                    "errmsg": "invalid json response",
                    "http_status": status,
                    "raw": text[:200],
                }
            errcode = data.get("errcode", -1)
            errmsg = data.get("errmsg", "")
            if errcode == 0:
                return {"success": True, "retriable": False, "errcode": 0, "errmsg": errmsg}
            if errcode == 45009:
                # 速率超限：调用方应走长 backoff
                return {
                    "success": False,
                    "retriable": True,
                    "errcode": 45009,
                    "errmsg": errmsg or "rate limit reached",
                }
            if errcode == 45033:
                # 并发超限：可重试，调用方走短 backoff
                return {
                    "success": False,
                    "retriable": True,
                    "errcode": 45033,
                    "errmsg": errmsg or "api concurrent out of limit",
                }
            # 其他业务错误（鉴权/参数）不重试
            return {
                "success": False,
                "retriable": False,
                "errcode": errcode,
                "errmsg": errmsg or "wecom error",
            }
    except asyncio.TimeoutError:
        logger.warning("wecom_post_timeout", url_key=key)
        return {"success": False, "retriable": True, "errcode": -1, "errmsg": "timeout"}
    except aiohttp.ClientError as e:
        logger.warning("wecom_post_client_error", url_key=key, error=str(e))
        return {"success": False, "retriable": True, "errcode": -1, "errmsg": str(e)}


async def send_wecom_payload(webhook_url: str, payload: dict) -> Dict[str, Any]:
    """对外暴露：分布式限流 + 并发 Semaphore + 单次发送。供测试接口复用。"""
    url_key = _url_key(webhook_url)
    # 1) 分布式速率限流（fail-open 到进程内 AsyncLimiter）
    await _acquire_rate_limit(url_key)
    # 2) 并发控制（规避 45033）
    async with _get_semaphore(url_key):
        return await _post_json(webhook_url, payload)


class WecomNotifier(BaseNotifier):
    """企业微信群机器人通知器"""

    async def send(
        self,
        alert: Alert,
        rule_name: str,
        channel_config: Dict[str, Any],
    ) -> Dict[str, Any]:
        webhook_url = channel_config.get("webhook_url")
        if not webhook_url:
            return {
                "success": False,
                "retriable": False,
                "content": {},
                "error": "missing webhook_url",
                "errcode": -1,
            }
        markdown = build_markdown(alert, rule_name)
        payload = {"msgtype": "markdown", "markdown": {"content": markdown}}

        url_key = _url_key(webhook_url)
        result = await send_wecom_payload(webhook_url, payload)
        logger.info(
            "wecom_send",
            url_key=url_key,
            rule_id=alert.rule_id,
            alert_id=alert.id,
            success=result["success"],
            errcode=result.get("errcode"),
        )
        if not result["success"]:
            return {
                "success": False,
                "retriable": result["retriable"],
                "content": {},
                "error": f"errcode={result.get('errcode')} {result.get('errmsg', '')}".strip(),
                "errcode": result.get("errcode"),
            }

        # 主消息发送成功后，追加 @ 消息（若配置了）
        mentions = channel_config.get("mentioned_mobile_list") or []
        mention_text = build_mention_text(mentions)
        if mention_text:
            mention_payload = {
                "msgtype": "text",
                "text": {
                    "content": mention_text,
                    "mentioned_mobile_list": mentions,
                },
            }
            # @ 消息失败不影响整体结果，仅记日志
            r2 = await send_wecom_payload(webhook_url, mention_payload)
            if not r2["success"]:
                logger.warning(
                    "wecom_mention_failed",
                    url_key=url_key,
                    errcode=r2.get("errcode"),
                    errmsg=r2.get("errmsg"),
                )

        return {
            "success": True,
            "retriable": False,
            "content": {
                "channel": "wecom",
                "channel_name": channel_config.get("name"),
                "markdown_bytes": len(markdown.encode("utf-8")),
            },
            "error": None,
            "errcode": 0,
        }


async def close_session() -> None:
    """应用关闭时调用（optional）"""
    global _session
    if _session and not _session.closed:
        await _session.close()
        _session = None
