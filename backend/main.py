"""
LogSentinel - K8s 日志告警平台
FastAPI 主应用入口
"""
import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from config import settings
from database.redis import close_redis_pool, get_redis_client
from api import rules, alerts
from api import sequence_states
from api import notifications
from api import ws
from api import channels

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理

    P3 改进：Redis 探活失败不再 sys.exit，改为警告后继续启动。
    真正的就绪判定由 K8s readinessProbe（/health）在请求链路上做；不可达时 Probe 失败会把 pod
    从 Service endpoints 摘掉，而不是让容器反复重启。
    """
    redis = get_redis_client()
    try:
        await redis.ping()
        logger.info("redis_ready", url=settings.REDIS_URL)
    except Exception as exc:  # noqa: BLE001
        logger.warning("redis_unreachable_on_startup", error=str(exc))

    yield
    await close_redis_pool()


app = FastAPI(
    title="LogSentinel API",
    description="Kubernetes 日志告警平台 API",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan
)

# 配置 CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(rules.router)
app.include_router(alerts.router)
app.include_router(sequence_states.router)
app.include_router(notifications.router)
app.include_router(ws.router)
app.include_router(channels.router)


@app.get("/health")
async def health_check():
    """健康检查端点 —— 检查 PG + Redis 连通，任一失败返回 503"""
    from database.session import engine as db_engine
    from sqlalchemy import text

    errors = []
    # 探活 Redis
    try:
        redis = get_redis_client()
        await redis.ping()
    except Exception as exc:  # noqa: BLE001
        errors.append(f"redis: {exc}")

    # 探活 PG
    try:
        async with db_engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        errors.append(f"postgres: {exc}")

    if errors:
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=503, content={"status": "unhealthy", "errors": errors})
    return {"status": "ok"}


@app.get("/")
async def root():
    """根路径"""
    return {
        "message": "LogSentinel API",
        "version": "1.0.0",
        "docs": "/docs"
    }
