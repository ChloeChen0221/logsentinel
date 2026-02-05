<!--
Sync Impact Report:
- Version change: template → 1.0.0
- Initial constitution creation
- Added sections: Core Principles (9), Technology Stack, Repository Structure, Non-Goals, Phase Gates, Governance
- Templates requiring updates: ⚠ .specify/templates/* (pending creation)
- Follow-up: Create corresponding spec/plan/tasks templates aligned with these principles
-->

# LogSentinel 项目宪法

**K8s 集群日志告警平台 - 基于规则引擎的毕业设计项目**

## 核心原则

### I. 规范驱动开发（MUST）

**不可协商：任何新功能必须先写 spec，再 plan/tasks，再 implement。**

- 禁止"先写代码后补文档"的行为
- 每个功能必须有明确的验收标准
- spec 文档必须包含：功能描述、数据模型、API 合约、验收步骤
- 变更现有功能必须先更新 spec，再同步代码

**理由**：单人项目容易陷入"边写边想"的混乱，规范驱动确保思路清晰、可追溯。

### II. 最小可用闭环优先（MUST）

**优先保证 end-to-end 链路可用，再做增强功能。**

- 第一优先级：日志可查 → 规则触发 → 告警入库 → 通知 → UI 可见
- 基础功能先于加分项（如规则测试、告警统计、高级静默）
- 每个里程碑必须有可演示的完整流程
- 避免过度优化未验证的功能

**理由**：毕业设计时间有限，必须确保核心价值链优先完成。

### III. 数据模型先定（MUST）

**Rule / Alert / Silence / Notification 的 schema 与 API contract 必须先稳定。**

- 数据库表结构与 Pydantic 模型同步维护
- API 合约变更必须同步前后端代码
- 提供数据库迁移脚本（即使是 SQLite）
- 字段变更必须评估历史数据兼容性

**理由**：前后端分离架构下，数据模型不稳定会导致返工成本倍增。

### IV. 可观测与可复现（MUST）

**关键流程必须有结构化日志；提供一键启动与验证脚本。**

- 规则评估、告警生成、通知发送必须打印结构化日志（JSON 格式）
- 日志必须包含：timestamp, level, module, rule_id, alert_id, action
- `/scripts` 目录必须提供：
  - `dev-setup.sh` - 本地环境初始化
  - `verify-pipeline.sh` - 端到端验证脚本
  - `generate-test-logs.sh` - 模拟日志生成工具
- 每个里程碑必须有清晰的验收步骤文档

**理由**：便于调试、演示与导师验收。

### V. 测试策略（MUST/SHOULD）

**不过度测试，但关键逻辑必须有测试覆盖。**

- **MUST** 有单元测试：
  - 规则评估逻辑（pattern/rate/sequence）
  - 告警去重与冷却算法
  - 静默匹配逻辑
- **SHOULD** 有集成测试：
  - API 端点基础场景（创建规则、查询告警）
  - 引擎与 Loki 交互
- **MAY** 有端到端测试：
  - 完整告警流程（时间成本高，手动验证为主）
- 测试框架：pytest + pytest-asyncio

**理由**：平衡测试价值与开发效率，避免为了测试而测试。

### VI. 代码风格与质量（MUST）

**统一格式化、类型检查与依赖管理。**

- Python 代码必须使用 `ruff` + `black` 格式化
- 必须使用 type hints（Python 3.11+ 语法）
- 禁止重复造轮子：优先使用成熟库（FastAPI、Pydantic、httpx）
- 依赖保持克制：仅引入必要的包，避免依赖膨胀
- 前端代码必须使用 ESLint + Prettier

**理由**：保持代码可读性与可维护性，降低 AI 辅助开发的理解成本。

### VII. 安全底线（MUST）

**敏感信息不进仓库；对外接口有基础鉴权。**

- Secret（数据库密码、邮件凭证、webhook URL）必须通过环境变量或 K8s Secret 注入
- `.env.example` 提供模板，真实 `.env` 不进版本控制
- API 接口必须有最小鉴权（开发期可用简单 token，不可完全裸奔）
- 日志与告警内容避免泄露 K8s namespace、IP、敏感字段
- 用户输入必须验证（Pydantic 校验 + SQL 注入防护）

**理由**：即使是毕业设计也需要基本安全意识，演示时不能暴露敏感信息。

### VIII. 性能边界（MUST）

**引擎必须增量拉取；对每条规则设置查询上限。**

- 引擎从 Loki 拉取日志必须使用 cursor 机制（记录 last_query_time）
- 每条规则的单次查询范围不超过 5 分钟
- 对高频规则设置防抖（最小评估间隔 30 秒）
- 避免全量扫描告警表（使用索引 + 分页）
- 通知模块必须有限流机制（同一告警 5 分钟内最多发送 1 次）

**理由**：Loki 不擅长大范围查询，必须控制单次查询成本；避免告警风暴。

### IX. UI 原则（SHOULD）

**围绕三页完成核心闭环，界面简洁实用。**

- **核心页面**：
  1. 规则列表与编辑页（增删改查规则）
  2. 告警列表页（筛选、分页、状态变更）
  3. 告警详情页（日志回溯、操作历史）
- **可选加分项**：
  - 规则测试接口（输入日志样本，预览匹配结果）
  - 告警统计看板（按规则/时间聚合）
- UI 组件使用 Ant Design，保持风格一致
- 响应式设计非必需，优先适配桌面端（演示用）

**理由**：毕业设计评审关注功能完整性而非 UI 复杂度。

## 技术栈约束

### 后端（MUST）

- **语言**：Python 3.11+
- **API 框架**：FastAPI（异步优先）
- **数据模型**：Pydantic v2
- **ORM**：SQLAlchemy 2.0（支持 async）
- **数据库**：开发期 SQLite；架构保持可切换 PostgreSQL/MySQL
- **缓存/状态**：Redis（用于 cursor、去重、冷却状态）
- **HTTP 客户端**：httpx（异步）
- **日志**：structlog（结构化日志）

### 引擎与通知（MUST）

- **引擎**：Python worker，独立进程或与 API 同进程部署
- **调度**：APScheduler 或简单的 while loop + asyncio.sleep
- **通知**：统一接口 `send(channel, payload)`，支持 console/email/webhook
- **重试机制**：tenacity 库

### 前端（MUST）

- **框架**：React 18+
- **UI 库**：Ant Design 5.x
- **状态管理**：useState/useContext（简单场景）或 Zustand（可选）
- **HTTP 客户端**：axios
- **构建工具**：Vite

### 部署（MUST）

- **容器**：Docker（后端/前端独立镜像）
- **编排**：Kubernetes YAML（Deployment/Service/ConfigMap/Secret）
- **基础组件**：
  - Loki + Promtail：Helm 部署
  - Grafana：Helm 部署（用于验证与演示）
  - Redis：StatefulSet 或 Helm
- **本地测试**：Minikube（Mac）

## 仓库结构约束

**MUST 遵循以下目录结构：**

```
logsentinel/
├── .specify/              # Speckit 规范文档
│   ├── memory/
│   │   └── constitution.md
│   └── templates/
├── backend/               # 后端代码
│   ├── api/              # FastAPI 路由
│   ├── engine/           # 规则引擎
│   ├── notifier/         # 通知模块
│   ├── models/           # 数据模型
│   ├── schemas/          # Pydantic schemas
│   ├── database/         # 数据库连接与迁移
│   ├── tests/            # 测试
│   └── main.py
├── frontend/              # 前端代码
│   ├── src/
│   │   ├── pages/
│   │   ├── components/
│   │   └── services/
│   └── package.json
├── deploy/                # 部署配置
│   ├── k8s/              # Kubernetes manifests
│   ├── helm/             # Helm values
│   └── docker/           # Dockerfiles
├── scripts/               # 开发与验证脚本
│   ├── dev-setup.sh
│   ├── verify-pipeline.sh
│   └── generate-test-logs.sh
├── docs/                  # 补充文档（可选）
├── .env.example
├── requirements.txt
└── README.md
```

## 非目标声明

**以下功能明确不在本项目范围内，避免过度工程化：**

- ❌ **分布式高可用**：不做引擎集群、分片、选主
- ❌ **多租户**：不做用户隔离、权限体系、配额管理
- ❌ **复杂权限**：不做 RBAC，最多简单 token 鉴权
- ❌ **告警路由**：不做复杂的告警分组、路由树、escalation
- ❌ **历史数据归档**：不做冷热分离、长期存储优化
- ❌ **前端高级特性**：不做主题切换、国际化、移动端适配
- ❌ **性能压测**：不做大规模并发测试、性能调优

**如需扩展以上功能，必须先修订宪法并评估时间成本。**

## 治理规则

### 宪法优先级

**本宪法超越所有其他实践文档与口头约定。**

- 所有 spec/plan/tasks/implement 产出必须符合本宪法约束
- 宪法与实际冲突时，优先修订宪法再推进实现
- 快速原型可豁免部分非 MUST 条款，但必须在 spec 中明确声明

### 修订流程

- **MINOR 变更**（新增原则、扩展约束）：更新版本号 + 记录变更原因
- **MAJOR 变更**（删除/重定义原则）：必须评估影响范围 + 迁移计划
- **PATCH 变更**（措辞优化、示例补充）：直接更新

### 合规检查

- 每个 spec 文档必须包含"宪法合规性检查"章节
- 每个 plan 必须验证是否违反核心原则
- 实现前必须通过 Phase Gate 检查
- AI 辅助开发时，将本宪法作为 context 提供

### 复杂度辩护

**任何增加架构复杂度的决策必须书面说明理由，并获得批准（自我批准或导师批准）。**

示例需要辩护的决策：
- 引入新的中间件或框架
- 修改数据库 schema 导致迁移成本
- 增加非核心功能模块

---

**版本**: 1.0.0  
**批准日期**: 2026-02-03  
**最后修订**: 2026-02-03

---

*本宪法是 LogSentinel 项目的根本准则，确保单人毕业设计在有限时间内高质量交付。*
