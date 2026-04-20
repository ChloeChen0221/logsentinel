## ADDED Requirements

### Requirement: 序列规则定义
系统 SHALL 支持创建 `rule_type=sequence` 的规则，规则包含 2 个有序条件步骤（step[0] 和 step[1]），每个步骤 SHALL 包含：`match_type`（contains/regex）、`match_pattern`（字符串）、`window_seconds`（步骤超时窗口）、`threshold`（命中次数，默认1）。

#### Scenario: 创建序列规则成功
- **WHEN** 用户提交包含两个步骤和关联类型的规则
- **THEN** 系统创建 Rule 记录（rule_type=sequence）并关联两条 RuleStep 记录，返回完整规则对象

#### Scenario: 序列规则缺少步骤时拒绝
- **WHEN** 用户提交 rule_type=sequence 但 steps 为空或只有1个步骤
- **THEN** 系统返回 422 错误，提示"序列规则至少需要2个步骤"

### Requirement: 顺序关联语义
系统 SHALL 支持 `correlation_type=sequence`，语义为：step[0] 命中后，在 step[0].window_seconds 内 step[1] 也命中，则触发告警。

#### Scenario: A命中后B在窗口内命中触发告警
- **WHEN** step[0] 在轮次 T 命中，step[1] 在 T + step[0].window_seconds 内命中
- **THEN** 系统创建告警并重置序列状态

#### Scenario: A命中后B超时未命中不触发
- **WHEN** step[0] 命中但 step[1] 在 window_seconds 内未命中
- **THEN** 序列状态超时重置，不创建告警

### Requirement: 否定关联语义
系统 SHALL 支持 `correlation_type=negative`，语义为：step[0] 命中后，在 step[0].window_seconds 内 step[1] 未命中，则触发告警。

#### Scenario: A命中后B超时未命中触发告警
- **WHEN** step[0] 命中，且超过 window_seconds 后 step[1] 仍未命中
- **THEN** 系统创建告警并重置序列状态

#### Scenario: A命中后B在窗口内命中则不告警
- **WHEN** step[0] 命中，step[1] 在 window_seconds 内命中
- **THEN** 序列状态重置，不创建告警
