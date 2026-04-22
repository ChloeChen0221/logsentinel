# notification-delivery Specification

## Purpose
TBD - created by archiving change horizontal-scale-architecture. Update Purpose after archive.
## Requirements
### Requirement: 通知交付必须与规则评估解耦

系统 SHALL 使用进程内 `asyncio.Queue` 作为通知任务缓冲，Evaluator 通过 `put` 入队后立即返回，不等待发送结果；通知消费者在独立协程中执行发送。

#### Scenario: 规则评估不被通知发送阻塞

- **GIVEN** 一条规则命中，产生 1 条待发送通知
- **WHEN** 通知发送协程因网络超时耗时 10 秒
- **THEN** Evaluator 入队后立即返回，继续评估下一条规则
- **AND** Evaluator 单轮评估总耗时不受单条通知发送耗时影响

#### Scenario: 队列满载时丢弃新入队项并告警

- **GIVEN** 通知队列配置 `maxsize=10000` 且已满
- **WHEN** Evaluator 尝试入队新通知
- **THEN** 系统捕获 `asyncio.QueueFull` 异常，记录 `notification_queue_full` 结构化日志
- **AND** 新通知不入队；对应 Alert 已落库，可由补偿扫表后续重发

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

### Requirement: 通知失败必须按指数退避重试

通知消费者 SHALL 对单条通知最多重试 3 次，间隔分别为 1 秒、2 秒、4 秒。重试耗尽仍失败的通知 SHALL 标记为 `status=failed` 并记录 `error_message`。

#### Scenario: 临时性失败被重试并最终成功

- **GIVEN** 第一次发送抛出 `ConnectionError`
- **WHEN** 消费者重试第二次
- **THEN** 间隔至少 1 秒后再次发送
- **AND** 若第二次成功则状态更新为 `sent`，`retry_count=1`

#### Scenario: 重试耗尽标记最终失败

- **GIVEN** 某条通知连续 3 次失败
- **WHEN** 消费者耗尽重试机会
- **THEN** 对应行 `status` 更新为 `failed`，`retry_count=3`，`error_message` 记录最后一次异常简述
- **AND** 记录结构化错误日志 `notify_failed_final`

### Requirement: Worker 重启必须扫表补发未完成通知

Rule Worker 启动时 SHALL 扫描 `notifications` 表中 `status=pending` 的记录，重新入队 `asyncio.Queue`。系统对外承诺"至少一次交付"语义。

#### Scenario: Worker 崩溃重启后补发

- **GIVEN** Worker 异常退出时存在 3 条 `status=pending` 的未发送通知
- **WHEN** Worker 重启完成初始化
- **THEN** 系统查询 `notifications WHERE status='pending'` 重新入队所有 3 条
- **AND** 补发过程使用 CAS `WHERE id=? AND status='pending'` 防止并发 Worker 重复消费同一条

#### Scenario: 补发场景下的重复通知风险已披露

- **WHEN** 对外文档或 API 描述此机制
- **THEN** SHALL 明确声明交付语义为"至少一次"，下游系统需自行去重

### Requirement: 失败通知必须可在前端查询

系统 SHALL 提供 API `GET /api/notifications?status=failed` 返回失败通知列表，支持按 `alert_id` 过滤与分页。响应字段 SHALL 包含 `channel_config.name` 以标识失败的具体渠道。

#### Scenario: 查询失败通知列表显示渠道名

- **WHEN** 客户端调用 `GET /api/notifications?status=failed&page=1&page_size=20`
- **THEN** 返回 JSON 响应包含 `items`（含 `id`、`alert_id`、`channel`、`channel_name`（来自 channel_config.name）、`retry_count`、`error_message`、`notified_at`）与 `total`
- **AND** 按 `notified_at DESC` 排序

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

