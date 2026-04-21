## ADDED Requirements

### Requirement: 评估器支持规则类型分发
`RuleEvaluator.evaluate_rule()` SHALL 根据 `rule.rule_type` 分发到不同的评估路径：`keyword`/`threshold` 规则走原有 `_evaluate_single_condition()` 路径；`sequence` 规则走新增的 `_evaluate_sequence()` 路径。现有单条件评估逻辑 SHALL 保持不变。

#### Scenario: keyword 规则走原有路径
- **WHEN** evaluate_rule() 被调用，rule.rule_type 为 keyword
- **THEN** 调用 _evaluate_single_condition()，行为与现有逻辑一致

#### Scenario: sequence 规则走序列路径
- **WHEN** evaluate_rule() 被调用，rule.rule_type 为 sequence
- **THEN** 调用 _evaluate_sequence()，读取并更新 SequenceState

### Requirement: 序列评估函数
`_evaluate_sequence()` SHALL 执行以下逻辑：(1) 加载或创建 SequenceState；(2) 检查 expires_at 是否超时，超时则重置；(3) 根据 current_step 查询 Loki 并匹配对应 RuleStep；(4) 命中则推进 current_step；(5) 根据 correlation_type 判断是否触发告警；(6) 持久化更新后的 SequenceState。

#### Scenario: 序列步骤推进
- **WHEN** step[current_step] 的 Loki 查询返回匹配日志
- **THEN** current_step 递增，expires_at 更新为 now() + step.window_seconds

#### Scenario: 序列完成触发告警（sequence类型）
- **WHEN** current_step 推进到最后一步且最后一步命中
- **THEN** 触发告警，调用 AlertManager.create_or_update_alert()，重置 SequenceState

#### Scenario: 否定关联超时触发告警
- **WHEN** _evaluate_sequence() 检测到 expires_at < now() 且 current_step == 1（已过第一步，等待第二步）且 correlation_type == negative
- **THEN** 触发告警，重置 SequenceState
