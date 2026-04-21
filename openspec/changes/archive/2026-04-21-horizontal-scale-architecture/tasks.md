# Tasks: 架构水平扩展升级

## 1. P1：存储层升级 — 依赖与配置

- [x] 1.1 在 `backend/requirements.txt` 新增 `asyncpg>=0.29`、`redis>=4.2,<6`、`alembic>=1.13`；移除 `aiosqlite`
- [x] 1.2 在 `backend/core/config.py` 新增配置项：`DATABASE_URL`（PG）、`REDIS_URL`、`REDIS_POOL_MAX_CONN`
- [x] 1.3 编写 `.env.example`，给出 PG / Redis 默认连接串示例

## 2. P1：存储层升级 — 数据库会话与 Redis 客户端

- [x] 2.1 改写 `backend/database/session.py` 使用 `asyncpg` + `AsyncAdaptedQueuePool`（`pool_size=20`、`max_overflow=10`、`pool_pre_ping=True`、`pool_recycle=3600`）
- [x] 2.2 校对现有 ORM 模型在 PG 下映射正确（`JSON` → `JSONB`、`DateTime(timezone=True)`）
- [x] 2.3 新增 `backend/database/redis.py` 提供 `get_redis()` 连接池 + FastAPI `Depends`
- [x] 2.4 应用启动时 `PING` Redis 探活，失败退出由 K8s 拉起

## 3. P1：存储层升级 — Schema 变更与 Alembic

- [x] 3.1 在 `backend/models/notification.py` 新增字段 `status`、`retry_count`、`error_message`
- [x] 3.2 在 `backend/models/alert.py` 将 `hit_count` 改为 `BigInteger`
- [x] 3.3 在 models 声明索引：`rules(enabled, last_query_time)`、`alerts(rule_id, last_seen DESC)`、`notifications(status, created_at)`、`notifications(alert_id, notified_at DESC)`
- [x] 3.4 在 `backend/` 初始化 `alembic init migrations`，配置从 `settings.DATABASE_URL` 读取
- [x] 3.5 执行 `alembic revision --autogenerate -m "initial schema for pg"` 生成初始迁移，人工检视索引与新字段
- [x] 3.6 应用启动流程调用 `alembic upgrade head`（或独立 init container）

## 4. P1：存储层升级 — 清理 SQLite 与验证

- [x] 4.1 打 git tag `v0.3.0-sqlite` 作为回滚锚点
- [x] 4.2 删除 `backend/data/` 目录及相关 `.gitignore` 规则
- [x] 4.3 删除 `docker-compose.yaml` 中 engine 容器的 SQLite volume 挂载
- [x] 4.4 本地 `docker-compose up` 启动 PG + Redis + 应用，验证 `GET /api/health` 正常
- [x] 4.5 手动 POST 创建规则，验证 PG 可查询到；通过 `psql` 确认表结构与索引符合 schema

## 4bis. P1：Helm 脚手架 — 最小可运行 Umbrella Chart

**里程碑对齐 `v0.4.0-p1`：Helm 能在 K3s 装出 PG + Redis + Loki + api + engine 单副本，且 `GET /api/health` 可达。**

- [x] 4bis.1 创建 `helm-charts/logsentinel/Chart.yaml`，声明 dependencies：`postgresql`（bitnami）、`redis`（bitnami）、`loki`（grafana）
- [x] 4bis.2 执行 `helm dependency update` 将 subchart `helm pull` 到 `charts/`；提交 `Chart.lock`，`.gitignore` 排除 `charts/*.tgz` 解压目录（按团队惯例）
- [x] 4bis.3 编写最小 `values.yaml`：PG/Redis 的密码、持久化 off（MVP 阶段）、Loki 单副本、logsentinel 的镜像与 tag
- [x] 4bis.4 编写 `templates/_helpers.tpl`：`logsentinel.fullname`、`logsentinel.labels`、`logsentinel.redisUrl`、`logsentinel.databaseUrl`（从 subchart 生成的 Service 名拼接）
- [x] 4bis.5 编写 `templates/api-deployment.yaml` + `api-service.yaml`（`replicas: 1`，NodePort 30080），环境变量 `DATABASE_URL` / `REDIS_URL` / `LOKI_URL` 从 helper 拼接
- [x] 4bis.6 编写 `templates/engine-deployment.yaml`（`replicas: 1`，复用同镜像 + `command: ["python", "-m", "engine.worker"]`）
- [x] 4bis.7 编写 `templates/secret.yaml` 存放 PG 密码（或引用 subchart 生成的 Secret）
- [x] 4bis.8 Alembic 迁移通过 `initContainer` 在 api pod 启动前执行 `alembic upgrade head`
- [x] 4bis.9 在 K3s 本地执行 `helm install logsentinel helm-charts/logsentinel`，验证所有 pod `Running`、`GET /api/health` 200、创建规则可持久化到 PG

## 5. P2：Worker 水平扩展 — 分片、锁、Worker ID

- [x] 5.1 新增 `backend/engine/sharding.py` 实现 `RuleSharding` 类（`heartbeat`、`alive_workers`、`owns`）
- [x] 5.2 实现 Worker ID fallback：`WORKER_ID` → `HOSTNAME` → `local-{uuid8}`
- [x] 5.3 新增 `backend/engine/lock.py` 提供 `async with redis_lock(redis, key, value, ttl)` 上下文管理器（`SET NX EX` + `DEL`）

## 6. P2：Worker 水平扩展 — 窗口计数器外置

- [x] 6.1 新增 `backend/engine/fingerprint.py` 抽取 fingerprint 计算共用函数
- [x] 6.2 重写 `backend/engine/window_counter.py` 为 `RedisWindowCounter`：`add`（ZADD + EXPIRE + 上限截断）+ `count`（ZREMRANGEBYSCORE + ZCARD）
- [x] 6.3 member 格式 `{ts_ms}:{uuid8}` 保证唯一；单 Key 上限 100000，超出 `ZREMRANGEBYRANK` 截断并记 `window_counter_truncated` 日志
- [x] 6.4 更新 `backend/tests/unit/test_window_counter.py` 覆盖分组独立、过期清理、上限截断三个场景

## 7. P2：Worker 水平扩展 — Evaluator 与 Worker 改造

- [x] 7.1 在 `backend/engine/evaluator.py` 删除 `self.window_counters: dict`，`_match_window_threshold` 按 `group_by` 分组 → 每组独立 fingerprint → 独立 `RedisWindowCounter.add/count`
- [x] 7.2 `group_by` 为空时 fingerprint 基于 `group_by={}` 计算（单一默认分组）
- [x] 7.3 在 `backend/engine/worker.py` `_execute_cycle`：调用 `sharding.heartbeat()` → 读存活列表 → 过滤 `my_rules` → `asyncio.Semaphore` 包装并发评估
- [x] 7.4 每条规则评估前 `async with redis_lock(...)`，失败则跳过

## 8. P2：Worker 水平扩展 — 部署与验证

- [x] 8.1 `docker-compose.yaml` **仅保留单副本 engine**（开发环境用途，不追求分布式验证）
- [x] 8.2 Helm Chart `engine-deployment.yaml` `replicas` 由 1 改为 3（通过 values 参数化，默认 3）
- [x] 8.3 配置 `podAntiAffinity preferredDuringSchedulingIgnoredDuringExecution`（软约束，单节点 K3s 允许同节点）
- [x] 8.4 通过 downward API 注入 `WORKER_ID` 为 pod name（`fieldRef: metadata.name`）
- [x] 8.5 在 `values.yaml` 暴露 `engine.replicas`、`engine.resources`、`engine.concurrency`（评估并发上限）
- [x] 8.6 验证：3 副本启动 10 条规则，每条规则只被一个副本执行；`kubectl delete pod` 任一副本后 15s 内被接管
- [x] 8.7 验证分组 Bug 修复：threshold=10 + group_by=namespace，ns=A 6 条 + ns=B 5 条命中时**不**触发告警

**里程碑对齐 `v0.4.0-p2`：Helm 能装出 3 副本 Worker，分片 + 心跳 + 锁在 K3s 上验证通过。**

## 9. P3：路径异步化 — Loki 客户端

- [x] 9.1 在 `requirements.txt` 新增 `aiohttp>=3.9`、`aiolimiter>=1.1`
- [x] 9.2 重写 `backend/engine/loki_client.py`：`aiohttp.ClientSession` 单例 + `AsyncLimiter(50, 1)` + Redis STRING 缓存（key=`loki:{md5}`，TTL 10s） + 3 次指数退避重试
- [x] 9.3 每次查询记录结构化日志：`query_hash`、`cache_hit`、`duration_ms`、`status`、`rule_id`
- [x] 9.4 新增/更新 `backend/tests/unit/test_loki_client.py` 覆盖缓存命中、限流等待、重试三场景

## 10. P3：路径异步化 — 通知队列与补偿

- [x] 10.1 新增 `backend/notifier/queue.py`：模块级 `notification_queue = asyncio.Queue(maxsize=10000)`；`enqueue_notification` 先 INSERT `status=pending`，再 `put_nowait`
- [x] 10.2 新增 `backend/notifier/consumer.py`：`notifier_worker()` 协程循环 `queue.get()` + 3 次指数退避；通过 CAS `UPDATE WHERE id=? AND status='pending'` 更新终态
- [x] 10.3 改造 `backend/engine/evaluator.py` `_handle_notification`：由直接调用改为 `await enqueue_notification(...)`
- [x] 10.4 新增 `backend/notifier/recovery.py`：启动时扫 `notifications WHERE status='pending'` 使用 CAS 抢占后重新入队
- [x] 10.5 在 Worker lifespan 中先调用 recovery，再启动 N 个 `notifier_worker()` 协程

## 11. P3：路径异步化 — 失败通知查询 API

- [x] 11.1 新增 `backend/schemas/notification.py`：`NotificationItem` / `NotificationListResponse`
- [x] 11.2 新增 `backend/api/notifications.py`：`GET /api/notifications?status=failed&page=&page_size=` 分页返回，按 `notified_at DESC` 排序
- [x] 11.3 在 `backend/main.py` 注册该 router

## 12. P3：路径异步化 — 告警实时推送

- [x] 12.1 在 `backend/engine/alert_manager.py` 的 `create_or_update_alert` 事务提交后 `await redis.publish("alerts:new", json.dumps({...}))`；Payload 含 `id`、`rule_id`、`fingerprint`、`last_seen`、`hit_count`
- [x] 12.2 新增 `backend/api/ws.py`：`@router.websocket("/ws/alerts")` 订阅 `alerts:new` 并推送；捕获 `WebSocketDisconnect` 清理
- [x] 12.3 在 `backend/main.py` 注册 WebSocket 路由
- [x] 12.4 新增 `frontend/src/services/websocket.ts` 封装连接与 5s 重连
- [x] 12.5 改造 `frontend/src/pages/AlertList.tsx`：`useEffect` 建立 WebSocket；收到消息后 prepend 或 update 行；重连时主动 `alertsService.list()` 补齐

## 13. P3：路径异步化 — API 多进程

- [x] 13.1 `docker-compose.yaml` api 服务 `command` 改为 `gunicorn backend.main:app -k uvicorn.workers.UvicornWorker -w 4 -b 0.0.0.0:8000 --timeout 60`
- [x] 13.2 Helm Chart API Deployment 启动命令同步更新
- [x] 13.3 Helm `api-service.yaml` 暴露 WebSocket 端口（与 HTTP 共用 8000，NodePort 30080），确认 `timeoutSeconds` 不会切断长连接
- [x] 13.4 `values.yaml` 新增 `api.replicas`（默认 2）、`api.workers`（gunicorn -w，默认 4）

## 14. P3：路径异步化 — 验证

- [x] 14.1 打开前端 AlertList，手动触发规则命中，**无需刷新**即可看到新告警
- [x] 14.2 人工构造 `status=pending` 记录后重启后端，验证补发成功
- [x] 14.3 杀掉单个消费者协程，补偿扫表后消息能被其他协程处理且不重复
- [x] 14.4 对 Loki 发起 100 次并发相同查询，实际 HTTP 请求数接近 1（缓存命中率≈100%）
- [x] 14.5 失败通知 API：构造 `status=failed` 记录，`GET /api/notifications?status=failed` 返回该记录

## 14bis. P3：Helm 生产化 — 资源、探针、前端

**里程碑对齐 `v0.5.0`：Helm 装出完整生产形态（2 API × 4 进程 + 3 Worker + WS + 前端），K3s 单节点跑通。**

- [x] 14bis.1 所有 Deployment 补 `resources.requests/limits`（values 可覆盖）
- [x] 14bis.2 api Deployment 加 `readinessProbe`（`/api/health`）与 `livenessProbe`（TCP 8000），延长 `initialDelaySeconds` 等 Alembic 迁移
- [x] 14bis.3 engine Deployment 加 `livenessProbe`（exec `pgrep -f engine.worker`）
- [x] 14bis.4 新增 `templates/frontend-deployment.yaml` + `frontend-service.yaml`（NodePort 30300），镜像 tag 通过 values 暴露
- [x] 14bis.5 `values.yaml` 汇总 image repository/tag、副本数、NodePort、资源限制、PG/Redis 密码（Secret 引用）
- [x] 14bis.6 `helm lint` + `helm template` 输出检查，确认 WS / HTTP / 数据库连接字符串正确

## 15. 部署与收尾 — Helm Umbrella Chart 收敛

**§4bis / §8 / §14bis 已完成骨架、分布式语义、生产化三阶段，本节做最终清理。**

- [x] 15.1 复核 `Chart.yaml` dependencies 版本锁定（`~x.y.z`），`helm dependency update` 后提交 `Chart.lock`
- [x] 15.2 复核 `values.yaml` 结构：按 `global` / `api` / `engine` / `frontend` / `postgresql` / `redis` / `loki` 分节，所有魔法值下沉到 values
- [x] 15.3 提供 `values-dev.yaml`（资源最小化，用于毕设答辩本地 K3s）与 `values-prod.yaml`（资源对齐 §17.4 压测预期）两份 override
- [x] 15.4 `_helpers.tpl` 抽取重复片段（labels、env、探针、subchart 连接字符串拼接）
- [x] 15.5 `templates/NOTES.txt` 输出 NodePort 访问地址与关键命令（`kubectl logs`、`helm upgrade`）

## 16. 部署与收尾 — 镜像与文档

- [x] 16.1 更新后端 `Dockerfile` 基础镜像 `python:3.11-slim`（实际采用版本），安装 `libpq-dev`/`gcc` 编译 `asyncpg`
- [x] 16.2 验证镜像构建大小合理（445MB < 500MB）
- [x] 16.3 更新 `docs/架构升级方案.md` 与最终 design 保持一致
- [x] 16.4 更新 `README.MD`：部署命令改为 `helm install logsentinel helm-charts/logsentinel -f values-dev.yaml`；保留 `docker-compose` 作为**开发环境**说明（单副本 PG + Redis + engine）

## 17. 整体端到端验证

- [x] 17.1 在 K3s 单节点部署完整 Helm Chart，验证 3 个 Worker + 2 个 API 副本启动
- [x] 17.2 通过 NodePort 访问前端，完整走通：创建规则 → 触发告警 → 收到 WebSocket 推送
- [x] 17.3 杀掉任一 Worker pod，K8s 自动拉起新 pod；期间告警继续产出
- [x] 17.4 构造告警量 >= 100 条，验证 PG 查询 P99 < 200ms、Redis 内存 < 200MB
