## ADDED Requirements

### Requirement: 序列状态持久化
系统 SHALL 将每条序列规则的执行状态持久化到 `sequence_states` 表，记录 `rule_id`、`current_step`（当前待匹配步骤索引）、`step_timestamps`（JSON，各步骤命中时间戳数组）、`started_at`、`expires_at`。

#### Scenario: 首次评估序列规则时初始化状态
- **WHEN** 序列规则首次被评估且数据库中无对应 SequenceState
- **THEN** 系统创建 current_step=0 的初始状态记录

#### Scenario: 步骤命中时更新状态
- **WHEN** step[N] 命中
- **THEN** 系统将 current_step 更新为 N+1，记录命中时间戳到 step_timestamps[N]，更新 expires_at

### Requirement: 序列状态超时自动重置
系统 SHALL 在每轮评估时检测 `expires_at`，当 `expires_at < now()` 时重置状态为初始值（current_step=0，清空 step_timestamps）。

#### Scenario: 状态超时重置
- **WHEN** 引擎评估时发现 SequenceState.expires_at < 当前时间
- **THEN** 重置 current_step=0，清空 step_timestamps，不触发告警

### Requirement: 状态随规则删除级联清理
系统 SHALL 在规则被删除时级联删除对应的 SequenceState 记录。

#### Scenario: 规则删除时清理状态
- **WHEN** DELETE /api/rules/{id} 被调用
- **THEN** 对应的 SequenceState 记录同时被删除
