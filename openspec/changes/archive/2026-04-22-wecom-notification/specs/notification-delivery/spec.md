## ADDED Requirements

### Requirement: 规则 SHALL 可配置多个通知渠道

`rules` 表 SHALL 新增 `notify_config JSONB NOT NULL DEFAULT '[]'` 字段，存储渠道配置数组。每个元素至少包含 `type`（当前支持 `wecom`）、`name`（显示名）、以及渠道类型所需的连接参数。

#### Scenario: 规则配置 2 个企微渠道

- **GIVEN** 规则 `notify_config` 配置了 2 个 `type=wecom` 的渠道（开发群、运维群）
- **WHEN** 告警触发
- **THEN** 系统为该告警创建 2 条 `notifications` 记录，分别发往两个 webhook

#### Scenario: 存量规则 notify_config 为空时 fallback 到 console

- **GIVEN** 规则 `notify_config=[]`
- **WHEN** 告警触发
- **THEN** 系统创建 1 条 `channel=console` 的 `notifications` 记录
- **AND** ConsoleNotifier 输出结构化日志

### Requirement: 通知触发 SHALL 按渠道扇出为独立记录

告警触发时，`enqueue_notification` MUST 接收 `channels: list[dict]` 参数，SHALL 对每个渠道在 `notifications` 表独立插入一条 `status=pending` 记录，各自独立入队，各自独立 CAS 抢占与重试。

#### Scenario: 扇出的单 channel 故障不影响其他 channel

- **GIVEN** 规则配置 2 个 wecom 渠道 A 和 B，告警触发扇出为 2 条 notification
- **WHEN** channel A 发送成功、channel B 网络超时重试 3 次仍失败
- **THEN** notification A 状态 `sent`，notification B 状态 `failed`
- **AND** `alert.last_notified_at` 因 A 成功被更新

### Requirement: `notifications` 表 SHALL 存储渠道配置快照

`notifications` 表 SHALL 新增 `channel_config JSONB NOT NULL DEFAULT '{}'` 字段，入队时从 `rule.notify_config` 对应项拷贝当时配置。消费者从本字段读取连接参数，不反查 `rules`。

#### Scenario: 用户修改规则渠道配置不影响已入队通知

- **GIVEN** 已入队 1 条 pending notification（channel_config 含原 webhook_url）
- **WHEN** 用户在 UI 修改该规则的 webhook_url
- **THEN** 正在消费的通知仍发往**原** webhook_url（快照生效）
- **AND** 规则更新后的下一次触发使用新 webhook_url

### Requirement: 通知失败原因 SHALL 区分是否可重试

`Notifier.send` 返回字典 SHALL 包含 `retriable: bool` 字段。`retriable=False` 时 consumer 直接跳过剩余重试、标记 `failed`。

#### Scenario: 不可重试错误直接标记失败

- **GIVEN** WecomNotifier 返回 `{"success":False, "retriable":False, "error":"errcode=93000"}`
- **WHEN** consumer 处理该失败
- **THEN** 不进入剩余重试循环
- **AND** notifications 状态直接置为 `failed`，`retry_count=0`

#### Scenario: 可重试错误按默认策略重试

- **GIVEN** WecomNotifier 返回 `{"success":False, "retriable":True, "error":"timeout"}`
- **WHEN** consumer 处理该失败
- **THEN** 按 1s/2s/4s 退避重试最多 3 次
- **AND** 全部失败后标记 `failed`，`retry_count=3`

## MODIFIED Requirements

### Requirement: 通知状态必须持久化以支持崩溃恢复

`notifications` 表 SHALL 维护 `status`（枚举：`pending / sent / failed`）、`retry_count`、`channel`、`channel_config`、`content`、`error_message`、`notified_at` 字段。通知入队时以 `status=pending` 创建记录，成功后更新为 `sent`，最终失败更新为 `failed`。每条记录对应**一个渠道**（一个告警触发 N 个渠道即产生 N 条记录）。

#### Scenario: 通知入队立即持久化为 pending

- **WHEN** Evaluator 触发一次通知入队，规则配置 2 个渠道
- **THEN** 系统在 `notifications` 表插入 2 条 `status=pending`、`retry_count=0` 的记录
- **AND** 每条记录的 `channel_config` 分别对应 2 个渠道的快照

#### Scenario: 通知发送成功更新状态

- **WHEN** 通知消费者成功发送一条通知
- **THEN** 对应 `notifications` 行 `status` 原子更新为 `sent`，记录 `notified_at`
- **AND** 更新条件为 `WHERE id=? AND status='pending'`，防止并发重复处理

### Requirement: 失败通知必须可在前端查询

系统 SHALL 提供 API `GET /api/notifications?status=failed` 返回失败通知列表，支持按 `alert_id` 过滤与分页。响应字段 SHALL 包含 `channel_config.name` 以标识失败的具体渠道。

#### Scenario: 查询失败通知列表显示渠道名

- **WHEN** 客户端调用 `GET /api/notifications?status=failed&page=1&page_size=20`
- **THEN** 返回 JSON 响应包含 `items`（含 `id`、`alert_id`、`channel`、`channel_name`（来自 channel_config.name）、`retry_count`、`error_message`、`notified_at`）与 `total`
- **AND** 按 `notified_at DESC` 排序
