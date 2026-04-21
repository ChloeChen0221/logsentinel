# Spec: alert-lifecycle

## ADDED Requirements

### Requirement: 窗口阈值判定必须按分组粒度

系统 SHALL 将窗口计数器的 Key 粒度从 `rule_id` 细化到 `(rule_id, fingerprint)`，`fingerprint` 基于规则的 `group_by` 字段计算。每个分组独立维护窗口计数并独立判定阈值。

#### Scenario: 按 group_by 分组独立判定

- **GIVEN** 规则 `R` 定义 `threshold=10`、`group_by=["namespace"]`、`window_seconds=300`
- **WHEN** 窗口内 `namespace=A` 出现 6 次命中，`namespace=B` 出现 5 次命中
- **THEN** 两个分组各自均未达到 10，**不触发**任何告警
- **AND** 修复前（Bug）此场景会因全局计数 11 ≥ 10 而错误触发

#### Scenario: 单一分组达标独立触发

- **GIVEN** 同上规则 `R`
- **WHEN** 窗口内 `namespace=A` 出现 12 次命中，`namespace=B` 出现 2 次命中
- **THEN** 仅为 `namespace=A` 的 fingerprint 触发告警，`namespace=B` 不触发

#### Scenario: 规则未定义 group_by 时视作单一默认分组

- **GIVEN** 规则 `R` 未设置 `group_by`（为空）
- **WHEN** 系统计算 fingerprint
- **THEN** fingerprint 基于 `group_by={}` 计算，所有事件归入一个默认分组
- **AND** 行为等价于"全局计数"，但代码路径与分组场景一致

### Requirement: 窗口计数器必须外置到 Redis

系统 SHALL 使用 Redis ZSET 存储窗口内事件时间戳，Key 格式为 `window:{rule_id}:{fingerprint}`。每个 ZSET member 必须唯一（格式 `{timestamp_ms}:{uuid8}`），score 为时间戳毫秒值。

#### Scenario: 同一毫秒多条事件不被去重

- **WHEN** 两条日志时间戳相同（同一毫秒）
- **THEN** 两条事件生成不同 member（通过附加 uuid8 后缀）
- **AND** `ZCARD` 返回 2，不被合并

#### Scenario: Worker 重启后窗口计数保持

- **GIVEN** 单个 Worker 副本在窗口期间累计了 8 条事件
- **WHEN** 该 Worker 崩溃并由 K8s 拉起新实例
- **THEN** 新实例通过 Redis ZSET 读取已有的 8 条计数
- **AND** 后续 `ZADD` 在原有基础上累加，阈值判定不因重启重置

#### Scenario: 多副本 Worker 共享窗口计数

- **WHEN** 多个 Worker 副本都曾写入过同一规则、同一 fingerprint 的事件
- **THEN** 所有副本对同一 ZSET Key 的 `ZADD` 最终汇总
- **AND** `ZCARD` 反映全部副本累计的事件数

### Requirement: 窗口 Key 必须配置 TTL 与单 Key 上限

每次 `ZADD` 后 SHALL 对该 Key 执行 `EXPIRE 2 × window_seconds`，确保不活跃分组在 2 倍窗口内被 Redis 自动回收。单个 ZSET 的 member 数量超过 100000 时，SHALL 通过 `ZREMRANGEBYRANK key 0 -100001` 截断最老元素。

#### Scenario: 分组停止活跃后 Key 自动过期

- **GIVEN** 规则 `R` 某分组最后一次事件写入于 `T` 时刻，`window_seconds=300`
- **WHEN** 自 `T` 起 600 秒内无新事件
- **THEN** Redis 自动回收该 Key，释放内存

#### Scenario: 单 Key 超过 10 万元素时截断

- **GIVEN** 高流量场景下，`window:{rid}:{fp}` 的 ZCARD 达到 100001
- **WHEN** 系统执行截断保护
- **THEN** 最老的 1 个元素被移除，`ZCARD` 保持为 100000
- **AND** 记录告警日志 `window_counter_truncated`，含 `rule_id`、`fingerprint`、`window_seconds`

### Requirement: 窗口内过期事件必须从 ZSET 清理

系统 SHALL 在每次查询窗口内计数前，通过 `ZREMRANGEBYSCORE key -inf (now_ms - window_ms)` 清理过期事件，保持 ZSET 内仅包含当前窗口数据。

#### Scenario: 读取计数前自动剔除过期事件

- **GIVEN** ZSET 中存在 5 个事件，其中 2 个已超出窗口
- **WHEN** 系统调用 `count(now)` 读取当前计数
- **THEN** 先执行 `ZREMRANGEBYSCORE` 删除 2 个过期事件
- **AND** 再返回 `ZCARD` 结果 3

### Requirement: 告警创建与更新必须实时推送给前端

系统 SHALL 在 Alert 创建或更新时，通过 Redis `PUBLISH alerts:new <json>` 广播事件。API 层 SHALL 提供 WebSocket 端点 `/ws/alerts`，订阅该频道并推送给所有连接的客户端。

#### Scenario: 新告警触发 WebSocket 推送

- **GIVEN** 前端已通过 WebSocket 连接到 `/ws/alerts`
- **WHEN** AlertManager 创建一条新 Alert
- **THEN** 系统在事务提交后执行 `PUBLISH alerts:new`，消息体包含 `id`、`rule_id`、`fingerprint`、`last_seen`
- **AND** 前端收到消息并在 2 秒内完成渲染

#### Scenario: 已存在告警的 last_seen 更新同样推送

- **WHEN** 同一 fingerprint 的 Alert 被更新（`last_seen` 刷新、`hit_count` 增加）
- **THEN** 同样发布 `alerts:new` 事件，前端据此更新列表对应行

#### Scenario: 客户端断线后重连不丢失历史

- **GIVEN** WebSocket 在推送期间短暂断线
- **WHEN** 客户端重连
- **THEN** 前端 SHALL 主动通过 REST API `GET /api/alerts` 拉取一次最新列表，补齐断线期间漏推
- **AND** 系统不保证 WebSocket 自身的消息投递可靠性，由前端结合 REST 拉取保证最终一致

#### Scenario: 多 API 副本下所有订阅者都能收到

- **GIVEN** 部署了 2 个 API 副本，各自有客户端连接
- **WHEN** 任一副本或 Rule Worker 触发 `PUBLISH alerts:new`
- **THEN** 两个 API 副本的 Redis pub/sub 订阅都收到该消息
- **AND** 两个副本各自将消息推送给自己连接的客户端
