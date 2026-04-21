"""
Loki HTTP 客户端（P3 改造：aiohttp + aiolimiter + Redis 缓存 + 指数退避重试）

D6 决策：
- aiohttp ClientSession 单例（连接池复用）
- AsyncLimiter(50, 1) 本地令牌桶（副本级 QPS 限流）
- Redis STRING 缓存（key=loki:{md5(query+start+end)}, TTL 10s）
- 3 次指数退避重试（1s / 2s / 4s）
- 结构化日志：query_hash, cache_hit, duration_ms, status, rule_id
"""
import asyncio
import hashlib
import json
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import aiohttp
from aiolimiter import AsyncLimiter
from redis.asyncio import Redis

from config import settings
from database.redis import get_redis_client
from engine.logger import get_logger

logger = get_logger(__name__)


class LokiQueryError(Exception):
    """Loki 查询错误"""
    pass


class LogEntry:
    """日志条目"""

    def __init__(
        self,
        timestamp: datetime,
        content: str,
        namespace: str,
        pod: str,
        container: Optional[str] = None,
    ):
        self.timestamp = timestamp
        self.content = content
        self.namespace = namespace
        self.pod = pod
        self.container = container

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat() + "Z",
            "content": self.content,
            "namespace": self.namespace,
            "pod": self.pod,
            "container": self.container,
        }


# 副本本地 QPS 限流：每秒 50 次（整体 QPS = 50 × Worker 副本数）
_DEFAULT_RATE = 50
_DEFAULT_PER = 1.0
# Redis 缓存 TTL
_CACHE_TTL_SECONDS = 10
# 重试配置
_MAX_RETRIES = 3
_RETRY_BACKOFFS = [1.0, 2.0, 4.0]


class LokiClient:
    """Loki HTTP 异步客户端"""

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: int = 5,
        redis: Optional[Redis] = None,
        rate: int = _DEFAULT_RATE,
        per: float = _DEFAULT_PER,
    ):
        self.base_url = base_url or settings.LOKI_URL
        self.timeout = timeout
        self._redis = redis  # 懒加载：None 则调用时走 get_redis_client()
        self._limiter = AsyncLimiter(rate, per)
        self._session: Optional[aiohttp.ClientSession] = None

    @property
    def redis(self) -> Redis:
        if self._redis is None:
            self._redis = get_redis_client()
        return self._redis

    async def _get_session(self) -> aiohttp.ClientSession:
        """懒加载共享 ClientSession"""
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=self.timeout)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    # ------------------------------------------------------------------ #
    # 查询入口
    # ------------------------------------------------------------------ #

    async def query_range(
        self,
        namespace: str,
        start_time: datetime,
        end_time: datetime,
        labels: Optional[Dict[str, str]] = None,
        keyword: Optional[str] = None,
        limit: int = 1000,
        rule_id: Optional[int] = None,
    ) -> List[LogEntry]:
        """查询指定时间范围的日志（支持缓存/限流/重试）"""
        query = self._build_query(namespace, labels, keyword)
        start_ns = int(start_time.timestamp() * 1e9)
        end_ns = int(end_time.timestamp() * 1e9)

        cache_key, query_hash = self._cache_key(query, start_ns, end_ns, limit)
        t0 = time.monotonic()

        # 1. 缓存命中直接返回
        cached = await self._get_cache(cache_key)
        if cached is not None:
            duration_ms = int((time.monotonic() - t0) * 1000)
            logger.info(
                "loki_query",
                rule_id=rule_id,
                query_hash=query_hash,
                cache_hit=True,
                duration_ms=duration_ms,
                status="ok",
            )
            return self._parse_response(cached)

        # 2. 限流等待 + 重试
        params = {
            "query": query,
            "start": str(start_ns),
            "end": str(end_ns),
            "limit": str(limit),
            "direction": "forward",
        }
        url = f"{self.base_url}/loki/api/v1/query_range"

        data = await self._request_with_retry(url, params, rule_id, query_hash)
        await self._set_cache(cache_key, data)

        duration_ms = int((time.monotonic() - t0) * 1000)
        logger.info(
            "loki_query",
            rule_id=rule_id,
            query_hash=query_hash,
            cache_hit=False,
            duration_ms=duration_ms,
            status="ok",
        )
        return self._parse_response(data)

    async def _request_with_retry(
        self,
        url: str,
        params: Dict[str, str],
        rule_id: Optional[int],
        query_hash: str,
    ) -> Dict[str, Any]:
        last_err: Optional[Exception] = None
        for attempt in range(_MAX_RETRIES):
            try:
                async with self._limiter:
                    session = await self._get_session()
                    async with session.get(url, params=params) as resp:
                        if resp.status >= 500:
                            text = await resp.text()
                            raise LokiQueryError(f"Loki 5xx: {resp.status} - {text[:200]}")
                        if resp.status >= 400:
                            text = await resp.text()
                            # 4xx 不重试（客户端错误，重试无用）
                            raise LokiQueryError(f"Loki {resp.status}: {text[:200]}")
                        return await resp.json()
            except asyncio.TimeoutError as e:
                last_err = LokiQueryError(f"Loki 查询超时: {e}")
            except aiohttp.ClientError as e:
                last_err = LokiQueryError(f"Loki 连接异常: {e}")
            except LokiQueryError as e:
                # 4xx 直接抛，不重试
                if "4" in str(e).split(":", 1)[0][-3:]:
                    logger.warning(
                        "loki_query",
                        rule_id=rule_id,
                        query_hash=query_hash,
                        cache_hit=False,
                        status="client_error",
                        error=str(e),
                    )
                    raise
                last_err = e

            # 可重试错误：记日志 + 退避
            backoff = _RETRY_BACKOFFS[min(attempt, len(_RETRY_BACKOFFS) - 1)]
            logger.warning(
                "loki_query_retry",
                rule_id=rule_id,
                query_hash=query_hash,
                attempt=attempt + 1,
                backoff_seconds=backoff,
                error=str(last_err),
            )
            if attempt < _MAX_RETRIES - 1:
                await asyncio.sleep(backoff)

        assert last_err is not None
        logger.error(
            "loki_query",
            rule_id=rule_id,
            query_hash=query_hash,
            cache_hit=False,
            status="failed",
            error=str(last_err),
        )
        raise last_err

    # ------------------------------------------------------------------ #
    # 缓存
    # ------------------------------------------------------------------ #

    @staticmethod
    def _cache_key(query: str, start_ns: int, end_ns: int, limit: int) -> tuple:
        raw = f"{query}|{start_ns}|{end_ns}|{limit}".encode("utf-8")
        h = hashlib.md5(raw).hexdigest()
        return f"loki:{h}", h

    async def _get_cache(self, key: str) -> Optional[Dict[str, Any]]:
        try:
            raw = await self.redis.get(key)
        except Exception as e:
            logger.warning("loki_cache_get_failed", key=key, error=str(e))
            return None
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    async def _set_cache(self, key: str, data: Dict[str, Any]) -> None:
        try:
            await self.redis.set(key, json.dumps(data), ex=_CACHE_TTL_SECONDS)
        except Exception as e:
            logger.warning("loki_cache_set_failed", key=key, error=str(e))

    # ------------------------------------------------------------------ #
    # 工具
    # ------------------------------------------------------------------ #

    def _build_query(
        self,
        namespace: str,
        labels: Optional[Dict[str, str]] = None,
        keyword: Optional[str] = None,
    ) -> str:
        query_parts = [f'namespace="{namespace}"']
        if labels:
            for key, value in labels.items():
                query_parts.append(f'{key}="{value}"')
        query = "{" + ", ".join(query_parts) + "}"
        if keyword:
            query += f' |= "{keyword}"'
        return query

    def _parse_response(self, response: Dict[str, Any]) -> List[LogEntry]:
        entries: List[LogEntry] = []

        if response.get("status") != "success":
            raise LokiQueryError(f"Loki 响应状态异常: {response.get('status')}")

        result_data = response.get("data", {})
        results = result_data.get("result", [])

        for result in results:
            stream = result.get("stream", {})
            values = result.get("values", [])

            for value in values:
                if len(value) < 2:
                    continue
                timestamp_ns = int(value[0])
                timestamp = datetime.fromtimestamp(timestamp_ns / 1e9, tz=timezone.utc)
                content = value[1]

                entry = LogEntry(
                    timestamp=timestamp,
                    content=content,
                    namespace=stream.get("namespace", ""),
                    pod=stream.get("pod", ""),
                    container=stream.get("container"),
                )
                entries.append(entry)

        return entries
