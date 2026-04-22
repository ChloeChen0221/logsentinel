## Why

当前告警通知只支持 `console`（结构化日志）。用户在企业微信群里无法实时收到告警，导致告警平台的最后一公里闭环缺失，答辩演示和生产使用价值都严重打折。

## What Changes

- 新增企业微信群机器人渠道（Webhook），支持 Markdown 消息、按 severity 染色、可选 @手机号
- 规则表新增 `notify_config JSONB` 字段，存放渠道列表（当前仅支持 `type=wecom`），每条规则可配置多个群
- `notifications` 表扩展 `channel_config JSONB` 字段，保存触发时的渠道配置快照，用于审计和失败重发
- 告警触发时按渠道列表**扇出**为 N 条独立 notification 记录，独立状态机 + 独立 CAS + 独立重试
- 存量规则 `notify_config=[]` 时 fallback 到 `console`，保持向后兼容
- 前端规则表单新增「通知渠道」配置区域（动态列表 + 测试发送按钮）
- 新增 `POST /api/channels/test` 用于 webhook 连通性验证
- 单副本 `AsyncLimiter(20, 60)` 每 webhook 限速；命中企微 `errcode=45009` 走 60s backoff 而非 4s
- **多副本分布式限流**：基于 Redis ZSET 滑动窗口（`wecom:rl:{md5(url)}`），所有 API/engine 副本共享同一计数器，确保多副本场景总速率仍 ≤ 20/min
- **并发控制**：每 webhook 进程内 `asyncio.Semaphore(2)` 上限，避免企微 `errcode=45033 api concurrent out of limit`
- **Redis 降级**：Redis 不可用时 fail-open，退化到进程内 `AsyncLimiter(20,60)` 兄弟兜底，不阻断告警送达

## Capabilities

### New Capabilities
- `wecom-channel`: 企业微信群机器人 Webhook 通知渠道，含消息格式化、限流、错误码处理、测试接口

### Modified Capabilities
- `notification-delivery`: 由单一 console 渠道扩展为多渠道扇出模型；入队语义从"一 alert 一 notification"变为"一 alert N notification"（N=规则配置的渠道数，空配置时为 1 条 console）

## Impact

- **代码**
  - `backend/models/rule.py` 新增 `notify_config` 字段
  - `backend/models/notification.py` 新增 `channel_config` 字段
  - `backend/notifier/queue.py` `enqueue_notification` 改为接收渠道列表并扇出
  - `backend/notifier/consumer.py` 从 `channel_config` 读取渠道实例并分发
  - `backend/notifier/wecom.py`（新）+ `backend/notifier/formatter.py`（新）+ `backend/notifier/registry.py`（新）
  - `backend/api/channels.py`（新）提供测试发送接口
  - `backend/api/rules.py` + `backend/schemas/rule.py` 接收 `notify_config`
  - `frontend/src/pages/RuleForm.tsx` 新增通知渠道配置 UI
- **数据库**
  - Alembic migration：`rules.notify_config JSONB DEFAULT '[]'`；`notifications.channel_config JSONB DEFAULT '{}'`
- **依赖**：复用已有 `aiohttp` / `aiolimiter`，无新增
- **风险**
  - 企微 webhook URL 明文存 DB（方案确认，不加密）
  - Redis 分布式限流增加对 Redis 可用性的依赖；通过 fail-open 降级策略保障告警链路不因 Redis 故障断裂
- **回滚**：保留 console 兜底逻辑；migration 为新增字段，回滚只需 downgrade drop column
