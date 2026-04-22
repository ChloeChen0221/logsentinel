## ADDED Requirements

### Requirement: 系统 SHALL 支持企业微信群机器人 Webhook 通知

系统 SHALL 通过企业微信提供的 Webhook 端点（`https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key={key}`）发送 Markdown 格式告警消息，HTTP `POST` + `Content-Type: application/json`。

#### Scenario: 成功发送 Markdown 告警消息

- **GIVEN** 一条 severity=error 的告警命中，规则配置了 1 个 wecom 渠道
- **WHEN** 通知消费者处理该通知
- **THEN** 系统 POST 到配置的 webhook_url
- **AND** 请求体 `msgtype=markdown`，`markdown.content` 含规则名称、时间、命中次数、样本日志
- **AND** 企微返回 `{"errcode":0,"errmsg":"ok"}`
- **AND** 对应 notifications 行状态更新为 `sent`

#### Scenario: Markdown 内容超长自动截断

- **GIVEN** 告警的 sample_log 长度导致整体消息 > 4096 字节
- **WHEN** 消息格式化器构造请求体
- **THEN** sample_log 被截断至合规长度，保留头尾元信息完整
- **AND** 截断处以 `...(truncated)` 提示

### Requirement: 系统 SHALL 支持按 severity 染色的消息模板

系统 SHALL 根据告警 severity 使用企微 Markdown `<font color="...">` 标签渲染不同颜色：`critical`/`error` → `warning`（橙红），`warning` → `comment`（灰），`info` → `info`（绿）。

#### Scenario: error 级告警渲染为橙红色标题

- **GIVEN** 一条 severity=error 的告警
- **WHEN** 格式化器构造 markdown
- **THEN** 首行含 `<font color="warning">[严重]</font>` 样式

### Requirement: 系统 SHALL 支持 @手机号 mention

渠道配置 `mentioned_mobile_list` 为非空数组时，请求体 MUST 包含 `markdown` 消息后追加一条 `text` 消息（或使用 markdown 原生不支持 mentioned_list 的限制下，使用 text 类型单独发送 mention）。

#### Scenario: 配置了 mention 时 at 到人

- **GIVEN** 渠道 `mentioned_mobile_list=["13800000000"]`
- **WHEN** 发送告警
- **THEN** 除 markdown 主消息外，额外发送一条 `text` 消息 `@13800000000`
- **AND** 两条消息均计入 20 条/分钟限额

### Requirement: 系统 SHALL 对每个 webhook 做分布式速率限流

系统 SHALL 使用 Redis ZSET 滑动窗口 `wecom:rl:{md5(url)[:12]}` 为每个 webhook 施加 60 秒 20 条的速率上限。所有副本共享同一 ZSET，确保**多副本总速率** ≤ 20 条/60 秒。超速调用 MUST 在 acquire 阶段 `asyncio.sleep` 等待窗口滑动，不丢请求。

#### Scenario: 单副本超速时排队等待

- **GIVEN** 单副本进程在 60 秒内已通过 Redis 限流发送 20 条
- **WHEN** 第 21 条任务调用 acquire
- **THEN** 调用阻塞直到 ZSET 最老一条 score + 60_000 ≤ now_ms
- **AND** 最终放行并计入下一窗口

#### Scenario: 多副本共享限流配额

- **GIVEN** 2 个 API 副本，Redis 限流 ZSET 当前计数已达 20
- **WHEN** 任一副本尝试发送新请求
- **THEN** 该副本在 acquire 阶段等待，不会突破 20/60 秒总上限

#### Scenario: Redis 不可用时 fail-open

- **GIVEN** Redis 连接异常
- **WHEN** 调用 acquire
- **THEN** 记录 `wecom_ratelimit_fallback` warning 日志
- **AND** 退化到进程内 `AsyncLimiter(20, 60)` 兜底
- **AND** 不阻断告警发送

### Requirement: 系统 SHALL 对每个 webhook 做并发数控制

系统 SHALL 为每个 webhook 在每个进程内维护 `asyncio.Semaphore(2)`，限制同一进程对同一 webhook 的并发 in-flight 请求数不超过 2，以规避企微未文档化的 `errcode=45033 api concurrent out of limit`。

#### Scenario: 并发请求超过上限时排队

- **GIVEN** 同一进程内已有 2 个针对同一 webhook 的请求处于 in-flight 状态
- **WHEN** 第 3 个请求到达
- **THEN** 第 3 个请求在 Semaphore 上阻塞
- **AND** 前两者中任一完成释放许可后继续执行

### Requirement: 系统 SHALL 正确处理企微错误码

系统 MUST 根据企业微信响应中的 `errcode` 字段决定后续动作：

| errcode | 动作 |
|---|---|
| 0 | 标记 sent |
| 45009（速率超限） | backoff 60s 后重试（覆盖默认 4s） |
| 45033（并发超限） | backoff 5s 后重试（retriable=True） |
| 其他 != 0 | 不重试，直接 failed，记录 errcode+errmsg |
| HTTP 5xx / 超时 | 按默认 1s/2s/4s backoff 重试 |
| HTTP 4xx | 不重试，直接 failed |

#### Scenario: 45009 超频错误走长 backoff

- **GIVEN** 企微返回 `{"errcode":45009,"errmsg":"reach max"}`
- **WHEN** 消费者处理该失败
- **THEN** 下一次重试前等待至少 60 秒
- **AND** 整体重试次数仍受 `MAX_RETRIES=3` 约束

#### Scenario: 45033 并发超限错误走 5s backoff

- **GIVEN** 企微返回 `{"errcode":45033,"errmsg":"api concurrent out of limit"}`
- **WHEN** 消费者处理该失败
- **THEN** 下一次重试前等待至少 5 秒
- **AND** retriable=True，进入重试循环

#### Scenario: 鉴权错误不重试

- **GIVEN** 企微返回 `{"errcode":93000,"errmsg":"invalid key"}`
- **WHEN** 消费者处理响应
- **THEN** 状态直接置为 `failed`，`retry_count=0`
- **AND** `error_message` 记录 `wecom errcode=93000 invalid key`

### Requirement: 系统 SHALL 提供 webhook 测试发送接口

系统 SHALL 提供 `POST /api/channels/test`，同步发送一条测试消息并返回发送结果。

**请求示例**：
```json
POST /api/channels/test
{
  "webhook_url": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx",
  "mentioned_mobile_list": []
}
```

**成功响应**：
```json
HTTP 200
{"success": true, "errcode": 0, "errmsg": "ok"}
```

**失败响应**：
```json
HTTP 400
{"success": false, "errcode": 93000, "errmsg": "invalid key"}
```

#### Scenario: 测试发送连通 webhook

- **WHEN** 调用 `POST /api/channels/test` 带有效 webhook_url
- **THEN** 系统向该 URL 发送一条文案 `LogSentinel 连通性测试 <ISO 时间>` 的 text 消息
- **AND** 返回 HTTP 200 + `errcode=0`

#### Scenario: 测试发送不走队列

- **WHEN** 调用测试接口
- **THEN** 不在 `notifications` 表写入记录
- **AND** 请求在 5 秒内返回（同步调用）
