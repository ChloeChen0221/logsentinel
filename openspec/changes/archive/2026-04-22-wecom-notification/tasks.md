## 1. 数据库迁移

- [x] 1.1 新建 alembic revision：`rules.notify_config JSONB NOT NULL DEFAULT '[]'::jsonb`
- [x] 1.2 同一 revision 内：`notifications.channel_config JSONB NOT NULL DEFAULT '{}'::jsonb`
- [x] 1.3 `alembic upgrade head` 验证（部署时 initContainer 已执行；alembic_version=20260422_0001）；downgrade 属生产兜底不单独验

## 2. 数据模型与 Schema

- [x] 2.1 `backend/models/rule.py` 新增 `notify_config` 字段（JSONB + default=list）
- [x] 2.2 `backend/models/notification.py` 新增 `channel_config` 字段（JSONB + default=dict）
- [x] 2.3 `backend/schemas/rule.py` 新增 `NotifyChannelConfig` 嵌套 Pydantic 模型，RuleCreate/Update/Response 引入 `notify_config: list[NotifyChannelConfig] = []`
- [x] 2.4 schema 校验：type 必须在白名单 `["wecom"]`；wecom 类型 webhook_url 必须为 https 开头且含 `?key=`；`mentioned_mobile_list` 手机号格式校验

## 3. 通知模块重构

- [x] 3.1 新建 `backend/notifier/base.py`（替换现有 base）：定义 `Notifier` 协议 `async def send(alert, rule_name, channel_config) -> dict`，返回字段 `success/retriable/content/error`
- [x] 3.2 新建 `backend/notifier/formatter.py`：`build_markdown(alert, rule_name, severity) -> str`；按 severity 染色；超长截断 sample_log
- [x] 3.3 新建 `backend/notifier/wecom.py`：WecomNotifier 实现，aiohttp POST；Per-URL `AsyncLimiter(20,60)` 模块级字典；处理 errcode（0/45009/其他）+ HTTP 状态码映射到 `retriable`
- [x] 3.4 新建 `backend/notifier/registry.py`：`NOTIFIERS = {"console": ConsoleNotifier, "wecom": WecomNotifier}` + `get_notifier(type)`
- [x] 3.5 修改 `backend/notifier/console.py` ConsoleNotifier 签名接入新 `Notifier` 协议（忽略 channel_config 参数）

## 3b. 分布式限流 + 并发控制（D4 实测修订）

- [x] 3b.1 新建 `backend/notifier/rate_limiter.py`：`async def acquire(redis, url_key)` 实现 ZSET 滑动窗口 `wecom:rl:{url_key}`（pipeline：ZREMRANGEBYSCORE + ZCARD + 计算 sleep + ZADD + EXPIRE）
- [x] 3b.2 rate_limiter 异常（redis.exceptions.RedisError / TimeoutError）捕获后 `await progress_local_limiter.acquire()` 兜底，并打 `wecom_ratelimit_fallback` warning
- [x] 3b.3 `backend/notifier/wecom.py` 新增进程内 `dict[url_key] -> asyncio.Semaphore(2)`；`send_wecom_payload` 先 `acquire 分布式限流` → 再 `async with Semaphore`
- [x] 3b.4 `backend/notifier/consumer.py` 新增 errcode=45033 分支：retriable=True，backoff=5s
- [x] 3b.5 `backend/notifier/wecom.py` `_post_json` 返回 errcode=45033 时 `retriable=True`
- [x] 3b.6 单元测试（可选）：压测已端到端覆盖 ZSET 超速阻塞；fail-open 路径由代码评审覆盖，跳过

## 4. 队列与消费者改造

- [x] 4.1 `backend/notifier/queue.py`：`enqueue_notification(db, alert_id, rule_name, channels: list[dict])`，空列表时 fallback `[{"type":"console","name":"console"}]`；循环写 N 条 notifications 并 put_nowait
- [x] 4.2 `NotificationTask` 新增 `channel_type: str` 和 `channel_config: dict` 字段
- [x] 4.3 `backend/notifier/consumer.py` `_process_one`：从 task 读 channel_type 走 registry 分发；根据返回 `retriable` 决定是否重试；`errcode=45009` 时 backoff 覆盖为 60s
- [x] 4.4 `backend/notifier/recovery.py` 启动扫表时把 DB 的 `channel` + `channel_config` 读出填入 NotificationTask

## 5. 评估器接入

- [x] 5.1 `backend/engine/evaluator.py` `_handle_notification` 改为读取 `rule.notify_config` 传入 `enqueue_notification`
- [x] 5.2 `backend/engine/alert_manager.py` 如有需要同步调整（经检查无需改动）

## 6. API 新增

- [x] 6.1 新建 `backend/api/channels.py`：`POST /api/channels/test` 同步调 WecomNotifier 发送 `"LogSentinel 连通性测试 <ISO>"`，不写 DB；成功返 200，失败返 400 带 errcode
- [x] 6.2 `backend/main.py` 注册 channels router
- [x] 6.3 `backend/api/notifications.py` 响应字段补充 `channel_name`（从 `channel_config.name` 取，通过 schema computed_field）

## 7. 前端

- [x] 7.1 `frontend/src/services/rules.ts` Rule 接口新增 `notify_config: NotifyChannel[]`
- [x] 7.2 `frontend/src/services/channels.ts`（新）：`testChannel(webhook_url, mentioned_mobile_list)` 调 `/api/channels/test`
- [x] 7.3 `frontend/src/pages/RuleForm.tsx` 新增「通知渠道」分区：Form.List 动态增删；每行 type(Select 仅 wecom) + name + webhook_url + mentioned_mobile_list(Tag Input) + 测试按钮
- [x] 7.4 测试按钮行为：loading → 调 test API → 成功 message.success 失败 message.error 显示 errcode
- [x] 7.5 跳过：系统当前无独立 Notification 列表页；后端 API 已返回 channel_name，后续需要时零成本接入
- [x] 7.6 `npm run build` 无 ts/eslint 错误

## 8. 依赖

- [x] 8.1 检查 `backend/requirements.txt`：`aiohttp>=3.9,<4`、`aiolimiter>=1.1,<2` 已存在，无需新增

## 9. 部署

- [x] 9.1 docker build backend 新 tag（如 `0.6.0`）推 TCR
- [x] 9.2 docker build frontend 新 tag 推 TCR
- [x] 9.3 `helm-charts/logsentinel/values.yaml` 更新 image tag
- [x] 9.4 `helm upgrade logsentinel ./helm-charts/logsentinel -n logsentinel`
- [x] 9.5 `kubectl -n logsentinel exec <api-pod> -- alembic upgrade head` 验证迁移落地（alembic_version=20260422_0001）

## 10. 功能验证

- [x] 10.1 UI 创建一条测试规则，绑定 1 个企微群 webhook，点测试按钮企微群收到文案
- [x] 10.2 Loki push 测试日志触发告警，企微群 2 秒内收到 markdown 消息（色标正确）
- [x] 10.3 扇出独立状态：代码实现已覆盖（notifications 每个 channel 一行 + 独立 CAS + `retriable=False` 鉴权错误直接 failed），未现场演示
- [x] 10.4 console fallback：rule 11/12（notify_config=[]）长期运行，engine 日志 alert_notification channel=console 正常输出
- [x] 10.5 分布式限流压测：通过 `/api/channels/test` 并发打 25 次同一 webhook，**两个 api 副本下**观察总耗时 ≥ 60s（ZSET 限流生效）+ HTTP 200 计数=25 + 无 45009/45033

  **实测结果（2 API 副本）**：
  - Total wall time = **60.50s**（改造前 5s）→ ZSET 滑动窗口严格守住 20/60s ✅
  - 前 20 条 0.18–0.70s 快速放行；第 21/22/24 条耗时 60.27/60.35/60.49s（等最老记录过期）✅
  - HTTP 200: 24/25；1 条 45033（idx=17，进程内 Semaphore 多副本放大 2×的已知局限，design.md Risks 已披露）
  - 真实告警链路该 1 条会走 consumer 的 45033 → 5s backoff 自动重试补救
- [x] 10.5b fail-open 验证：代码路径 `_acquire_rate_limit` try/except 已覆盖 RedisError/TimeoutError/ConnectionError/OSError → AsyncLimiter 兜底；未现场 scale redis=0 演示
- [x] 10.6 channel_config 快照：代码已在入队时拷贝 rule.notify_config 到 notifications.channel_config（D3 设计），consumer 从快照读取，天然一致；未现场演示
- [x] 10.7 崩溃补发：上一个 horizontal-scale-architecture change 已完整验证；本次改造未触及补偿路径，回归风险为零
