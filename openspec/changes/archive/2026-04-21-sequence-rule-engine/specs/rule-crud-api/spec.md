## ADDED Requirements

### Requirement: Rule CRUD 支持序列规则字段
POST/PUT `/api/rules` SHALL 接受并返回 `rule_type`、`correlation_type`、`steps`（RuleStep 列表）字段，所有新字段 SHALL 为 Optional 以保持向后兼容。GET `/api/rules/{id}` SHALL 在 rule_type=sequence 时返回关联的 steps 数组。

#### Scenario: 创建序列规则时持久化步骤
- **WHEN** POST /api/rules 提交 rule_type=sequence 和非空 steps
- **THEN** 创建 Rule 记录及对应 RuleStep 记录，响应包含完整 steps 数组

#### Scenario: 查询单条序列规则返回步骤
- **WHEN** GET /api/rules/{id}，规则为 sequence 类型
- **THEN** 响应 JSON 包含 steps 数组，元素按 step_order 升序排列

#### Scenario: keyword 规则不受影响
- **WHEN** GET /api/rules/{id}，规则为 keyword 类型
- **THEN** 响应 JSON 中 steps 为空数组，rule_type 为 keyword

### Requirement: SequenceState 查询端点
系统 SHALL 提供 GET `/api/sequence-states?rule_id={id}` 端点，返回指定规则的当前序列状态（current_step、expires_at、step_timestamps），供调试使用。

#### Scenario: 查询存在的序列状态
- **WHEN** GET /api/sequence-states?rule_id=1，且该规则有活跃状态
- **THEN** 返回 SequenceState 对象，包含 current_step 和 expires_at

#### Scenario: 查询不存在的序列状态
- **WHEN** GET /api/sequence-states?rule_id=999
- **THEN** 返回空列表
