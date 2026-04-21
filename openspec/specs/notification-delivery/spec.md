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

`notifications` 表 SHALL 新增 `status` 字段（枚举：`pending / sent / failed`）与 `retry_count` 字段。通知入队时以 `status=pending` 创建记录，成功后更新为 `sent`，最终失败更新为 `failed`。

#### Scenario: 通知入队立即持久化为 pending

- **WHEN** Evaluator 触发一次通知入队
- **THEN** 系统在 `notifications` 表插入 `status=pending`、`retry_count=0` 的记录
- **AND** 记录的 `alert_id` 与对应 Alert 关联

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

系统 SHALL 提供 API `GET /api/notifications?status=failed` 返回失败通知列表，支持按 `alert_id` 过滤与分页。

#### Scenario: 查询失败通知列表

- **WHEN** 客户端调用 `GET /api/notifications?status=failed&page=1&page_size=20`
- **THEN** 返回 JSON 响应包含 `items`（含 `id`、`alert_id`、`channel`、`retry_count`、`error_message`、`notified_at`）与 `total`
- **AND** 按 `notified_at DESC` 排序

