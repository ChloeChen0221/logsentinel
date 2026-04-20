## MODIFIED Requirements

### Requirement: Rule 模型扩展
Rule 模型 SHALL 新增以下字段：`rule_type: Enum('keyword', 'threshold', 'sequence')`（默认 `keyword`）、`correlation_type: Optional[Enum('sequence', 'negative')]`（仅 rule_type=sequence 时有效）。现有字段 `match_pattern`/`window_seconds`/`threshold` 保持不变，keyword/threshold 规则继续使用这些字段。

#### Scenario: 现有规则 rule_type 默认值
- **WHEN** 数据库迁移运行后
- **THEN** 所有现有规则的 rule_type 字段值为 'keyword' 或 'threshold'（基于 window_seconds > 0 判断）

#### Scenario: 序列规则关联 RuleStep
- **WHEN** 创建 rule_type=sequence 的规则
- **THEN** Rule 记录关联至少2条 RuleStep 记录，每条包含 step_order、match_type、match_pattern、window_seconds、threshold

## ADDED Requirements

### Requirement: RuleStep 模型
系统 SHALL 新增 `RuleStep` 模型，字段包括：`id`、`rule_id`（外键，级联删除）、`step_order`（步骤序号，从0开始）、`match_type`（contains/regex）、`match_pattern`、`window_seconds`、`threshold`（默认1）。

#### Scenario: 步骤随规则删除级联清理
- **WHEN** Rule 被删除
- **THEN** 关联的所有 RuleStep 记录同时被删除
