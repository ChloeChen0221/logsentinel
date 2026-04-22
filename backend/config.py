"""
配置管理模块
使用 pydantic-settings 管理环境变量
"""
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator
from typing import List, Union
from pathlib import Path
import json

# 获取 backend 目录的绝对路径
BACKEND_DIR = Path(__file__).parent


class Settings(BaseSettings):
    """应用配置"""
    
    # 基础配置
    APP_NAME: str = "LogSentinel"
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"
    
    # 数据库配置（PostgreSQL via asyncpg）
    DATABASE_URL: str = "postgresql+asyncpg://logsentinel:logsentinel@localhost:5432/logsentinel"
    DB_POOL_SIZE: int = 20
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_RECYCLE: int = 3600

    # Redis 配置
    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_PASSWORD: str = ""  # 若非空，运行时注入到 REDIS_URL userinfo 部分（Secret 提供）
    REDIS_POOL_MAX_CONN: int = 50
    
    # Loki 配置
    LOKI_URL: str = "http://localhost:3100"
    LOKI_TIMEOUT: int = 5
    
    # 引擎配置
    ENGINE_INTERVAL_SECONDS: int = 30
    
    # CORS 配置
    CORS_ORIGINS: List[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]
    
    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: Union[str, List[str]]) -> List[str]:
        """支持从 JSON 字符串或列表解析 CORS_ORIGINS"""
        if isinstance(v, str):
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                # 支持逗号分隔格式
                return [origin.strip() for origin in v.split(",")]
        return v
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True
    )


settings = Settings()
