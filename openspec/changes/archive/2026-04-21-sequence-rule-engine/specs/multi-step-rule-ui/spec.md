## ADDED Requirements

### Requirement: 多步骤规则表单
前端规则表单 SHALL 在 `rule_type=sequence` 时展示步骤列表区域，支持动态添加/删除步骤行，每行包含：`match_type`（下拉）、`match_pattern`（输入框）、`window_seconds`（数字输入，单位秒）、`threshold`（数字输入）。

#### Scenario: 选择序列类型后显示步骤区域
- **WHEN** 用户在规则类型下拉中选择"序列规则"
- **THEN** 表单展示步骤列表区域，默认显示2个步骤行

#### Scenario: 添加步骤
- **WHEN** 用户点击"添加步骤"按钮
- **THEN** 步骤列表末尾新增一个空白步骤行

#### Scenario: 删除步骤
- **WHEN** 用户点击某步骤行的删除按钮，且当前步骤数 > 2
- **THEN** 该步骤行被移除，步骤序号重新排列

### Requirement: 关联类型选择
规则表单 SHALL 在步骤列表上方提供 `correlation_type` 选择器，选项为"顺序关联（A→B）"和"否定关联（A→¬B）"，并附带简短说明文字。

#### Scenario: 选择关联类型
- **WHEN** 用户选择关联类型
- **THEN** 表单下方显示对应语义说明文字

### Requirement: 规则列表展示序列类型标签
规则列表 SHALL 为 `rule_type=sequence` 的规则展示"序列规则"类型标签，与现有"关键词"/"阈值"标签区分显示。

#### Scenario: 列表展示序列规则标签
- **WHEN** 规则列表加载，规则的 rule_type 为 sequence
- **THEN** 该规则行显示"序列规则"标签
