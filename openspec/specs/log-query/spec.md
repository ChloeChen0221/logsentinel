# log-query Specification

## Purpose
TBD - created by archiving change horizontal-scale-architecture. Update Purpose after archive.
## Requirements
### Requirement: 日志查询必须异步非阻塞

系统 SHALL 使用异步 HTTP 客户端（`aiohttp`）调用 Loki 查询接口，不得在协程中使用同步阻塞库（如 `requests`）。

#### Scenario: Worker 在同一事件循环内并发评估规则

- **WHEN** Rule Worker 在单轮评估周期内并发触发 10 条规则的 Loki 查询
- **THEN** 所有查询协程共享同一事件循环，单条查询阻塞不得导致其他协程被挂起
- **AND** 所有查询并发发出 HTTP 请求，总耗时接近最慢请求耗时而非顺序耗时之和

#### Scenario: 网络抖动时触发重试退避

- **WHEN** 单次 Loki HTTP 请求超时或返回 5xx 错误
- **THEN** 系统按指数退避策略重试（1s / 2s / 4s），最多重试 3 次
- **AND** 3 次均失败时抛出 `LokiQueryError` 并记录结构化日志

### Requirement: 相同查询必须在 TTL 内复用缓存

系统 SHALL 以 `(query_expression, start, end)` 的 MD5 为 Key，将 Loki 查询响应缓存到 Redis，默认 TTL 为 10 秒。TTL 可通过配置项覆盖。

#### Scenario: 缓存命中时不发起 HTTP 请求

- **GIVEN** 某条查询 `q1` 在 10 秒内已由任一 Worker 执行过并缓存
- **WHEN** 任意 Worker 再次发起完全相同的 `q1`
- **THEN** 查询直接从 Redis 返回缓存结果，不向 Loki 发起 HTTP 请求
- **AND** 缓存命中在可观测日志中以 `cache_hit=true` 标记

#### Scenario: 缓存过期后重新查询并刷新

- **GIVEN** 某条查询 `q1` 缓存已超过 TTL
- **WHEN** Worker 再次发起 `q1`
- **THEN** 系统向 Loki 发起 HTTP 请求，响应返回后回写 Redis，TTL 重置

#### Scenario: 不同时间范围不共享缓存

- **WHEN** 查询表达式相同但 `start` 或 `end` 不同
- **THEN** 生成不同的缓存 Key，互不干扰

### Requirement: 系统必须对 Loki 出站 QPS 实施限流

系统 SHALL 使用令牌桶算法对 Loki 查询 QPS 实施限流，默认上限为 50 QPS，可通过配置覆盖。超过限额的查询协程阻塞等待令牌。

#### Scenario: QPS 超限时请求被排队

- **GIVEN** Loki QPS 上限配置为 50
- **WHEN** 单秒内有 100 次查询请求
- **THEN** 前 50 次立即执行，后续 50 次等待下一秒的令牌
- **AND** 不得因 QPS 限流抛出异常或返回失败

#### Scenario: 限流器跨 Worker 副本独立

- **WHEN** 部署了多个 Rule Worker 副本
- **THEN** 每个副本维护独立的本地限流器；整体出站 QPS 上限为 `单副本上限 × 副本数`

### Requirement: 查询客户端必须上报可观测指标

系统 SHALL 为每次 Loki 查询记录结构化日志，至少包含：`query_hash`、`cache_hit`、`duration_ms`、`status`（`success / timeout / error`）、`rule_id`（若有上下文）。

#### Scenario: 查询成功路径

- **WHEN** 一次查询成功返回
- **THEN** 日志记录 `status=success`、`duration_ms` 为实际 HTTP 耗时（缓存命中时接近 0）
- **AND** 记录 `cache_hit=true|false`

#### Scenario: 查询失败路径

- **WHEN** 查询因重试耗尽而最终失败
- **THEN** 日志记录 `status=error`，`duration_ms` 为累计耗时，并附 `error_type` 字段

