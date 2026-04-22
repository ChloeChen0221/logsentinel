"""
Redis 客户端封装
全局连接池 + FastAPI Depends 注入
"""
from typing import AsyncGenerator, Optional
from urllib.parse import urlparse, urlunparse, quote

from redis.asyncio import ConnectionPool, Redis

from config import settings

_pool: Optional[ConnectionPool] = None


def _resolve_redis_url() -> str:
    """将 REDIS_PASSWORD 注入到 REDIS_URL 的 userinfo；若 URL 已带密码则尊重原配置"""
    url = settings.REDIS_URL
    password = settings.REDIS_PASSWORD
    if not password:
        return url
    parsed = urlparse(url)
    if parsed.password:
        return url
    host = parsed.hostname or "localhost"
    netloc = f"{host}:{parsed.port}" if parsed.port else host
    new_netloc = f":{quote(password, safe='')}@{netloc}"
    return urlunparse(parsed._replace(netloc=new_netloc))


def get_redis_pool() -> ConnectionPool:
    """懒加载全局 Redis 连接池"""
    global _pool
    if _pool is None:
        _pool = ConnectionPool.from_url(
            _resolve_redis_url(),
            max_connections=settings.REDIS_POOL_MAX_CONN,
            decode_responses=True,
        )
    return _pool


def get_redis_client() -> Redis:
    """获取共享 Redis 客户端实例（通过全局连接池）"""
    return Redis(connection_pool=get_redis_pool())


async def get_redis() -> AsyncGenerator[Redis, None]:
    """FastAPI 依赖注入入口"""
    client = get_redis_client()
    try:
        yield client
    finally:
        # 客户端复用全局连接池，连接归还由池管理，无需 close()
        pass


async def close_redis_pool() -> None:
    """应用关闭时回收连接池"""
    global _pool
    if _pool is not None:
        await _pool.disconnect(inuse_connections=True)
        _pool = None
