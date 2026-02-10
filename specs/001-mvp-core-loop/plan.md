# Implementation Plan: MVP 核心闭环 - K8s 日志告警平台

**Branch**: `001-mvp-core-loop` | **Date**: 2026-02-04 | **Spec**: [spec.md](./spec.md)  
**Input**: 基于已完成的 MVP Feature Specification（001-mvp-core-loop），生成第一阶段 MVP 的技术实施计划

## Summary

本计划旨在实现 Kubernetes 集群日志告警平台的最小可用闭环：从 K8s 产生测试日志 → 被 Loki 查询到 → 被规则引擎匹配 → 生成告警记录 → 在 Web 界面可见 → 完成基础通知。核心特点是"规则配置化"，规则逻辑由平台内置引擎统一定义和执行，用户通过配置参数实例化规则，而非编写代码。

技术方案采用前后端分离架构：
- **后端**：FastAPI 提供 RESTful API，SQLite 持久化数据
- **引擎**：独立 Python Worker 定期查询 Loki 并执行规则匹配
- **前端**：React + Ant Design 构建管理界面
- **通知**：MVP 阶段使用控制台输出，预留扩展接口

## Technical Context

**Language/Version**: Python 3.11+（后端与引擎）、JavaScript/TypeScript（前端 React 18+）  
**Primary Dependencies**:
- 后端：FastAPI、SQLAlchemy 2.0（async）、Pydantic v2、httpx（异步 HTTP 客户端）
- 引擎：APScheduler（定时任务）、structlog（结构化日志）
- 前端：React 18、Ant Design 5.x、axios、Vite

**Storage**: SQLite（开发期）；架构保持可切换 PostgreSQL  
**Testing**: pytest + pytest-asyncio（后端单元测试）；手动验证为主（端到端）  
**Target Platform**: 本地 Windows + Minikube 环境，后端与引擎运行在 Docker 容器或本地进程  
**Project Type**: Web 应用（前后端分离）  
**Performance Goals**:
- Loki 单次查询响应时间 < 5 秒
- Web 界面加载列表 < 2 秒（100 条数据内）
- 规则引擎查询周期：30 秒

**Constraints**:
- 单用户使用，无需多租户和复杂权限
- 日志格式限定为容器 stdout/stderr，暂不支持结构化日志解析
- 通知方式限定为控制台输出（MVP 阶段）
- 规则引擎单进程运行，无需分布式

**Scale/Scope**:
- 规则数量：< 50 条
- 告警记录：< 10,000 条
- 并发用户：1 人
- 日志查询范围：最近 5 分钟内

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

### 合规性检查

| 原则 | 状态 | 说明 |
|------|------|------|
| I. 规范驱动开发 | ✅ PASS | 已完成 spec.md，本 plan.md 在 spec 之后生成 |
| II. 最小可用闭环优先 | ✅ PASS | 聚焦核心链路：日志查询→规则匹配→告警→通知→UI，无过度工程化 |
| III. 数据模型先定 | ✅ PASS | Phase 1 将生成 data-model.md 和 API contracts |
| IV. 可观测与可复现 | ✅ PASS | 引擎关键流程使用 structlog 记录结构化日志；提供验证脚本 |
| V. 测试策略 | ✅ PASS | 规则评估、告警去重、冷却期逻辑将有单元测试；API 端点有基础集成测试 |
| VI. 代码风格与质量 | ✅ PASS | 使用 ruff + black 格式化；type hints 强制；依赖克制 |
| VII. 安全底线 | ✅ PASS | Loki URL、数据库路径通过环境变量配置；.env 不进版本控制 |
| VIII. 性能边界 | ✅ PASS | 引擎使用增量查询（记录 last_query_time）；单次查询范围 ≤ 5 分钟 |
| IX. UI 原则 | ✅ PASS | 核心三页：规则管理、告警列表、告警详情；使用 Ant Design |

### 复杂度辩护

无需辩护。本方案未引入超出宪章约束的复杂度。

## Project Structure

### Documentation (this feature)

```text
specs/001-mvp-core-loop/
├── spec.md              # 功能规格（已完成）
├── plan.md              # 本文件（技术实施计划）
├── research.md          # Phase 0 输出（技术调研与决策）
├── data-model.md        # Phase 1 输出（数据模型定义）
├── quickstart.md        # Phase 1 输出（快速启动指南）
├── contracts/           # Phase 1 输出（API 合约）
│   ├── rules-api.yaml   # 规则管理 API（OpenAPI 3.0）
│   └── alerts-api.yaml  # 告警管理 API（OpenAPI 3.0）
└── tasks.md             # Phase 2 输出（任务清单，由 /speckit.tasks 生成）
```

### Source Code (repository root)

```text
logsentinel/
├── backend/                    # 后端代码
│   ├── api/                   # FastAPI 路由
│   │   ├── __init__.py
│   │   ├── rules.py           # 规则管理 API
│   │   └── alerts.py          # 告警管理 API
│   ├── engine/                # 规则引擎
│   │   ├── __init__.py
│   │   ├── worker.py          # 引擎主循环
│   │   ├── evaluator.py       # 规则评估逻辑
│   │   ├── loki_client.py     # Loki 查询客户端
│   │   └── deduplicator.py    # 告警去重与合并
│   ├── notifier/              # 通知模块
│   │   ├── __init__.py
│   │   ├── base.py            # 通知接口定义
│   │   └── console.py         # 控制台通知实现
│   ├── models/                # SQLAlchemy 数据模型
│   │   ├── __init__.py
│   │   ├── rule.py
│   │   ├── alert.py
│   │   └── notification.py
│   ├── schemas/               # Pydantic schemas（API 请求/响应）
│   │   ├── __init__.py
│   │   ├── rule.py
│   │   └── alert.py
│   ├── database/              # 数据库连接与迁移
│   │   ├── __init__.py
│   │   ├── session.py         # 数据库会话管理
│   │   └── migrations/        # Alembic 迁移脚本
│   ├── tests/                 # 测试
│   │   ├── unit/
│   │   │   ├── test_evaluator.py
│   │   │   └── test_deduplicator.py
│   │   └── integration/
│   │       ├── test_rules_api.py
│   │       └── test_alerts_api.py
│   ├── config.py              # 配置管理
│   ├── main.py                # FastAPI 应用入口
│   └── requirements.txt
│
├── frontend/                   # 前端代码
│   ├── src/
│   │   ├── pages/
│   │   │   ├── RuleList.tsx   # 规则列表页
│   │   │   ├── RuleForm.tsx   # 规则创建/编辑页
│   │   │   ├── AlertList.tsx  # 告警列表页
│   │   │   └── AlertDetail.tsx # 告警详情页
│   │   ├── components/
│   │   │   ├── RuleCard.tsx
│   │   │   └── AlertCard.tsx
│   │   ├── services/
│   │   │   ├── api.ts         # axios 封装
│   │   │   ├── rules.ts       # 规则 API 调用
│   │   │   └── alerts.ts      # 告警 API 调用
│   │   ├── App.tsx
│   │   └── main.tsx
│   ├── package.json
│   └── vite.config.ts
│
├── deploy/                     # 部署配置
│   ├── docker/
│   │   ├── Dockerfile.backend
│   │   └── Dockerfile.frontend
│   └── k8s/
│       ├── backend-deployment.yaml
│       ├── frontend-deployment.yaml
│       └── service.yaml
│
├── scripts/                    # 开发与验证脚本
│   ├── dev-setup.sh           # 本地环境初始化
│   ├── verify-pipeline.sh     # 端到端验证脚本
│   └── generate-test-logs.sh  # 模拟日志生成工具
│
├── .env.example               # 环境变量模板
├── .gitignore
└── README.md
```

**Structure Decision**: 采用 Web 应用结构（Option 2），前后端分离。后端包含 API 服务和规则引擎，前端为独立的 React 应用。引擎作为后端的一部分，可以与 API 服务同进程运行（通过 APScheduler 后台任务），也可以独立部署为 Worker 进程。

## 一、系统整体拆分

### 1.1 模块职责与边界

#### 模块 1: API 服务（FastAPI）

**职责**：
- 提供规则管理 RESTful API（创建、查询、更新、删除、启用/停用）
- 提供告警查询 API（列表、详情、分页）
- 作为 Web 前端的唯一后端入口
- 负责规则与告警数据的持久化（通过 SQLAlchemy 访问 SQLite）
- 数据验证与错误处理（Pydantic schemas）

**边界**：
- 不执行规则匹配逻辑（由引擎负责）
- 不直接查询 Loki（由引擎负责）
- 不发送通知（由引擎调用通知模块）

**关键接口**：
- `POST /api/rules` - 创建规则
- `GET /api/rules` - 查询规则列表
- `GET /api/rules/{id}` - 查询规则详情
- `PUT /api/rules/{id}` - 更新规则
- `DELETE /api/rules/{id}` - 删除规则
- `PATCH /api/rules/{id}/enable` - 启用规则
- `PATCH /api/rules/{id}/disable` - 停用规则
- `GET /api/alerts` - 查询告警列表（支持分页、筛选）
- `GET /api/alerts/{id}` - 查询告警详情

#### 模块 2: 规则引擎（Engine Worker）

**职责**：
- 以独立循环方式运行（APScheduler 定时任务，默认 30 秒周期）
- 定期从数据库加载所有"已启用"规则
- 对每条规则查询 Loki 获取符合选择器的日志数据（使用 LogQL）
- 执行规则匹配逻辑：
  - 关键词匹配（contains）
  - 窗口阈值统计（window_seconds + threshold）
- 执行告警去重与合并（基于 rule_id + group_by 生成 fingerprint）
- 生成或更新告警记录（写入数据库）
- 判断是否需要触发通知（首次触发或冷却期结束）
- 调用通知模块发送通知

**边界**：
- 不提供 HTTP 接口（仅通过数据库与 API 服务交互）
- 不直接响应用户请求
- 不负责通知渠道的具体实现（委托给通知模块）

**MVP 执行模型约束**：
- 采用**单进程、单调度循环、顺序执行规则**的简化模型
- APScheduler 仅作为周期调度工具，不追求规则级并发或异步并行
- 规则按顺序逐条评估，单条规则失败不影响后续规则
- 并发优化属于后续阶段，不在 MVP 范围内

**关键流程**：
```
每 30 秒循环：
1. 从数据库加载 enabled=True 的规则
2. 对每条规则：
   a. 构造 LogQL 查询（基于 selector 和 last_query_time）
   b. 调用 Loki API 获取日志
   c. 对每条日志执行匹配判断
   d. 对于窗口阈值规则，维护时间窗口内的命中记录
   e. 判断是否满足告警条件
   f. 如果满足，计算 fingerprint 并查询数据库
   g. 如果告警已存在，更新 hit_count 和 last_seen
   h. 如果告警不存在，创建新告警记录
   i. 判断是否需要通知（首次或冷却期结束）
   j. 如果需要通知，调用 notifier.send()
3. 更新规则的 last_query_time
4. 记录结构化日志
```

#### 模块 3: 通知模块（Notifier）

**职责**：
- 提供统一的通知接口 `send(alert: Alert) -> None`
- MVP 阶段实现控制台输出（structlog 输出 JSON 格式）
- 记录通知历史到数据库（Notification 表）
- 预留扩展接口，后续支持 email/钉钉/webhook

**边界**：
- 不负责判断是否需要通知（由引擎判断）
- 不负责冷却期逻辑（由引擎判断）
- 仅负责通知的发送和记录

**实现策略**：
- 定义抽象基类 `BaseNotifier`，包含 `send()` 方法
- MVP 实现 `ConsoleNotifier`，输出到 stdout
- 通知内容包含：规则名称、严重级别、触发时间、匹配日志样例

#### 模块 4: Web 前端（React）

**职责**：
- 规则管理页面：
  - 规则列表（展示规则名称、类型、严重级别、启用状态）
  - 规则创建表单（输入规则参数）
  - 规则编辑表单（修改规则参数）
  - 规则启用/停用按钮
  - 规则删除确认
- 告警管理页面：
  - 告警列表（展示规则名称、严重级别、命中次数、最后触发时间）
  - 告警详情（展示告警完整信息和匹配日志样例）
  - 分页与筛选

**边界**：
- 通过 API 服务访问后端，不直接与引擎交互
- 不直接查询 Loki
- 不执行规则匹配逻辑

**技术选型**：
- React 18 + TypeScript
- Ant Design 5.x（Table、Form、Button、Modal 等组件）
- React Router（页面路由）
- axios（HTTP 客户端）

### 1.2 模块交互图

```
┌─────────────┐
│  Web 前端   │
│  (React)    │
└──────┬──────┘
       │ HTTP (REST API)
       ▼
┌─────────────┐
│  API 服务   │
│  (FastAPI)  │
└──────┬──────┘
       │ SQLAlchemy
       ▼
┌─────────────┐      ┌─────────────┐
│  数据库     │◄─────┤  规则引擎   │
│  (SQLite)   │      │  (Worker)   │
└─────────────┘      └──────┬──────┘
                            │ httpx
                            ▼
                     ┌─────────────┐
                     │    Loki     │
                     │  (外部服务) │
                     └─────────────┘
                            ▲
                            │ Promtail
                     ┌─────────────┐
                     │ Kubernetes  │
                     │   Cluster   │
                     └─────────────┘

规则引擎 ──调用──> 通知模块 ──输出──> 控制台
```

## 二、关键技术实现策略

### 2.1 Loki 日志查询策略（MVP）

**查询方式**：
- 使用 LogQL 进行日志查询
- 查询范围：从 `last_query_time` 到当前时间（最大 5 分钟）
- 初次查询：从当前时间往前推 60 秒

**LogQL 示例**：
```logql
{namespace="demo"} |= "ERROR"
```

**字段提取**：
- 时间戳：从 Loki 响应的 `timestamp` 字段
- 日志内容：从 `line` 字段
- namespace/pod：从 `stream` 标签中提取

**避免重复处理**：
- 每条规则维护 `last_query_time`（存储在数据库 Rule 表）
- **仅在本轮规则处理完整成功后**才更新 `last_query_time` 为本次查询的结束时间
- 如果 Loki 查询失败、超时或规则处理过程中发生异常，则保持原 `last_query_time`
- 下一个调度周期将重试该时间段的日志，避免因异常导致日志被永久跳过

**错误处理**：
- Loki 连接失败：记录错误日志，跳过本次查询，保持 `last_query_time` 不变，下次重试
- 查询超时：设置 5 秒超时，超时后跳过，保持 `last_query_time` 不变
- 查询无结果：正常情况，不生成告警，更新 `last_query_time`

### 2.2 规则执行模型

**引擎循环**：
- 使用 APScheduler 的 `IntervalTrigger`，默认 30 秒周期
- 每个周期独立执行，不依赖上一周期结果
- MVP 阶段采用顺序执行模式，规则按顺序逐条评估
- 可使用 asyncio 简化 I/O 操作，但不追求规则级并发

**规则类型**：

**MVP 阶段规则类型约定**：
- 不引入显式 `rule_type` 字段
- 通过 `window_seconds` 是否大于 0 区分规则类型：
  - `window_seconds = 0`：简单关键词匹配规则
  - `window_seconds > 0`：时间窗口阈值规则
- 前端表单与后端校验逻辑应基于此约定约束字段填写

#### 类型 1: 关键词匹配（contains）

**匹配逻辑**：
```python
def match_contains(log_line: str, keyword: str) -> bool:
    return keyword in log_line
```

**告警条件**：
- 只要有一条日志匹配，就满足告警条件

#### 类型 2: 时间窗口阈值（window + threshold）

**匹配逻辑**：
```python
def match_window_threshold(
    logs: List[LogEntry],
    window_seconds: int,
    threshold: int
) -> bool:
    now = datetime.utcnow()
    window_start = now - timedelta(seconds=window_seconds)
    
    # 筛选窗口内的日志
    logs_in_window = [
        log for log in logs
        if log.timestamp >= window_start
    ]
    
    return len(logs_in_window) >= threshold
```

**告警条件**：
- 窗口内匹配日志数量 >= 阈值

### 2.3 告警去重与分组

**Fingerprint 生成**：
```python
def generate_fingerprint(
    rule_id: int,
    group_by: Dict[str, str]
) -> str:
    """
    group_by 示例: {"namespace": "demo", "pod": "test-pod-123"}
    """
    parts = [str(rule_id)]
    for key in sorted(group_by.keys()):
        parts.append(f"{key}={group_by[key]}")
    
    fingerprint_str = "|".join(parts)
    return hashlib.sha256(fingerprint_str.encode()).hexdigest()
```

**去重逻辑**：
```python
async def handle_alert(
    rule: Rule,
    log_entry: LogEntry,
    session: AsyncSession
):
    # 提取分组维度
    group_by = {
        "namespace": log_entry.namespace,
        "pod": log_entry.pod
    }
    
    fingerprint = generate_fingerprint(rule.id, group_by)
    
    # 查询是否已存在
    existing_alert = await session.execute(
        select(Alert).where(Alert.fingerprint == fingerprint)
    )
    alert = existing_alert.scalar_one_or_none()
    
    if alert:
        # 更新现有告警
        alert.hit_count += 1
        alert.last_seen = datetime.utcnow()
        alert.sample_log = log_entry.to_dict()
    else:
        # 创建新告警
        alert = Alert(
            rule_id=rule.id,
            fingerprint=fingerprint,
            severity=rule.severity,
            status="active",
            first_seen=datetime.utcnow(),
            last_seen=datetime.utcnow(),
            hit_count=1,
            group_by=group_by,
            sample_log=log_entry.to_dict()
        )
        session.add(alert)
    
    await session.commit()
    return alert
```

### 2.4 时间窗口统计策略

**内存结构**：
- 使用 Python `deque` 维护窗口内的日志时间戳
- 每次新增日志时，移除窗口外的旧记录

**实现示例**：
```python
from collections import deque
from datetime import datetime, timedelta

class WindowCounter:
    def __init__(self, window_seconds: int):
        self.window_seconds = window_seconds
        self.timestamps = deque()
    
    def add(self, timestamp: datetime):
        self.timestamps.append(timestamp)
        self._cleanup()
    
    def _cleanup(self):
        now = datetime.utcnow()
        cutoff = now - timedelta(seconds=self.window_seconds)
        
        while self.timestamps and self.timestamps[0] < cutoff:
            self.timestamps.popleft()
    
    def count(self) -> int:
        self._cleanup()
        return len(self.timestamps)
```

**重启恢复**：
- 引擎重启后，从数据库读取告警的 `first_seen` 和 `last_seen`
- 如果 `last_seen` 在窗口内，恢复 `hit_count`
- 如果 `last_seen` 超出窗口，重置计数

**MVP 阶段窗口统计设计说明**：
- 时间窗口统计主要依赖运行期内存状态（如 deque）
- 引擎重启后，不保证跨重启的窗口连续性
- 这种设计不会导致误报，只可能在极端情况下延迟一次告警触发
- 该取舍是 MVP 阶段为降低复杂度而做出的合理权衡

### 2.5 冷却期实现

**数据库字段**：
- Alert 表增加 `last_notified_at` 字段（datetime，可为 NULL）

**判断逻辑**：
```python
def should_notify(
    alert: Alert,
    cooldown_seconds: int
) -> bool:
    if alert.last_notified_at is None:
        # 首次触发，需要通知
        return True
    
    now = datetime.utcnow()
    elapsed = (now - alert.last_notified_at).total_seconds()
    
    # 冷却期结束，需要通知
    return elapsed >= cooldown_seconds
```

**通知后更新**：
```python
async def notify_and_update(
    alert: Alert,
    notifier: BaseNotifier,
    session: AsyncSession
):
    # 发送通知
    await notifier.send(alert)
    
    # 更新通知时间
    alert.last_notified_at = datetime.utcnow()
    
    # 记录通知历史
    notification = Notification(
        alert_id=alert.id,
        notified_at=datetime.utcnow(),
        content=alert.to_notification_content()
    )
    session.add(notification)
    
    await session.commit()
```

### 2.6 样例日志存储

**存储策略**：
- Alert 表增加 `sample_log` 字段（JSON 类型）
- 仅存储最新一条命中日志的关键字段

**字段内容**：
```json
{
  "timestamp": "2026-02-04T08:30:15.123Z",
  "content": "ERROR: Connection timeout",
  "namespace": "demo",
  "pod": "test-pod-123",
  "container": "app"
}
```

**更新时机**：
- 每次告警命中时，覆盖 `sample_log` 为最新日志

## 三、数据模型与持久化策略

### 3.1 核心表结构

#### 表 1: rules（告警规则）

| 字段 | 类型 | 说明 | 必需 |
|------|------|------|------|
| id | INTEGER | 主键 | ✓ |
| name | VARCHAR(255) | 规则名称 | ✓ |
| enabled | BOOLEAN | 启用状态 | ✓ |
| severity | VARCHAR(20) | 严重级别（low/medium/high/critical） | ✓ |
| selector_namespace | VARCHAR(255) | 命名空间选择器 | ✓ |
| selector_labels | JSON | 标签选择器（可选） | |
| match_type | VARCHAR(20) | 匹配类型（contains/regex） | ✓ |
| match_pattern | TEXT | 匹配模式（关键词或正则） | ✓ |
| window_seconds | INTEGER | 时间窗口（秒，0 表示不使用窗口） | ✓ |
| threshold | INTEGER | 阈值（窗口内命中次数） | ✓ |
| group_by | JSON | 分组维度（如 ["namespace", "pod"]） | ✓ |
| cooldown_seconds | INTEGER | 冷却时间（秒） | ✓ |
| last_query_time | DATETIME | 上次查询时间（引擎使用） | |
| created_at | DATETIME | 创建时间 | ✓ |
| updated_at | DATETIME | 更新时间 | ✓ |

**引擎运行必需状态**：
- `enabled` - 判断是否执行规则
- `last_query_time` - 增量查询 Loki

#### 表 2: alerts（告警记录）

| 字段 | 类型 | 说明 | 必需 |
|------|------|------|------|
| id | INTEGER | 主键 | ✓ |
| rule_id | INTEGER | 关联规则 ID（外键） | ✓ |
| fingerprint | VARCHAR(64) | 告警指纹（SHA256） | ✓ |
| severity | VARCHAR(20) | 严重级别 | ✓ |
| status | VARCHAR(20) | 状态（active，MVP 固定，仅作未来扩展预留） | ✓ |
| first_seen | DATETIME | 首次触发时间 | ✓ |
| last_seen | DATETIME | 最后触发时间 | ✓ |
| hit_count | INTEGER | 累计命中次数 | ✓ |
| group_by | JSON | 分组维度值（如 {"namespace": "demo", "pod": "xxx"}） | ✓ |
| sample_log | JSON | 最新一条匹配日志 | ✓ |
| last_notified_at | DATETIME | 上次通知时间（冷却期使用） | |
| created_at | DATETIME | 创建时间 | ✓ |
| updated_at | DATETIME | 更新时间 | ✓ |

**索引**：
- `fingerprint` - 唯一索引（用于去重查询）
- `rule_id` - 普通索引
- `last_seen` - 普通索引（用于列表排序）

**引擎运行必需状态**：
- `fingerprint` - 去重判断
- `hit_count` - 窗口阈值统计
- `last_seen` - 窗口判断
- `last_notified_at` - 冷却期判断

**MVP 阶段 status 字段设计说明**：
- MVP 阶段不实现告警生命周期管理（ack/resolved）
- `status` 字段固定为 `active`，仅作为未来扩展预留字段
- 当前阶段 `status` 不参与任何业务判断逻辑

#### 表 3: notifications（通知记录）

| 字段 | 类型 | 说明 | 必需 |
|------|------|------|------|
| id | INTEGER | 主键 | ✓ |
| alert_id | INTEGER | 关联告警 ID（外键） | ✓ |
| notified_at | DATETIME | 通知时间 | ✓ |
| channel | VARCHAR(50) | 通知渠道（console/email/webhook） | ✓ |
| content | TEXT | 通知内容（JSON 格式） | ✓ |
| status | VARCHAR(20) | 发送状态（success/failed） | ✓ |
| created_at | DATETIME | 创建时间 | ✓ |

**索引**：
- `alert_id` - 普通索引

### 3.2 数据库技术选型

**开发期**：SQLite
- 优点：零配置、轻量级、适合单用户
- 文件路径：`./data/logsentinel.db`

**架构保持可切换**：
- 使用 SQLAlchemy 2.0 异步 API
- 避免使用 SQLite 特有语法
- 后续可切换到 PostgreSQL（修改连接字符串即可）

### 3.3 数据库迁移

**工具**：Alembic

**迁移脚本位置**：`backend/database/migrations/`

**初始迁移**：
```bash
alembic revision --autogenerate -m "Initial schema"
alembic upgrade head
```

## 四、实施阶段划分

### Phase 1: 基础后端与数据模型

**目标**：建立后端项目骨架，完成数据模型定义和规则管理 API

**任务**：
1. 初始化 FastAPI 项目结构
2. 配置 SQLAlchemy + SQLite 连接
3. 定义 Rule / Alert / Notification 数据模型（SQLAlchemy models）
4. 定义 Pydantic schemas（API 请求/响应）
5. 实现规则管理 API：
   - POST /api/rules（创建规则）
   - GET /api/rules（查询规则列表）
   - GET /api/rules/{id}（查询规则详情）
   - PUT /api/rules/{id}（更新规则）
   - DELETE /api/rules/{id}（删除规则）
   - PATCH /api/rules/{id}/enable（启用规则）
   - PATCH /api/rules/{id}/disable（停用规则）
6. 编写单元测试（API 端点基础场景）
7. 配置环境变量管理（.env.example）

**完成标志**：
- 可通过 Postman/curl 创建规则并查看规则列表
- 规则数据成功持久化到 SQLite
- 单元测试通过

**交付物**：
- `backend/` 目录完整代码
- `data-model.md` 文档
- `contracts/rules-api.yaml` OpenAPI 规范

### Phase 2: 规则引擎最小循环

**目标**：实现引擎周期任务，能从 Loki 查询日志并执行关键词规则

**任务**：
1. 实现 Loki 客户端（httpx 异步调用）
2. 实现引擎主循环（APScheduler，30 秒周期）
3. 实现关键词匹配逻辑（contains）
4. 实现告警生成逻辑（创建 Alert 记录）
5. 实现增量查询（维护 last_query_time）
6. 配置 structlog 结构化日志
7. 编写单元测试（Loki 客户端、匹配逻辑）

**完成标志**：
- 引擎能定期查询 Loki 并打印日志
- 关键词规则能触发告警生成
- 告警数据成功写入数据库
- 结构化日志输出正常

**交付物**：
- `backend/engine/` 目录完整代码
- 引擎运行日志示例

### Phase 3: 窗口阈值与告警合并

**目标**：实现窗口阈值规则和告警去重合并机制

**任务**：
1. 实现时间窗口统计逻辑（WindowCounter）
2. 实现窗口阈值规则匹配
3. 实现 fingerprint 生成逻辑
4. 实现告警去重与合并（更新 hit_count 和 last_seen）
5. 实现告警查询 API：
   - GET /api/alerts（查询告警列表，支持分页）
   - GET /api/alerts/{id}（查询告警详情）
6. 编写单元测试（去重逻辑、窗口统计）

**完成标志**：
- 窗口阈值规则能正确触发告警
- 同一 fingerprint 的多次命中能合并到同一告警
- 告警列表 API 返回正确数据
- 命中次数与时间正确更新

**交付物**：
- `backend/engine/deduplicator.py` 完整代码
- `contracts/alerts-api.yaml` OpenAPI 规范

### Phase 4: 基础通知与冷却期

**目标**：实现控制台通知和冷却期机制

**任务**：
1. 定义通知接口（BaseNotifier 抽象类）
2. 实现控制台通知（ConsoleNotifier）
3. 实现冷却期判断逻辑
4. 实现通知历史记录（Notification 表）
5. 集成通知到引擎主循环
6. 编写单元测试（冷却期逻辑）

**完成标志**：
- 告警首次触发时能输出通知到控制台
- 冷却期内不重复通知
- 冷却期结束后能再次通知
- 通知历史可追溯

**交付物**：
- `backend/notifier/` 目录完整代码
- 通知输出示例

### Phase 5: Web 界面接入

**目标**：实现前端界面，完成完整闭环演示

**任务**：
1. 初始化 React + Vite 项目
2. 配置 Ant Design 和 axios
3. 实现规则管理页面：
   - 规则列表（Table 组件）
   - 规则创建表单（Form 组件）
   - 规则编辑表单
   - 启用/停用按钮
   - 删除确认（Modal 组件）
4. 实现告警管理页面：
   - 告警列表（Table 组件，支持分页）
   - 告警详情（Descriptions 组件）
5. 配置路由（React Router）
6. 编写 API 调用封装（services/）
7. 编写演示脚本（scripts/verify-pipeline.sh）

**完成标志**：
- 可在浏览器中访问前端界面
- 可通过界面创建规则
- 可在界面查看告警列表和详情
- 演示脚本能稳定复现完整闭环

**交付物**：
- `frontend/` 目录完整代码
- `scripts/verify-pipeline.sh` 演示脚本
- `quickstart.md` 快速启动指南

## 五、明确不在 plan 中展开的内容

以下功能明确不在 MVP 阶段实现，避免过度工程化：

- ❌ **分布式高可用**：引擎集群、分片、选主
- ❌ **静默功能**：手动屏蔽特定告警的通知
- ❌ **序列规则**：基于多条规则的组合逻辑
- ❌ **复杂权限**：多用户、RBAC、配额管理
- ❌ **通知渠道扩展**：邮件、钉钉、企业微信、Webhook
- ❌ **通知重试限流**：通知失败重试、频率限制
- ❌ **规则测试 UI**：在界面上模拟规则匹配
- ❌ **结构化日志解析**：JSON、键值对字段提取
- ❌ **告警状态自动解决**：基于日志恢复标记为 resolved
- ❌ **告警统计看板**：趋势图、Top 规则排行
- ❌ **性能优化**：大规模日志查询优化、缓存机制

如需扩展以上功能，必须先修订宪法并评估时间成本。

## Complexity Tracking

无需填写。本方案未引入超出宪章约束的复杂度。

---

**下一步**：执行 Phase 0（研究与决策），生成 `research.md` 文档，解决所有技术细节问题。
