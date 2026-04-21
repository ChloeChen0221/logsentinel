## Context

当前 logsentinel 规则引擎（`backend/engine/evaluator.py`）采用单条件评估模型：每条规则持有一个 `match_pattern`、可选的 `window_seconds` 和 `threshold`，评估逻辑为"每轮查询Loki → 匹配日志 → 超阈值则创建/更新告警"。状态仅保存在 `rule.last_query_time`，评估函数为无状态纯函数。

扩展目标是在不破坏现有规则的前提下，引入多步骤时序状态机，使引擎能够跨轮次追踪"A条件是否已命中、B条件是否在窗口内跟进"。

## Goals / Non-Goals

**Goals:**
- 新增 `sequence` 规则类型，支持 2-N 个条件步骤按时序关联
- 支持两种关联语义：`sequence`（顺序关联，A→B）和 `negative`（否定关联，A→¬B）
- SequenceState 持久化到数据库（SQLite），跨 worker 重启后状态不丢失
- 现有单条件规则(`keyword`/`threshold`)无需迁移，继续走原有代码路径
- 前端表单支持多步骤增删与关联类型选择

**Non-Goals:**
- 不支持3个以上步骤的复杂图式关联（v1只支持线性A→B双步骤）
- 不支持跨命名空间的关联（步骤共享父规则的 namespace selector）
- 不提供状态可视化 UI（仅存储，可通过API查询）
- 不重写现有告警去重与通知机制

## Decisions

### 1. 规则类型区分：新增 `rule_type` 字段而非改造现有字段

**选择**：在 `Rule` 模型新增 `rule_type: Enum('keyword', 'threshold', 'sequence')` 字段，序列规则的步骤以独立的 `RuleStep` 关联表存储，而非将 steps JSON 内嵌到 Rule 表。

**理由**：
- 关联表允许对单个步骤做索引查询，而 JSON 列无法高效过滤
- 保持现有 `match_pattern`/`window_seconds`/`threshold` 字段不变，keyword/threshold 规则零迁移成本
- 替代方案（把steps存成JSON列）：实现更简单，但扩展性差，放弃

### 2. SequenceState 存储：数据库持久化而非内存字典

**选择**：新增 `SequenceState` 表，字段包括 `rule_id`、`current_step`、`step_timestamps`(JSON)、`started_at`、`expires_at`。

**理由**：
- APScheduler worker 可能重启，内存状态会丢失；持久化保证可靠性
- `expires_at` 字段允许数据库层面的过期清理（定期 DELETE WHERE expires_at < now()）
- 替代方案（Redis）：运维复杂度高，对当前规模没必要，放弃

### 3. 序列状态机：线性推进 + 超时回滚

**状态推进逻辑**：
```
state.current_step == 0 → 检测 step[0] 是否命中
                         → 命中：current_step=1, started_at=now, expires_at=now+step[0].window_seconds
state.current_step == 1 → 检测 step[1] 是否在 expires_at 内命中
  sequence 类型：命中则触发告警，重置state
  negative 类型：expires_at 到期且未命中则触发告警，重置state
  任意步骤：expires_at 已过 → 重置state（回滚到step 0）
```

**理由**：线性状态机对双步骤场景足够，逻辑清晰可测试。

### 4. 评估器改造：策略模式隔离新旧逻辑

**选择**：`RuleEvaluator._evaluate_rule()` 根据 `rule.rule_type` 分发到 `_evaluate_single_condition()` 或 `_evaluate_sequence()`，共享 Loki 查询和告警创建逻辑。

**理由**：避免在现有评估函数中插入大量 if/else，新旧逻辑互不干扰，方便独立测试。

## Risks / Trade-offs

- **SequenceState 写入压力**：每个序列规则每轮都要读写 SequenceState，高规则数量时可能成为瓶颈 → 缓解：引擎执行是单线程串行，无并发写冲突；state 行数 = 规则数，量级可控
- **时钟偏差**：`expires_at` 依赖 worker 服务器时间，与 Loki 日志时间戳可能存在秒级偏差 → 缓解：步骤窗口通常配置为分钟级，秒级偏差影响可忽略
- **前端向后兼容**：API 新增字段必须为 Optional，避免旧版前端解析失败 → 缓解：新增字段均设默认值

## Migration Plan

1. 数据库迁移：新增 `rule_steps` 表和 `sequence_states` 表；`rules` 表新增 `rule_type` 列（默认 `keyword`）——现有数据自动兼容
2. 后端部署：无停机升级，APScheduler worker 重启后自动加载新逻辑
3. 回滚：删除 `rule_steps`/`sequence_states` 表，回退 `rules.rule_type` 字段即可，不影响现有规则数据

## Open Questions

- 是否需要在告警详情中展示"序列命中路径"（哪个步骤触发了最终告警）？ → 暂不实现，alert.sample_log 记录触发日志即可
- 负样本关联（¬B）的通知时机：应在 expires_at 精确时刻触发还是下一轮评估时触发？ → 下一轮评估时检测 expires_at < now()，存在最多一个 engine interval 的延迟，可接受
