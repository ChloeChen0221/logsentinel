# Design: 架构水平扩展升级

## Context

当前 LogSentinel 为单机 Demo 架构：FastAPI 单进程 + SQLite + 单 Rule Worker 串行评估 + 同步 Loki 查询 + 同步通知。具体瓶颈已在 `proposal.md` 的 Why 中枚举，本设计承接 proposal 的 Capabilities 变更，给出**跨模块联动决策**与**关键实现抉择**。

**关键约束：**

- Python 3.11（Docker 基础镜像 `python:3.11-slim`；生产与开发环境一致）
- 单节点 K3s v1.34.3 部署，PG / Redis / Loki 均单副本
- Worker 固定 3 副本，API 固定 2 副本，不启用 HPA
- 无 Nginx / Ingress，NodePort 直连
- MVP 阶段无数据保留需求，SQLite 可直接 drop

---

## Goals / Non-Goals

**Goals:**

- 规则评估能力随 Worker 副本数线性扩展；单副本宕机不中断整体评估
- Worker 无状态化：进程内状态（窗口计数、冷却缓存）全部外置到 Redis
- I/O 路径全面异步：Loki 查询 / DB / 通知不阻塞事件循环
- 修复窗口阈值判定与分组告警的语义不一致 Bug
- 通知至少一次交付，崩溃后可自动补发
- 告警实时推送前端

**Non-Goals:**

- 多节点部署 HA（PG 主从、Redis Sentinel、Loki 微服务）—— 未来工作
- K8s HPA 自动扩缩容 —— 未来工作
- 告警治理（Silence / Inhibit / 分组聚合）—— 未来工作
- 冷热数据分离与历史归档 —— 未来工作
- 多租户隔离 —— 未来工作
- 保留 SQLite 数据迁移能力

---

## Decisions

### D1：SQLite → PostgreSQL 直接替换，不保留迁移路径

**决策：** 删除 `aiosqlite` 驱动、`data/logsentinel.db`、docker volume；由 Alembic 基于 PG schema 生成**新的**初始迁移；首次启动执行 `alembic upgrade head`。

**选型对比：**

| 方案 | 优点 | 缺点 |
|---|---|---|
| A. 双轨迁移（sqlite dump → pg restore） | 保留现有数据 | 无生产数据；一次性脚本增加维护成本；代码保留 SQLite 分支降低可维护性 |
| **B. 直接替换**（本次选择） | 代码干净，单一驱动路径 | 无法从旧数据库恢复（本次不需要） |

**Schema 变更：**

| 表 | 变更 |
|---|---|
| `notifications` | 新增 `status VARCHAR(16) NOT NULL DEFAULT 'pending'`（枚举 `pending/sent/failed`）<br>新增 `retry_count INTEGER NOT NULL DEFAULT 0`<br>新增 `error_message TEXT NULL`<br>新增索引 `(status, created_at)` 加速补偿扫表 |
| `alerts` | `hit_count INTEGER` → `BIGINT`<br>新增索引 `(rule_id, last_seen DESC)` |
| `rules` | 新增索引 `(enabled, last_query_time)` |

**连接池配置：**

```python
engine = create_async_engine(
    "postgresql+asyncpg://logsentinel:xxx@postgres:5432/logsentinel",
    poolclass=AsyncAdaptedQueuePool,
    pool_size=20,
    max_overflow=10,
    pool_pre_ping=True,
    pool_recycle=3600,
)
```

**Alembic 目录：** `backend/database/migrations/`，`alembic.ini` 放于 `backend/` 下。

---

### D2：Redis 客户端统一使用 `redis-py >= 4.2`

**选型对比：**

| 方案 | 评价 |
|---|---|
| `aioredis` | 已合并进 `redis-py`，不再独立维护 |
| **`redis-py >= 4.2` asyncio 接口** | 官方维护；API 稳定；文档充分 |
| `coredis` | 社区规模小 |

**初始化：** `backend/database/redis.py` 提供 `get_redis()` 依赖注入，使用 `ConnectionPool.from_url`。

---

### D3：Worker 分片策略 —— 哈希取模 + 心跳 + 分布式锁

**决策：** 使用**简单哈希取模**（`rule_id % len(alive_workers)`），**不是**一致性哈希。通过 Redis 分布式锁兜底 rebalance 瞬间的重复执行。

**选型对比：**

| 方案 | 适用量级 | rebalance 开销 | 本次选择 |
|---|---|---|---|
| **哈希取模**（本次选择） | 100~10k 规则 | 副本数变化时几乎所有规则重新分配 | ✓ 简单；副本数固定 |
| 一致性哈希 | 同上 | 仅 1/N 规则重新分配 | 毕设副本数固定为 3，优势不明显 |
| Kafka + 消费组 | 10w+ 规则 | Kafka 自身管理 | 过度工程 |

**坦诚披露：** 本方案不是"一致性哈希"——副本数变化时会触发 rebalance 风暴。分布式锁（D4）在此间隙内承担**防止同一规则被多副本重复评估**的兜底职责。由于固定副本数 3，rebalance 仅发生在 K8s 调度重启瞬间。

**分片流程：**

```
Worker 启动
   │
   ▼
注册心跳 SET worker:{id} = "1" EX 15
   │
   ▼
启动独立心跳协程（每 5s 续期一次）
   │
   ▼
每轮评估周期（默认 30s）开始：
   1. 读取存活列表 KEYS worker:* → sorted()
   2. 加载 enabled 规则
   3. 过滤：workers[rule_id % len(workers)] == self.id
   4. 并发评估（asyncio.Semaphore 限并发）
        对每条规则：
          - SET lock:rule:{rid} = worker_id NX EX 60
          - 若成功 → evaluate_rule → DEL lock
          - 若失败 → skip（其他副本在处理）
```

**心跳与评估周期解耦：** 心跳续期由独立协程负责（`HEARTBEAT_INTERVAL_SECONDS=5`，远小于 `HEARTBEAT_TTL_SECONDS=15`），不依赖评估周期。原因：若在 `_execute_cycle` 内续期，评估周期 30s > TTL 15s 会导致心跳中途过期，多副本 `KEYS worker:*` 视图不一致，分片结果抖动。独立协程保证任何时刻所有存活 Worker 的心跳 Key 都在 TTL 内。

**存活判定：** Worker 宕机后 15s 内心跳 Key 过期，其他副本下一轮周期自动 rebalance。

---

### D4：分布式锁使用 `SET NX EX`，不引入 Redlock

**选型对比：**

| 方案 | 评价 |
|---|---|
| **`SET NX EX`**（本次选择） | 单节点 Redis 下正确性足够；无主从分裂 |
| Redlock（多节点仲裁） | 需要 ≥3 个独立 Redis；单节点无收益 |
| Lua 脚本 CAS 释放 | 避免"释放了别人的锁"；下一次迭代可加，本次保持简单 |

**已知风险：** 当前 `DEL` 不带 value 检查，若锁因 TTL 过期后被另一 Worker 获取，原持有者执行完 `DEL` 会删掉新持有者的锁。锁 TTL=60s 远大于单次评估耗时（<5s），正常运行中不会出现。若未来评估耗时接近 TTL，升级为 Lua 脚本 CAS。

---

### D5：窗口计数器使用 Redis ZSET，按 `(rule_id, fingerprint)` 分组

**分组 Bug 修复：**

```
修复前（当前代码）：
  self.window_counters: dict[int, WindowCounter] = {}  # key 仅 rule_id
  → 规则有 group_by=["namespace"] 时，不同 namespace 共享同一计数器
  → 各分组单独都不达标，合计达标也会触发

修复后：
  key = f"window:{rule_id}:{fingerprint}"
  fingerprint = sha256({rule_id, sorted(group_by_values)}).hexdigest()
  → 每组独立计数器
  → 未设 group_by 的规则使用 group_by={} 作为单一默认分组
```

**Redis Key 设计：**

| Key 格式 | 类型 | Member | Score | TTL |
|---|---|---|---|---|
| `window:{rid}:{fp}` | ZSET | `{ts_ms}:{uuid8}` | `ts_ms` | `2 × window_seconds`（每次 ZADD 后 EXPIRE） |

**核心操作：**

```python
# 添加事件
ZADD window:{rid}:{fp} {ts_ms} "{ts_ms}:{uuid8}"
EXPIRE window:{rid}:{fp} (2 * window_seconds)
# 上限保护
count = ZCARD window:{rid}:{fp}
IF count > 100_000:
    ZREMRANGEBYRANK window:{rid}:{fp} 0 (count - 100_001)

# 读取计数
ZREMRANGEBYSCORE window:{rid}:{fp} -inf (now_ms - window_ms)
ZCARD window:{rid}:{fp}
```

**数据结构选型对比：**

| 方案 | 精度 | 内存 | 迁移成本 |
|---|---|---|---|
| **ZSET**（本次选择） | 秒级严格滑动窗口 | 与窗口内事件数线性 | 语义与现内存版 deque 等价 |
| HASH + 桶（近似窗口） | 桶粒度（如 10s） | 恒定小 | 语义变更，需改规则阈值含义 |

---

### D6：Loki 客户端用 aiohttp + Redis 缓存 + aiolimiter

**限流粒度：** 每副本本地限流（非 Redis 全局令牌桶）。

**选型对比：**

| 方案 | 评价 |
|---|---|
| **本地 aiolimiter**（本次选择） | 实现简单；无跨副本开销；整体 QPS = 本地上限 × 副本数 |
| Redis 令牌桶（全局限流） | 精确但每次调用多一次 Redis 往返；毕设收益不显著 |
| 无限流 | Loki 过载时无保护 |

**Redis Key 设计（缓存）：**

| Key 格式 | 类型 | Value | TTL |
|---|---|---|---|
| `loki:{md5(query+start+end)}` | STRING | Loki 响应 JSON | 10s |

---

### D7：通知解耦使用进程内 `asyncio.Queue`，不引入 Celery

**选型对比：**

| 方案 | 评价 |
|---|---|
| **asyncio.Queue + DB 补偿**（本次选择） | 与现有 asyncio 技术栈统一；DB 持久化；"至少一次"语义清晰 |
| Celery + Redis Broker | 引入额外技术栈（broker + worker + flower）；容器数量 +3 |
| Redis List 做队列 | 跨副本共享但引入 consumer group 复杂度；单机场景收益小 |

**补偿扫表的并发安全：**

```sql
-- 补偿 Worker 使用 CAS 抢占
UPDATE notifications
SET status = 'sending', retry_count = retry_count
WHERE id = :id AND status = 'pending'
RETURNING *;
-- 若 RETURNING 为空，说明其他 Worker 已抢占，跳过
```

**重试策略：** 最多 3 次，间隔 1s / 2s / 4s（指数退避）；仍失败 → `status=failed`，`error_message` 记录最后一次异常。

---

### D8：WebSocket 实时推送 —— Redis pub/sub 广播

**选型对比：**

| 方案 | 评价 |
|---|---|
| **Redis pub/sub**（本次选择） | 多 API 副本下各自订阅，都能收到消息并广播给各自客户端；现有 Redis 已就位 |
| Server-Sent Events (SSE) | 单向更简单，但 WebSocket 与 Ant Design 集成更主流 |
| 长轮询 | 延迟和资源占用差 |

**多副本时序：**

```
 AlertManager (任一 Worker 副本)
        │  创建/更新 Alert
        ▼
   PUBLISH alerts:new {...}
        │
        ▼
   ┌──────────────────┐
   │  Redis pub/sub   │
   └────┬───────┬─────┘
        │       │  广播到所有订阅者
        ▼       ▼
   API 副本 1    API 副本 2
        │         │
        ▼         ▼
   WS Client A   WS Client B / C
```

**可靠性：** WebSocket 连接期间断连可能漏消息，前端重连时主动 `GET /api/alerts` 补齐。

**Channel 设计：**

| Channel | Payload |
|---|---|
| `alerts:new` | `{"id": 123, "rule_id": 5, "fingerprint": "...", "last_seen": "2026-04-20T..."}` |

---

### D9：所有 Redis Key 命名规范（统一汇总）

| 前缀 | 类型 | 用途 | TTL |
|---|---|---|---|
| `worker:{id}` | STRING | Worker 心跳 | 15s |
| `lock:rule:{rid}` | STRING | 规则分布式锁 | 60s |
| `window:{rid}:{fp}` | ZSET | 窗口计数器 | 2×window_seconds |
| `loki:{hash}` | STRING | Loki 查询缓存 | 10s |
| `cooldown:{fp}` | STRING | 告警冷却状态 | `rule.cooldown_seconds` |
| `alerts:new` | pub/sub channel | 告警实时推送 | — |

---

### D10：Worker ID 来源 fallback

```python
worker_id = (
    os.getenv("WORKER_ID")              # K8s downward API 注入 pod name
    or os.getenv("HOSTNAME")            # 容器默认 hostname
    or f"local-{uuid.uuid4().hex[:8]}"  # 本地开发
)
```

---

## Risks / Trade-offs

- **[风险] Redis 单点宕机导致分片、锁、窗口全部失效** → Redis 开启 AOF `appendfsync everysec`；Worker 启动时探活 Redis，未就绪则退出由 K8s 拉起；未来工作引入 Sentinel

- **[风险] SQLite 删除后无法回滚到原状** → 迁移前打 git tag `v0.3.0-sqlite` 作为回滚锚点；MVP 阶段无生产数据，回滚成本可接受

- **[风险] 通知补偿扫表下多副本重复处理** → 使用 `UPDATE ... WHERE status='pending' RETURNING` 原子 CAS

- **[风险] WebSocket 断连期间告警漏推** → 前端重连后主动 `GET /api/alerts` 补齐

- **[风险] 分布式锁 TTL 过期导致双重执行** → 锁 TTL 60s 远大于单规则评估耗时；若未来评估耗时接近 TTL，升级为 Lua 脚本 CAS

- **[风险] 哈希取模在副本数变化时 rebalance 抖动** → 固定副本数 3，rebalance 仅发生在 K8s 调度重启瞬间；分布式锁保证不重复执行

- **[风险] 单节点 ZSET 无限膨胀压垮 Redis** → 单 Key 上限 100000 元素截断 + 2×window TTL 自动清理

- **[Trade-off] 通知语义由"同步阻塞"变"至少一次最终一致"** → 使用方需知悉下游（Webhook/Email）需自行幂等去重

- **[Trade-off] Loki 查询限流为副本本地令牌桶** → 整体 QPS = 50 × 副本数 = 150 QPS，压测前需确认 Loki 承载能力

---

## Migration Plan

**分阶段推进：**

1. **P1 存储层（tasks.md §1）**：替换 SQLite 为 PG；引入 Redis；Alembic 迁移；索引补齐
2. **P2 Worker 水平扩展（tasks.md §2）**：分片 + 心跳 + 分布式锁；窗口计数器改 Redis ZSET；evaluator 按 fingerprint 判定
3. **P3 路径异步化（tasks.md §3）**：Loki aiohttp + 缓存 + 限流；asyncio.Queue 通知 + 补偿扫表；WebSocket 推送；API 多进程

**每阶段结束打 git tag（`v0.4.0-p1`/`v0.4.0-p2`/`v0.5.0`）作为回滚锚点。**

**回滚策略：**

- 出现不可修复问题时回退到上一阶段 tag
- 由于 SQLite 已删除，回滚到 MVP 需手动重建空白 PG + 重新加载规则配置

---

## Open Questions

- 前端 WebSocket 断线重连的"补齐"是否需要传递 `since` 时间戳给 REST API，还是直接全量拉取前 N 条？（实现细节，tasks 阶段决定）
- `notifications.status` 是否需要 `sending` 中间态？当前倾向不引入，通过 CAS 抢占实现隔离
- 压测方案是否纳入本 change？当前倾向单独 change，本次暂不包含
