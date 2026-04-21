FROM python:3.11-slim

WORKDIR /app

# 安装系统依赖（curl 用于健康检查；libpq-dev/gcc 用于编译 asyncpg）
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖文件
COPY requirements.txt .

# 安装 Python 依赖
RUN pip install --no-cache-dir -r requirements.txt

# 复制源码
COPY . .

# 环境变量默认值（DATABASE_URL/REDIS_URL 由 compose / Helm 注入）
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    LOG_LEVEL=INFO \
    LOKI_URL=http://loki:3100 \
    ENGINE_INTERVAL_SECONDS=30

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

EXPOSE 8000

# 默认启动 API 服务（compose 会用 entrypoint 先跑 alembic 迁移）
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
