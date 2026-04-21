# Proposal: 架构水平扩展升级

## Why

当前 LogSentinel 为单机 Demo 架构，存在多个无法承接生产环境的硬瓶颈：

- **SQLite 单文件存储** 在并发连接下会锁表；无连接池配置导致每次请求新建连接
- **Rule Worker 单进程串行评估** 规则，10 条规则 × 3s Loki 查询 = 30s，已触及调度间隔上限；单副本宕机即全量规则停摆
- **进程内状态**（窗口计数器、冷却缓存）导致 Worker 无法水平扩展，重启即丢失
- **Loki 查询在协程中使用同步 `requests.get()`** 阻塞事件循环
- **通知同步发送** 失败会阻塞规则评估；无重试与补偿
- **前端轮询** 查看告警，无实时推送
- **窗口计数器现存 Bug**：按 `rule_id` 全局计数而非按 `group_by` 分组，导致阈值判定与分组告警的语义不一致

本次作为毕业设计主线课题「架构设计层面支持多节点水平扩展」的核心升级，为后续压测验证提供可扩展的基础。

## What Changes

### 存储层
- **BREAKING**：SQLite 直接替换为 PostgreSQL，不保留 SQLite 代码与数据迁移脚本
- 引入 SQLAlchemy 连接池配置（`AsyncAdaptedQueuePool` + `asyncpg` 驱动）
- 补齐关键索引，`alerts.hit_count` 升级为 `BIGINT`
- 引入 Alembic 管理数据库迁移

### Redis 引入
- 单节点 Redis 承载：分布式锁、窗口计数器 ZSET、Loki 查询缓存、告警冷却、Worker 心跳、WebSocket pub/sub
- Python 客户端统一使用 `redis-py >= 4.2`（内置 asyncio）

### Rule Worker 水平扩展
- 引入**哈希取模分片**：`rule_id % len(alive_workers)` 决定规则归属
- Worker 通过 Redis 心跳注册存活状态（5s 续期，15s TTL）
- Redis 分布式锁兜底 rebalance 瞬间的重复执行
- 每轮评估并发执行（`asyncio.Semaphore` 限并发数）
- 固定副本数 Worker × 3，不使用 HPA

### 窗口计数器重构
- **BREAKING**：窗口计数器从内存 `dict[rule_id]` 改为 Redis ZSET，Key 粒度细化到 `(rule_id, fingerprint)`，修复分组计数 Bug
- 数据结构：ZSET，member 为 `{timestamp_ms}:{uuid8}` 保证唯一，score 为时间戳
- 单 Key 上限保护：`ZCARD > 100000` 时截断最老元素
- Key TTL：每次 `ZADD` 后 `EXPIRE 2 × window_seconds`
- 规则未定义 `group_by` 时，视作单一默认分组统一处理

### Loki 查询异步化
- `requests` 替换为 `aiohttp`
- 查询结果缓存（Redis STRING，TTL 10s）
- QPS 限流（`aiolimiter`，默认 50 QPS，本副本粒度）
- 指数退避重试（最多 3 次，1s/2s/4s）

### 通知路径解耦
- **BREAKING**：通知语义由同步变为"至少一次交付"
- 进程内 `asyncio.Queue` 解耦 Evaluator 与 Notifier
- `notifications` 表新增 `status`（`pending/sent/failed`）、`retry_count`、`error_message`
- Worker 启动时扫表补发 `status=pending` 的通知，通过 CAS 防并发重复处理
- 失败可通过 `GET /api/notifications?status=failed` 查询

### 告警实时推送
- API 层引入 WebSocket 端点 `/ws/alerts`
- AlertManager 创建/更新告警时 `PUBLISH alerts:new`
- 前端 `AlertList` 从被动刷新改为实时更新，断连重连时主动拉取 REST 补齐

### 部署
- Helm Umbrella Chart 统一编排，第三方组件（PG/Redis/Loki）通过 `helm pull` 引入为 subchart
- 单节点 K3s v1.34.3 部署，`podAntiAffinity` 使用软约束
- NodePort 暴露 API + WebSocket，不引入 Nginx/Ingress
- 所有 Pod 配置 `resources.requests/limits`，API 使用 `gunicorn -w 4` 多进程

## Capabilities

### New Capabilities

- `log-query`: Loki 日志查询能力，规范异步查询、结果缓存 TTL 与 QPS 限流行为
- `notification-delivery`: 通知交付能力，规范至少一次交付、持久化补偿、重试退避与失败可查询
- `alert-lifecycle`: 告警生命周期能力，涵盖窗口阈值按分组判定、窗口计数器外置到 Redis、实时 WebSocket 推送

### Modified Capabilities

_无_。当前 `openspec/specs/` 为空（MVP 能力尚未回填），本次作为首批正式 spec 建立。

## Impact

### 受影响代码

- `backend/database/session.py`：驱动切换为 `asyncpg`，配置连接池
- `backend/database/redis.py`（新增）：全局 Redis 连接池
- `backend/database/migrations/`（新增）：Alembic 迁移脚本
- `backend/engine/worker.py`：主循环改造，新增分片、心跳、并发评估
- `backend/engine/evaluator.py`：删除内存 `window_counters`，按 fingerprint 判定阈值
- `backend/engine/window_counter.py`：重写为 `RedisWindowCounter`（ZSET 版）
- `backend/engine/sharding.py`（新增）：Worker 心跳与哈希取模分片
- `backend/engine/lock.py`（新增）：Redis 分布式锁
- `backend/engine/fingerprint.py`（新增）：fingerprint 共用函数
- `backend/engine/loki_client.py`：`requests` → `aiohttp`，加缓存与限流
- `backend/engine/alert_manager.py`：Alert 变更时 `PUBLISH alerts:new`
- `backend/notifier/queue.py`（新增）：`asyncio.Queue` 与 Notifier Worker 协程
- `backend/notifier/recovery.py`（新增）：启动时扫表补发
- `backend/models/notification.py`：新增 `status`、`retry_count`、`error_message` 字段
- `backend/api/notifications.py`（新增）：失败通知查询 API
- `backend/api/ws.py`（新增）：WebSocket `/ws/alerts`
- `backend/main.py`：注册新路由；改造 lifespan 初始化 Redis、补偿扫表、Notifier Worker
- `frontend/src/services/websocket.ts`（新增）：WebSocket 封装与重连
- `frontend/src/pages/AlertList.tsx`：订阅 WebSocket，断连重连时 REST 补齐

### 依赖变更

- 新增 Python 依赖：`asyncpg>=0.29`、`redis>=4.2,<6`、`aiohttp>=3.9`、`aiolimiter>=1.1`、`alembic>=1.13`
- 移除：`aiosqlite`

### 部署资产

- `helm-charts/logsentinel/`（新增）：Chart.yaml、values.yaml、templates/
- `helm-charts/logsentinel/charts/`：`helm pull` 下载的 postgresql / redis / loki subchart
- `docker-compose.yaml` 更新：替换 SQLite 为 PG + Redis；engine 支持多副本；api 改 gunicorn 多进程

### 数据与破坏性变更

- SQLite 数据库文件 `data/logsentinel.db` 不再使用，已有数据不迁移（MVP 阶段可接受）
- 通知语义由同步调用改为最终一致（至少一次）
- 窗口阈值判定从"全局计数"变为"分组计数"——已有规则行为可能改变（修复 Bug）

### 风险与回滚

- **风险 1**：Redis 宕机导致 Worker 分片、锁、窗口失效。**缓解**：AOF 持久化；Worker 启动时探活 Redis，未就绪则退出由 K8s 拉起
- **风险 2**：通知补偿扫表可能重复发送。**缓解**：`UPDATE ... WHERE status='pending' RETURNING` 原子 CAS
- **风险 3**：WebSocket 多副本广播导致连接分布不均。**缓解**：每个 API 副本独立订阅 Redis，各自推送
- **回滚**：按 P1→P2→P3 三阶段推进，每阶段打 git tag；任一阶段出现不可修复问题时回退到上一阶段 tag；SQLite 已删除，回滚需手动准备空白 PG 实例
