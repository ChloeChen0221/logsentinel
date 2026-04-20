"""
LogSentinel - K8s 日志告警平台
FastAPI 主应用入口
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from config import settings
from database import init_db
from api import rules, alerts
from api import sequence_states


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时初始化数据库
    await init_db()
    yield
    # 关闭时清理资源（目前无需清理）


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


@app.get("/health")
async def health_check():
    """健康检查端点"""
    return {"status": "ok"}


@app.get("/")
async def root():
    """根路径"""
    return {
        "message": "LogSentinel API",
        "version": "1.0.0",
        "docs": "/docs"
    }
