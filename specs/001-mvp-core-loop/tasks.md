# Tasks: MVP 核心闭环 - K8s 日志告警平台

**Feature Branch**: `001-mvp-core-loop`  
**Created**: 2026-02-04  
**Spec**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md)

## 任务总览

本任务清单基于 MVP Feature Specification 和 Implementation Plan 生成，按照 5 个阶段组织，每个阶段聚焦一个可验收的交付增量。

**总体约束**：
- 严格按 MVP 范围：规则管理、关键词匹配、窗口阈值、告警合并去重、冷却期控制台通知、Web 界面展示
- 不引入新组件（不加 Redis/Kafka/ES 等）
- 引擎默认 30s 周期；Loki 查询失败不更新 last_query_time
- MVP 规则执行顺序执行即可（单进程、单调度循环）

**任务统计**：
- Phase 1: 6 个任务（后端骨架与数据模型）
- Phase 2: 5 个任务（引擎最小循环）
- Phase 3: 6 个任务（窗口阈值 + 去重合并）
- Phase 4: 5 个任务（控制台通知 + 冷却期）
- Phase 5: 7 个任务（前端接入 + E2E 演示）
- **总计**: 29 个任务

---

## Phase 1: 后端骨架与数据模型

**目标**：建立 FastAPI 项目骨架，完成数据模型定义和规则管理 API，确保规则 CRUD 功能可用。

### T001 - 初始化 FastAPI 项目与配置管理 ✅

**Scope**：
- 创建 `backend/` 目录结构
- 初始化 FastAPI 应用（`main.py`）
- 配置环境变量管理（`.env.example`、`config.py`）
- 配置 CORS（允许前端跨域访问）
- 添加健康检查端点（`GET /health`）

**Deliverables**：
- `backend/main.py` - FastAPI 应用入口
- `backend/config.py` - 配置管理模块
- `.env.example` - 环境变量模板（包含 LOKI_URL、DATABASE_URL）
- `backend/requirements.txt` - Python 依赖清单

**Done**：
- 运行 `uvicorn backend.main:app --reload` 能启动服务
- 访问 `http://localhost:8000/health` 返回 `{"status": "ok"}`
- 访问 `http://localhost:8000/docs` 能看到 Swagger UI

**Dependencies**: 无

---

### T002 - 配置 SQLAlchemy + SQLite 数据库连接 ✅

**Scope**：
- 配置 SQLAlchemy 2.0 异步引擎
- 创建数据库会话管理（`database/session.py`）
- 配置 SQLite 数据库文件路径（`./data/logsentinel.db`）
- 实现数据库初始化函数（创建表）

**Deliverables**：
- `backend/database/__init__.py`
- `backend/database/session.py` - 数据库会话管理
- `backend/database/base.py` - SQLAlchemy Base 类

**Done**：
- 运行应用后自动创建 `./data/logsentinel.db` 文件
- 数据库连接池正常工作
- 异步会话可正常创建和关闭

**Dependencies**: T001

---

### T003 - 定义数据模型（Rule/Alert/Notification） ✅

**Scope**：
- 实现 Rule 模型（`models/rule.py`）
- 实现 Alert 模型（`models/alert.py`）
- 实现 Notification 模型（`models/notification.py`）
- 定义表结构、字段类型、约束、索引
- 配置外键关系和级联删除

**Deliverables**：
- `backend/models/__init__.py`
- `backend/models/rule.py` - Rule 数据模型
- `backend/models/alert.py` - Alert 数据模型
- `backend/models/notification.py` - Notification 数据模型

**Done**：
- 所有模型字段与 `data-model.md` 定义一致
- 外键关系正确配置（Rule -> Alert -> Notification）
- 索引正确创建（fingerprint 唯一索引、last_seen 索引等）
- 运行应用后数据库表自动创建

**Dependencies**: T002

---

### T004 - 定义 Pydantic Schemas（API 请求/响应） ✅

**Scope**：
- 定义 Rule 相关 schemas（`schemas/rule.py`）
  - `RuleCreate` - 创建规则请求
  - `RuleUpdate` - 更新规则请求
  - `RuleResponse` - 规则响应
  - `RuleListResponse` - 规则列表响应
- 定义 Alert 相关 schemas（`schemas/alert.py`）
  - `AlertResponse` - 告警响应
  - `AlertListResponse` - 告警列表响应
- 实现输入验证逻辑（正则表达式合法性、字段范围等）

**Deliverables**：
- `backend/schemas/__init__.py`
- `backend/schemas/rule.py` - Rule schemas
- `backend/schemas/alert.py` - Alert schemas

**Done**：
- 所有 schema 字段与 API 合约（`contracts/rules-api.yaml`）一致
- 输入验证规则正确实现：
  - `name` 长度 1-255
  - `severity` 枚举值校验
  - `window_seconds` >= 0
  - `threshold` >= 1
  - `match_pattern` 正则表达式合法性校验（当 `match_type=regex` 时）
- Pydantic 验证错误能返回清晰的错误信息

**Dependencies**: T003

---

### T005 - 实现规则管理 API（CRUD + 启停） ✅

**Scope**：
- 实现规则管理路由（`api/rules.py`）
  - `POST /api/rules` - 创建规则
  - `GET /api/rules` - 查询规则列表
  - `GET /api/rules/{id}` - 查询规则详情
  - `PUT /api/rules/{id}` - 更新规则
  - `DELETE /api/rules/{id}` - 删除规则
  - `PATCH /api/rules/{id}/enable` - 启用规则
  - `PATCH /api/rules/{id}/disable` - 停用规则
- 实现数据库 CRUD 操作（使用 SQLAlchemy async）
- 实现错误处理（404、400、500）

**Deliverables**：
- `backend/api/__init__.py`
- `backend/api/rules.py` - 规则管理 API 路由

**Done**：
- 所有端点与 `contracts/rules-api.yaml` 定义一致
- 可通过 Postman/curl 创建规则并查看规则列表
- 规则数据成功持久化到 SQLite
- 启用/停用规则能正确更新 `enabled` 字段
- 删除规则能级联删除关联的告警记录
- 错误响应格式统一（包含 `error` 和 `detail` 字段）

**Dependencies**: T004

---

### T006 - 编写规则 API 基础测试 ✅

**Scope**：
- 配置 pytest + pytest-asyncio 测试环境
- 编写规则 API 集成测试（`tests/integration/test_rules_api.py`）
  - 测试创建规则（happy path）
  - 测试查询规则列表
  - 测试更新规则
  - 测试启用/停用规则
  - 测试删除规则
  - 测试输入验证（无效数据）

**Deliverables**：
- `backend/tests/__init__.py`
- `backend/tests/conftest.py` - pytest 配置和 fixtures
- `backend/tests/integration/test_rules_api.py` - 规则 API 测试

**Done**：
- 运行 `pytest backend/tests/integration/test_rules_api.py` 所有测试通过
- 测试覆盖主要场景（创建、查询、更新、删除、启停）
- 测试使用独立的测试数据库（不影响开发数据）

**Dependencies**: T005

---

## Phase 2: 引擎最小循环（关键词规则）

**目标**：实现规则引擎周期任务，能从 Loki 查询日志并执行关键词规则，生成告警记录。

### T007 - 实现 Loki 客户端（httpx + LogQL） ✅

**Scope**：
- 实现 Loki HTTP 客户端（`engine/loki_client.py`）
- 实现 `query_range()` 方法（查询指定时间范围的日志）
- 实现 LogQL 查询构造（基于 namespace、labels、关键词）
- 实现响应解析（提取 timestamp、line、namespace、pod、container）
- 实现错误处理（连接超时、查询失败）

**Deliverables**：
- `backend/engine/__init__.py`
- `backend/engine/loki_client.py` - Loki 客户端

**Done**：
- 能成功查询 Loki 并解析响应
- 能从响应中提取 `timestamp`、`line`、`namespace`、`pod`、`container` 字段
- 连接超时设置为 5 秒
- 查询失败时抛出明确的异常（`LokiQueryError`）
- 单元测试通过（mock Loki 响应）

**Dependencies**: T001

---

### T008 - 实现引擎主循环（APScheduler + 30s 周期） ✅

**Scope**：
- 实现引擎主循环（`engine/worker.py`）
- 配置 APScheduler 定时任务（IntervalTrigger，30 秒周期）
- 实现引擎启动和停止逻辑
- 配置 structlog 结构化日志（JSON 格式输出）
- 实现引擎运行状态监控（记录每轮执行时间、处理规则数量）

**Deliverables**：
- `backend/engine/worker.py` - 引擎主循环
- `backend/engine/logger.py` - structlog 配置

**Done**：
- 运行引擎后每 30 秒执行一次循环
- 每轮循环输出结构化日志（包含时间戳、规则数量、执行耗时）
- 引擎能优雅停止（Ctrl+C 后完成当前循环再退出）
- 日志格式为 JSON（包含 `timestamp`、`level`、`event`、`context` 字段）

**Dependencies**: T007

---

### T009 - 实现关键词匹配逻辑（contains） ✅

**Scope**：
- 实现规则评估器（`engine/evaluator.py`）
- 实现关键词匹配逻辑（`match_contains()`）
- 实现增量查询逻辑（维护 `last_query_time`）
- 实现规则加载逻辑（从数据库加载 `enabled=True` 的规则）
- 实现 last_query_time 更新策略（仅成功后更新，失败保留）

**Deliverables**：
- `backend/engine/evaluator.py` - 规则评估器

**Done**：
- 能从数据库加载已启用规则
- 能对每条规则查询 Loki（使用 `last_query_time` 作为起始时间）
- 能正确匹配包含关键词的日志
- 仅在规则处理完整成功后更新 `last_query_time`
- Loki 查询失败时保持 `last_query_time` 不变，下次重试
- 单元测试通过（mock Loki 客户端）

**Dependencies**: T008

---

### T010 - 实现告警生成逻辑（创建 Alert 记录） ✅

**Scope**：
- 实现告警生成逻辑（在 `evaluator.py` 中）
- 实现 Alert 记录创建（包含所有必需字段）
- 实现 sample_log 存储（最新一条匹配日志）
- 集成到引擎主循环（匹配成功后生成告警）

**Deliverables**：
- 更新 `backend/engine/evaluator.py` - 增加告警生成逻辑

**Done**：
- 关键词规则匹配成功后能生成 Alert 记录
- Alert 记录包含所有必需字段（rule_id、fingerprint、severity、first_seen、last_seen、hit_count、group_by、sample_log）
- sample_log 包含完整的日志信息（timestamp、content、namespace、pod、container）
- 告警数据成功写入数据库
- 结构化日志输出告警生成事件

**Dependencies**: T009

---

### T011 - 编写引擎单元测试（Loki 客户端 + 匹配逻辑） ✅

**Scope**：
- 编写 Loki 客户端单元测试（`tests/unit/test_loki_client.py`）
  - 测试 query_range() 正常响应解析
  - 测试连接超时处理
  - 测试查询失败处理
- 编写规则评估器单元测试（`tests/unit/test_evaluator.py`）
  - 测试关键词匹配逻辑
  - 测试增量查询逻辑
  - 测试 last_query_time 更新策略

**Deliverables**：
- `backend/tests/unit/test_loki_client.py` - Loki 客户端测试
- `backend/tests/unit/test_evaluator.py` - 规则评估器测试

**Done**：
- 运行 `pytest backend/tests/unit/` 所有测试通过
- 测试使用 mock 对象（不依赖真实 Loki 服务）
- 测试覆盖主要场景和边界情况

**Dependencies**: T010

---

## Phase 3: 窗口阈值 + 去重合并 + 告警 API

**目标**：实现窗口阈值规则、告警去重合并机制，提供告警查询 API。

### T012 - 实现时间窗口统计逻辑（WindowCounter） ✅

**Scope**：
- 实现时间窗口计数器（`engine/window_counter.py`）
- 使用 `deque` 维护窗口内的日志时间戳
- 实现 `add()` 方法（添加新时间戳）
- 实现 `count()` 方法（返回窗口内计数）
- 实现自动清理过期时间戳

**Deliverables**：
- `backend/engine/window_counter.py` - 时间窗口计数器

**Done**：
- 能正确统计窗口内的日志数量
- 过期时间戳能自动清理
- 单元测试通过（测试不同窗口大小和时间戳序列）

**Dependencies**: T009

---

### T013 - 实现窗口阈值规则匹配 ✅

**Scope**：
- 更新规则评估器（`evaluator.py`）
- 实现窗口阈值规则判断逻辑（`match_window_threshold()`）
- 为每条规则维护独立的 WindowCounter 实例
- 实现规则类型判断（通过 `window_seconds` 是否大于 0 区分）

**Deliverables**：
- 更新 `backend/engine/evaluator.py` - 增加窗口阈值逻辑

**Done**：
- 窗口阈值规则能正确触发告警（窗口内命中次数 >= 阈值）
- 不同规则使用独立的窗口计数器
- 规则类型通过 `window_seconds=0` 自动区分（0=关键词，>0=窗口阈值）
- 单元测试通过（测试不同窗口和阈值组合）

**Dependencies**: T012

---

### T014 - 实现 Fingerprint 生成与告警去重 ✅

**Scope**：
- 实现告警去重器（`engine/deduplicator.py`）
- 实现 `generate_fingerprint()` 方法（基于 rule_id + group_by）
- 实现告警查询逻辑（根据 fingerprint 查询现有告警）
- 实现告警合并逻辑（更新 hit_count、last_seen、sample_log）

**Deliverables**：
- `backend/engine/deduplicator.py` - 告警去重器

**Done**：
- fingerprint 生成算法正确（SHA256 哈希）
- 同一 fingerprint 的多次命中能合并到同一告警
- 告警合并时正确更新 `hit_count`、`last_seen`、`sample_log`
- 不同 fingerprint 创建独立的告警记录
- 单元测试通过（测试去重和合并逻辑）

**Dependencies**: T010

---

### T015 - 集成告警去重到引擎主循环 ✅

**Scope**：
- 更新引擎主循环（`worker.py`）
- 集成告警去重器到规则评估流程
- 实现告警创建和更新逻辑
- 实现数据库事务管理（确保原子性）

**Deliverables**：
- 更新 `backend/engine/worker.py` - 集成去重逻辑

**Done**：
- 引擎运行时能正确去重和合并告警
- 同一 Pod 的多次命中更新同一告警记录
- 不同 Pod 的命中创建独立告警记录
- 数据库操作使用事务（失败时回滚）
- 结构化日志输出告警合并事件

**Dependencies**: T014

---

### T016 - 实现告警查询 API（列表 + 详情） ✅

**Scope**：
- 实现告警管理路由（`api/alerts.py`）
  - `GET /api/alerts` - 查询告警列表（支持分页、筛选）
  - `GET /api/alerts/{id}` - 查询告警详情
- 实现分页逻辑（默认每页 20 条）
- 实现排序逻辑（默认按 `last_seen` 倒序）
- 实现筛选逻辑（按 severity、rule_id 筛选）

**Deliverables**：
- `backend/api/alerts.py` - 告警管理 API 路由

**Done**：
- 所有端点与 `contracts/alerts-api.yaml` 定义一致
- 告警列表支持分页（page、page_size 参数）
- 告警列表默认按 `last_seen` 倒序排列
- 告警详情包含完整信息（包括 sample_log）
- 可通过 Postman/curl 查询告警列表和详情

**Dependencies**: T015

---

### T017 - 编写告警去重与窗口统计单元测试 ✅

**Scope**：
- 编写告警去重器单元测试（`tests/unit/test_deduplicator.py`）
  - 测试 fingerprint 生成
  - 测试告警去重逻辑
  - 测试告警合并逻辑
- 编写窗口计数器单元测试（`tests/unit/test_window_counter.py`）
  - 测试窗口内计数
  - 测试过期清理

**Deliverables**：
- `backend/tests/unit/test_deduplicator.py` - 去重器测试
- `backend/tests/unit/test_window_counter.py` - 窗口计数器测试

**Done**：
- 运行 `pytest backend/tests/unit/` 所有测试通过
- 测试覆盖主要场景和边界情况

**Dependencies**: T016

---

## Phase 4: 控制台通知 + 冷却期 + 通知历史

**目标**：实现控制台通知、冷却期机制和通知历史记录。

### T018 - 定义通知接口（BaseNotifier） ✅

**Scope**：
- 定义通知接口抽象类（`notifier/base.py`）
- 定义 `send()` 方法签名
- 定义通知内容结构（规则名称、严重级别、触发时间、样例日志）

**Deliverables**：
- `backend/notifier/__init__.py`
- `backend/notifier/base.py` - 通知接口定义

**Done**：
- BaseNotifier 抽象类定义清晰
- `send()` 方法签名明确（接收 Alert 对象）
- 通知内容结构与 `data-model.md` 一致

**Dependencies**: T003

---

### T019 - 实现控制台通知（ConsoleNotifier） ✅

**Scope**：
- 实现控制台通知器（`notifier/console.py`）
- 实现 `send()` 方法（输出到 stdout）
- 使用 structlog 输出结构化日志（JSON 格式）
- 包含完整的通知内容（规则名称、严重级别、触发时间、样例日志）

**Deliverables**：
- `backend/notifier/console.py` - 控制台通知器

**Done**：
- 调用 `send()` 方法能输出结构化日志到控制台
- 日志格式为 JSON（包含 `event="alert_notification"`）
- 日志内容包含规则名称、严重级别、触发时间、样例日志
- 单元测试通过（验证日志输出）

**Dependencies**: T018

---

### T020 - 实现冷却期判断逻辑 ✅

**Scope**：
- 实现冷却期判断函数（在 `engine/evaluator.py` 中）
- 实现 `should_notify()` 方法（判断是否需要通知）
- 基于 `last_notified_at` 和 `cooldown_seconds` 判断
- 首次触发返回 True，冷却期内返回 False，冷却期结束返回 True

**Deliverables**：
- 更新 `backend/engine/evaluator.py` - 增加冷却期逻辑

**Done**：
- 告警首次触发时 `should_notify()` 返回 True
- 冷却期内 `should_notify()` 返回 False
- 冷却期结束后 `should_notify()` 返回 True
- 单元测试通过（测试不同冷却期和时间间隔）

**Dependencies**: T015

---

### T021 - 实现通知历史记录（Notification 表） ✅

**Scope**：
- 实现通知记录创建逻辑（在 `engine/evaluator.py` 中）
- 实现 `last_notified_at` 更新逻辑
- 实现 Notification 表写入（记录通知时间、渠道、内容、状态）
- 实现数据库事务管理

**Deliverables**：
- 更新 `backend/engine/evaluator.py` - 增加通知记录逻辑

**Done**：
- 通知发送后能创建 Notification 记录
- Notification 记录包含完整信息（alert_id、notified_at、channel、content、status）
- Alert 的 `last_notified_at` 正确更新
- 数据库操作使用事务（确保原子性）

**Dependencies**: T020

---

### T022 - 集成通知到引擎主循环 ✅

**Scope**：
- 更新引擎主循环（`worker.py`）
- 集成通知器到规则评估流程
- 实现通知触发逻辑（首次触发或冷却期结束）
- 实现通知失败处理（记录错误日志，不中断引擎）

**Deliverables**：
- 更新 `backend/engine/worker.py` - 集成通知逻辑

**Done**：
- 告警首次触发时能输出通知到控制台
- 冷却期内不重复通知（仅更新告警记录）
- 冷却期结束后能再次通知
- 通知历史可追溯（Notification 表有记录）
- 通知失败时记录错误日志但不中断引擎
- 结构化日志输出通知事件

**Dependencies**: T021

---

## Phase 5: Web 界面接入 + E2E 演示脚本

**目标**：实现前端界面，完成完整闭环演示，提供快速启动指南。

### T023 - 初始化 React 项目（Vite + Ant Design） ✅

**Scope**：
- 初始化 React + Vite 项目（`frontend/`）
- 配置 TypeScript
- 安装 Ant Design 5.x
- 安装 React Router、axios
- 配置开发服务器（端口 3000）
- 配置代理（转发 `/api` 请求到后端）

**Deliverables**：
- `frontend/package.json` - 依赖清单
- `frontend/vite.config.ts` - Vite 配置
- `frontend/tsconfig.json` - TypeScript 配置
- `frontend/src/main.tsx` - 应用入口

**Done**：
- 运行 `npm run dev` 能启动前端开发服务器
- 访问 `http://localhost:3000` 能看到默认页面
- Ant Design 组件能正常使用
- 代理配置正确（`/api` 请求转发到 `http://localhost:8000`）

**Dependencies**: 无

---

### T024 - 实现规则列表页面 ✅

**Scope**：
- 实现规则列表页面（`pages/RuleList.tsx`）
- 使用 Ant Design Table 组件展示规则列表
- 展示字段：规则名称、类型、严重级别、启用状态、创建时间
- 实现启用/停用按钮（调用 API）
- 实现删除按钮（带确认 Modal）
- 实现"新建规则"按钮（跳转到创建页面）

**Deliverables**：
- `frontend/src/pages/RuleList.tsx` - 规则列表页面
- `frontend/src/services/rules.ts` - 规则 API 调用封装

**Done**：
- 页面能正确展示规则列表
- 启用/停用按钮能正确切换规则状态
- 删除按钮能删除规则（带确认提示）
- "新建规则"按钮能跳转到创建页面
- 页面样式美观（使用 Ant Design 组件）

**Dependencies**: T023

---

### T025 - 实现规则创建/编辑表单 ✅

**Scope**：
- 实现规则创建页面（`pages/RuleForm.tsx`）
- 使用 Ant Design Form 组件
- 表单字段：规则名称、严重级别、命名空间、匹配类型、匹配模式、窗口时间、阈值、分组维度、冷却时间
- 实现表单验证（必填项、数值范围、正则表达式合法性）
- 实现提交逻辑（调用创建/更新 API）
- 支持创建和编辑两种模式（通过路由参数区分）

**Deliverables**：
- `frontend/src/pages/RuleForm.tsx` - 规则创建/编辑页面

**Done**：
- 表单能正确展示所有字段
- 表单验证规则正确（与后端一致）
- 提交后能成功创建/更新规则
- 提交成功后跳转回规则列表
- 表单样式美观（使用 Ant Design 组件）

**Dependencies**: T024

---

### T026 - 实现告警列表页面 ✅

**Scope**：
- 实现告警列表页面（`pages/AlertList.tsx`）
- 使用 Ant Design Table 组件展示告警列表
- 展示字段：规则名称、严重级别、状态、命中次数、最后触发时间
- 实现分页（默认每页 20 条）
- 实现排序（默认按最后触发时间倒序）
- 实现点击行跳转到详情页

**Deliverables**：
- `frontend/src/pages/AlertList.tsx` - 告警列表页面
- `frontend/src/services/alerts.ts` - 告警 API 调用封装

**Done**：
- 页面能正确展示告警列表
- 分页功能正常工作
- 排序功能正常工作
- 点击行能跳转到告警详情页
- 页面样式美观（使用 Ant Design 组件）

**Dependencies**: T023

---

### T027 - 实现告警详情页面 ✅

**Scope**：
- 实现告警详情页面（`pages/AlertDetail.tsx`）
- 使用 Ant Design Descriptions 组件展示告警详情
- 展示字段：规则名称、严重级别、状态、首次触发时间、最后触发时间、累计命中次数、分组维度、样例日志
- 样例日志使用 Card 组件展示（包含时间戳、内容、Pod、命名空间）

**Deliverables**：
- `frontend/src/pages/AlertDetail.tsx` - 告警详情页面

**Done**：
- 页面能正确展示告警详细信息
- 样例日志展示清晰（包含所有字段）
- 页面样式美观（使用 Ant Design 组件）

**Dependencies**: T026

---

### T028 - 配置路由与导航 ✅

**Scope**：
- 配置 React Router（`App.tsx`）
- 定义路由：
  - `/` - 重定向到 `/rules`
  - `/rules` - 规则列表页
  - `/rules/new` - 创建规则页
  - `/rules/:id/edit` - 编辑规则页
  - `/alerts` - 告警列表页
  - `/alerts/:id` - 告警详情页
- 实现顶部导航栏（使用 Ant Design Menu 组件）

**Deliverables**：
- `frontend/src/App.tsx` - 应用主组件（包含路由和导航）

**Done**：
- 所有路由正常工作
- 导航栏能正确切换页面
- 页面切换流畅（无闪烁）

**Dependencies**: T027

---

### T029 - 编写演示脚本与快速启动指南 ✅

**Scope**：
- 编写端到端验证脚本（`scripts/verify-pipeline.sh`）
  - 部署测试 Pod（持续输出 ERROR 日志）
  - 创建关键词规则（通过 API）
  - 等待告警生成（轮询告警 API）
  - 验证告警数据正确性
  - 验证控制台通知输出
- 编写 Loki 部署脚本（`scripts/setup-loki.sh`）
  - 自动部署 Loki 和 Promtail 到 Minikube
  - 验证部署状态
- 编写快速启动指南（`quickstart.md`）
  - 环境准备（Minikube、Loki、Python、Node.js）
  - Loki 部署步骤
  - 后端启动步骤
  - 引擎启动步骤
  - 前端启动步骤
  - 验证步骤（运行 verify-pipeline.sh）
  - 故障排查指南

**Deliverables**：
- `scripts/setup-loki.sh` - Loki 自动部署脚本（Bash）
- `scripts/verify-pipeline.sh` - 端到端验证脚本（Bash）
- `scripts/test-pod.yaml` - 测试 Pod 配置文件
- `scripts/README.md` - 脚本使用说明
- `specs/001-mvp-core-loop/quickstart.md` - 快速启动指南（已更新）

**Done**：
- 验证脚本能稳定复现完整闭环（3-5 分钟完成）
- Loki 部署脚本能自动部署 Loki Stack（2-3 分钟完成）
- 快速启动指南清晰易懂（新用户能按步骤操作）
- 验证脚本输出清晰的成功/失败信息
- 快速启动指南包含常见问题排查（11 个常见问题）
- 所有脚本适配 macOS/Linux Bash 环境
- 包含详细的故障排查步骤和解决方案

**Dependencies**: T028

---

## 演示验收 Checklist（10 分钟内完成）

完成所有任务后，按以下步骤验证完整闭环：

- [ ] **Step 1**: 启动后端服务（`uvicorn backend.main:app --reload`）
- [ ] **Step 2**: 启动规则引擎（`python -m backend.engine.worker`）
- [ ] **Step 3**: 启动前端服务（`cd frontend && npm run dev`）
- [ ] **Step 4**: 访问前端界面（`http://localhost:3000`）
- [ ] **Step 5**: 创建关键词规则（名称="测试错误告警"，关键词="ERROR"，命名空间="demo"）
- [ ] **Step 6**: 部署测试 Pod（`kubectl apply -f scripts/test-pod.yaml`）
- [ ] **Step 7**: 等待 60 秒，刷新告警列表页面
- [ ] **Step 8**: 验证告警列表中出现新告警
- [ ] **Step 9**: 点击告警查看详情，验证样例日志正确
- [ ] **Step 10**: 查看引擎控制台输出，验证通知日志存在

**预期结果**：
- 告警列表中出现 1 条告警
- 告警详情包含完整信息（规则名称、严重级别、命中次数、样例日志）
- 引擎控制台输出包含通知日志（JSON 格式，包含 `event="alert_notification"`）

---

## 关键风险点

### 风险 1: Loki URL 配置与网络连通性

**描述**：Loki 服务可能运行在 Minikube 内部，本地 Mac 环境无法直接访问。

**缓解措施**：
- 使用 `kubectl port-forward` 将 Loki 服务暴露到本地（如 `localhost:3100`）
- 在 `.env` 文件中配置正确的 Loki URL
- 在引擎启动时验证 Loki 连通性（发送测试查询）

### 风险 2: 日志时间戳与时区处理

**描述**：Loki 返回的日志时间戳可能是纳秒级 Unix 时间戳，需要正确解析和转换。

**缓解措施**：
- 在 Loki 客户端中实现时间戳解析逻辑（纳秒转 datetime）
- 统一使用 UTC 时区（避免时区混乱）
- 在前端展示时转换为本地时区

### 风险 3: SQLite 并发写入限制

**描述**：SQLite 不支持高并发写入，引擎和 API 服务同时写入可能导致锁冲突。

**缓解措施**：
- MVP 阶段引擎和 API 服务运行在同一进程（避免并发写入）
- 使用 SQLAlchemy 的连接池和重试机制
- 如果出现锁冲突，考虑切换到 PostgreSQL

---

**下一步**：开始执行 Phase 1 任务，建立后端骨架与数据模型。