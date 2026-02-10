# Research & Technical Decisions: MVP 核心闭环

**Feature**: 001-mvp-core-loop  
**Date**: 2026-02-04  
**Phase**: 0 - Outline & Research

## 研究目标

本文档记录 MVP 阶段的关键技术调研与决策，解决实施计划中的技术细节问题。

## 一、Loki 查询最佳实践

### 1.1 LogQL 查询语法

**基础查询**：
```logql
{namespace="demo"} |= "ERROR"
```

**时间范围查询**：
```logql
{namespace="demo"} |= "ERROR" [5m]
```

**标签过滤**：
```logql
{namespace="demo", app="myapp"} |= "ERROR"
```

### 1.2 增量查询策略

**决策**：使用时间范围参数实现增量查询

**实现方式**：
- 每条规则维护 `last_query_time`（存储在数据库）
- 查询时指定 `start` 和 `end` 参数
- 查询完成后更新 `last_query_time` 为本次查询的结束时间

**API 调用示例**：
```python
import httpx
from datetime import datetime, timedelta

async def query_loki(
    loki_url: str,
    query: str,
    start: datetime,
    end: datetime
) -> List[dict]:
    params = {
        "query": query,
        "start": int(start.timestamp() * 1e9),  # 纳秒
        "end": int(end.timestamp() * 1e9),
        "limit": 1000
    }
    
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{loki_url}/loki/api/v1/query_range",
            params=params,
            timeout=5.0
        )
        response.raise_for_status()
        return response.json()["data"]["result"]
```

**理由**：
- 避免重复处理日志
- 控制单次查询范围，降低 Loki 负载
- 支持引擎重启后恢复查询位置

### 1.3 响应数据解析

**Loki 响应格式**：
```json
{
  "data": {
    "result": [
      {
        "stream": {
          "namespace": "demo",
          "pod": "test-pod-123",
          "container": "app"
        },
        "values": [
          ["1738656615123456789", "ERROR: Connection timeout"]
        ]
      }
    ]
  }
}
```

**字段提取**：
- `stream` - 日志标签（namespace、pod、container）
- `values` - 日志条目数组，每项包含 [timestamp, line]
- `timestamp` - 纳秒级时间戳，需转换为 datetime
- `line` - 日志内容

**解析代码**：
```python
from datetime import datetime

def parse_loki_response(response: dict) -> List[LogEntry]:
    entries = []
    
    for result in response["data"]["result"]:
        stream = result["stream"]
        
        for value in result["values"]:
            timestamp_ns = int(value[0])
            line = value[1]
            
            entry = LogEntry(
                timestamp=datetime.fromtimestamp(timestamp_ns / 1e9),
                content=line,
                namespace=stream.get("namespace"),
                pod=stream.get("pod"),
                container=stream.get("container")
            )
            entries.append(entry)
    
    return entries
```

## 二、规则引擎架构决策

### 2.1 引擎运行模式

**选项对比**：

| 选项 | 优点 | 缺点 | 决策 |
|------|------|------|------|
| 独立进程 | 隔离性好，易于扩展 | 部署复杂度高 | ❌ |
| API 同进程后台任务 | 部署简单，共享数据库连接 | 耦合度高 | ✅ |
| Kubernetes CronJob | 云原生，易于调度 | MVP 过度工程化 | ❌ |

**决策**：使用 API 同进程后台任务（APScheduler）

**理由**：
- MVP 阶段优先简单部署
- 单用户场景无需隔离
- 共享数据库连接池，降低资源消耗
- 后续可轻松拆分为独立进程

### 2.2 调度框架选型

**选项对比**：

| 框架 | 优点 | 缺点 | 决策 |
|------|------|------|------|
| APScheduler | 轻量级，支持异步 | 功能相对简单 | ✅ |
| Celery | 功能强大，分布式 | 依赖 Redis/RabbitMQ，过重 | ❌ |
| asyncio.sleep | 零依赖 | 缺乏调度管理 | ❌ |

**决策**：使用 APScheduler

**实现示例**：
```python
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

scheduler = AsyncIOScheduler()

async def engine_loop():
    # 引擎主逻辑
    pass

scheduler.add_job(
    engine_loop,
    trigger=IntervalTrigger(seconds=30),
    id="rule_engine",
    replace_existing=True
)

scheduler.start()
```

**理由**：
- 支持异步任务（与 FastAPI 兼容）
- 轻量级，无需额外中间件
- 支持动态调整调度周期

### 2.3 规则评估并发策略

**决策**：使用 `asyncio.gather()` 并发评估多条规则

**实现示例**：
```python
async def evaluate_all_rules():
    rules = await load_enabled_rules()
    
    tasks = [
        evaluate_single_rule(rule)
        for rule in rules
    ]
    
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    for rule, result in zip(rules, results):
        if isinstance(result, Exception):
            logger.error(f"Rule {rule.id} failed", exc_info=result)
```

**理由**：
- 提高查询效率（多条规则并发查询 Loki）
- 单条规则失败不影响其他规则
- 符合异步编程最佳实践

## 三、数据库设计决策

### 3.1 JSON 字段存储

**场景**：
- `rules.selector_labels` - 标签选择器
- `rules.group_by` - 分组维度
- `alerts.group_by` - 分组维度值
- `alerts.sample_log` - 样例日志

**SQLite JSON 支持**：
- SQLite 3.38+ 支持 JSON 函数
- SQLAlchemy 使用 `JSON` 类型

**示例**：
```python
from sqlalchemy import Column, Integer, JSON
from sqlalchemy.orm import DeclarativeBase

class Base(DeclarativeBase):
    pass

class Rule(Base):
    __tablename__ = "rules"
    
    id = Column(Integer, primary_key=True)
    selector_labels = Column(JSON, nullable=True)
    group_by = Column(JSON, nullable=False)
```

**查询示例**：
```python
# 查询包含特定标签的规则
rules = await session.execute(
    select(Rule).where(
        Rule.selector_labels["app"].astext == "myapp"
    )
)
```

### 3.2 时间戳处理

**决策**：统一使用 UTC 时间，数据库存储 datetime

**SQLAlchemy 配置**：
```python
from sqlalchemy import Column, DateTime
from datetime import datetime

class Alert(Base):
    __tablename__ = "alerts"
    
    first_seen = Column(DateTime, nullable=False, default=datetime.utcnow)
    last_seen = Column(DateTime, nullable=False, default=datetime.utcnow)
```

**前端展示**：
- API 返回 ISO 8601 格式字符串
- 前端使用 `dayjs` 转换为本地时区

### 3.3 索引策略

**必需索引**：
```sql
-- 告警去重查询
CREATE UNIQUE INDEX idx_alerts_fingerprint ON alerts(fingerprint);

-- 告警列表排序
CREATE INDEX idx_alerts_last_seen ON alerts(last_seen DESC);

-- 规则关联查询
CREATE INDEX idx_alerts_rule_id ON alerts(rule_id);

-- 通知历史查询
CREATE INDEX idx_notifications_alert_id ON notifications(alert_id);
```

**理由**：
- `fingerprint` 唯一索引保证去重查询性能
- `last_seen` 索引支持告警列表按时间倒序排列
- 外键索引提升关联查询性能

## 四、前端技术决策

### 4.1 状态管理

**决策**：使用 React Hooks（useState/useEffect），不引入额外状态管理库

**理由**：
- MVP 阶段状态简单（规则列表、告警列表）
- 避免引入 Redux/MobX 增加复杂度
- 后续如需全局状态可引入 Zustand（轻量级）

### 4.2 API 调用封装

**决策**：使用 axios + 自定义 hooks

**实现示例**：
```typescript
// services/api.ts
import axios from 'axios';

const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || 'http://localhost:8000',
  timeout: 5000,
});

export default api;

// services/rules.ts
import api from './api';

export interface Rule {
  id: number;
  name: string;
  enabled: boolean;
  severity: string;
  // ...
}

export const getRules = async (): Promise<Rule[]> => {
  const response = await api.get('/api/rules');
  return response.data;
};

export const createRule = async (rule: Omit<Rule, 'id'>): Promise<Rule> => {
  const response = await api.post('/api/rules', rule);
  return response.data;
};

// hooks/useRules.ts
import { useState, useEffect } from 'react';
import { getRules, Rule } from '../services/rules';

export const useRules = () => {
  const [rules, setRules] = useState<Rule[]>([]);
  const [loading, setLoading] = useState(true);
  
  useEffect(() => {
    const fetchRules = async () => {
      try {
        const data = await getRules();
        setRules(data);
      } finally {
        setLoading(false);
      }
    };
    
    fetchRules();
  }, []);
  
  return { rules, loading };
};
```

### 4.3 UI 组件选型

**决策**：使用 Ant Design 5.x

**核心组件**：
- `Table` - 规则列表、告警列表
- `Form` - 规则创建/编辑表单
- `Modal` - 删除确认、告警详情
- `Button` - 操作按钮
- `Tag` - 严重级别标签
- `Descriptions` - 告警详情展示
- `Pagination` - 分页

**理由**：
- 组件丰富，开箱即用
- 中文文档完善
- 符合宪章 UI 原则

## 五、通知模块设计

### 5.1 接口抽象

**决策**：定义 `BaseNotifier` 抽象类，支持多种通知渠道

**实现示例**：
```python
from abc import ABC, abstractmethod
from typing import Dict, Any

class BaseNotifier(ABC):
    @abstractmethod
    async def send(self, alert: Alert) -> None:
        """发送通知"""
        pass
    
    def format_content(self, alert: Alert) -> Dict[str, Any]:
        """格式化通知内容"""
        return {
            "rule_name": alert.rule.name,
            "severity": alert.severity,
            "triggered_at": alert.last_seen.isoformat(),
            "hit_count": alert.hit_count,
            "sample_log": alert.sample_log
        }

class ConsoleNotifier(BaseNotifier):
    async def send(self, alert: Alert) -> None:
        content = self.format_content(alert)
        logger.info("Alert notification", **content)
```

**理由**：
- 符合开闭原则，易于扩展
- MVP 实现 ConsoleNotifier，后续可添加 EmailNotifier、WebhookNotifier
- 统一的内容格式化逻辑

### 5.2 通知内容格式

**决策**：使用 JSON 格式输出到 structlog

**示例输出**：
```json
{
  "timestamp": "2026-02-04T08:30:15.123Z",
  "level": "info",
  "event": "Alert notification",
  "rule_name": "测试错误告警",
  "severity": "high",
  "triggered_at": "2026-02-04T08:30:15.000Z",
  "hit_count": 5,
  "sample_log": {
    "timestamp": "2026-02-04T08:30:14.500Z",
    "content": "ERROR: Connection timeout",
    "namespace": "demo",
    "pod": "test-pod-123"
  }
}
```

**理由**：
- 结构化日志便于后续分析
- 符合宪章可观测性要求
- 易于扩展到其他通知渠道

## 六、测试策略

### 6.1 单元测试范围

**必需测试**：
- 规则评估逻辑（`engine/evaluator.py`）
  - 关键词匹配
  - 窗口阈值统计
- 告警去重逻辑（`engine/deduplicator.py`）
  - fingerprint 生成
  - 告警合并
- 冷却期判断（`engine/worker.py`）

**测试框架**：pytest + pytest-asyncio

**示例**：
```python
import pytest
from datetime import datetime, timedelta
from engine.evaluator import match_contains, match_window_threshold

def test_match_contains():
    assert match_contains("ERROR: timeout", "ERROR") is True
    assert match_contains("INFO: success", "ERROR") is False

@pytest.mark.asyncio
async def test_match_window_threshold():
    logs = [
        LogEntry(timestamp=datetime.utcnow() - timedelta(seconds=10), content="ERROR"),
        LogEntry(timestamp=datetime.utcnow() - timedelta(seconds=20), content="ERROR"),
        LogEntry(timestamp=datetime.utcnow() - timedelta(seconds=30), content="ERROR"),
    ]
    
    result = match_window_threshold(logs, window_seconds=60, threshold=3)
    assert result is True
```

### 6.2 集成测试范围

**可选测试**：
- API 端点基础场景
  - 创建规则成功
  - 查询规则列表
  - 更新规则
- 引擎与 Loki 交互（使用 mock）

**示例**：
```python
import pytest
from httpx import AsyncClient
from main import app

@pytest.mark.asyncio
async def test_create_rule():
    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.post("/api/rules", json={
            "name": "测试规则",
            "enabled": True,
            "severity": "high",
            "selector_namespace": "demo",
            "match_type": "contains",
            "match_pattern": "ERROR",
            "window_seconds": 0,
            "threshold": 1,
            "group_by": ["namespace", "pod"],
            "cooldown_seconds": 300
        })
        
        assert response.status_code == 201
        assert response.json()["name"] == "测试规则"
```

## 七、部署与运维

### 7.1 环境变量配置

**必需配置**：
```bash
# .env.example
LOKI_URL=http://localhost:3100
DATABASE_URL=sqlite:///./data/logsentinel.db
ENGINE_INTERVAL_SECONDS=30
LOG_LEVEL=INFO
```

**加载方式**：
```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    loki_url: str
    database_url: str
    engine_interval_seconds: int = 30
    log_level: str = "INFO"
    
    class Config:
        env_file = ".env"

settings = Settings()
```

### 7.2 日志配置

**决策**：使用 structlog 输出 JSON 格式日志

**配置示例**：
```python
import structlog

structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer()
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    logger_factory=structlog.stdlib.LoggerFactory(),
)

logger = structlog.get_logger()
```

### 7.3 Docker 部署

**Dockerfile 示例**（后端）：
```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**docker-compose.yml**（本地开发）：
```yaml
version: '3.8'

services:
  backend:
    build:
      context: ./backend
      dockerfile: Dockerfile
    ports:
      - "8000:8000"
    environment:
      - LOKI_URL=http://loki:3100
      - DATABASE_URL=sqlite:///./data/logsentinel.db
    volumes:
      - ./data:/app/data
  
  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile
    ports:
      - "3000:80"
    depends_on:
      - backend
```

## 八、风险与缓解

### 8.1 Loki 查询性能

**风险**：大范围时间查询导致 Loki 响应慢或超时

**缓解**：
- 限制单次查询范围 ≤ 5 分钟
- 设置查询超时 5 秒
- 查询失败时跳过本次周期，下次重试

### 8.2 告警记录膨胀

**风险**：长期运行后告警表数据量过大

**缓解**：
- MVP 阶段不实现自动清理
- 提供手动清理脚本（删除 30 天前的告警）
- 后续阶段可实现自动归档

### 8.3 引擎崩溃恢复

**风险**：引擎崩溃后丢失运行状态

**缓解**：
- 所有关键状态持久化到数据库（last_query_time、last_notified_at）
- 引擎启动时从数据库恢复状态
- 使用 structlog 记录详细日志便于排查

## 决策总结

| 决策点 | 选择 | 理由 |
|--------|------|------|
| 引擎运行模式 | API 同进程后台任务 | 部署简单，MVP 优先 |
| 调度框架 | APScheduler | 轻量级，支持异步 |
| 数据库 | SQLite | 零配置，适合单用户 |
| 前端框架 | React + Ant Design | 组件丰富，开发效率高 |
| 状态管理 | React Hooks | 简单场景无需额外库 |
| 通知方式 | 控制台输出（structlog） | MVP 最小实现，易于扩展 |
| 日志格式 | JSON（structlog） | 结构化，便于分析 |
| 测试策略 | 单元测试 + 手动验证 | 平衡测试价值与开发效率 |

---

**下一步**：执行 Phase 1（数据模型与 API 合约设计），生成 `data-model.md` 和 `contracts/` 文档。