## ADDED Requirements

### Requirement: C1 关键词规则场景
系统 SHALL 验证 keyword 规则（无时间窗口）在单条日志匹配时即可触发告警，并在同一 rule + group_by 下重复命中时更新 hit_count 而不产生大量重复告警。

#### Scenario: 单条日志触发告警
- **WHEN** namespace=demo 下任意 Pod 产生 1 条包含 "ERROR" 的日志
- **THEN** Engine 在下一个评估周期（≤30s）内创建告警，alert.status=active

#### Scenario: 重复命中更新 hit_count
- **WHEN** 同一 rule + namespace + pod 组合下持续产生 ERROR 日志
- **THEN** alert.hit_count 持续递增，不产生新的重复 alert 记录（fingerprint 唯一）

#### Scenario: 冷却期 hit_count 持续递增但不通知
- **WHEN** 告警已触发，cooldown_seconds=60，60 秒内同规则再次命中
- **THEN** alert.hit_count 继续递增（create_or_update_alert 仍执行），但 notifications 表通知数不增加，Engine 日志出现 `cooldown active`

#### Scenario: 冷却结束后复用同一 fingerprint
- **WHEN** cooldown 60 秒结束后，同规则再次命中
- **THEN** 触发通知，复用已有 alert（相同 fingerprint），不创建新 alert 记录

### Requirement: C2 阈值规则场景
系统 SHALL 验证 threshold 规则在时间窗口内计数达标时触发告警，按 pod 分组独立计数，窗口外计数回落后不再触发。

#### Scenario: 窗口内达阈值触发
- **WHEN** 同一 Pod 在 60s 内产生第 10 条包含 "OOMKilled" 的日志（threshold=10，window=60s）
- **THEN** Engine 在当前评估周期内创建告警

#### Scenario: 前 9 条不触发
- **WHEN** 同一 Pod 在 60s 内产生 9 条 "OOMKilled" 日志
- **THEN** 无告警产生

#### Scenario: 多 Pod 独立分组
- **WHEN** 同一 namespace 下 3 个不同 Pod 各自产生 ≥10 条 "OOMKilled" 日志
- **THEN** 创建 3 条独立告警，fingerprint 各不相同，group_by=pod 生效

#### Scenario: 窗口外计数回落
- **WHEN** Pod 在 60s 窗口内只有 9 条日志，60s 后再产生 1 条
- **THEN** 窗口滑动后旧计数失效，新窗口重新从 1 开始计数，不触发告警

### Requirement: C3 正向序列规则场景
系统 SHALL 验证 sequence 规则在 window 内所有步骤顺序命中后触发告警，步骤不完整或超时则不触发。

#### Scenario: 三步序列完整触发
- **WHEN** 在 300 秒内按顺序注入步骤1（服务A crash）→ 步骤2（服务B timeout）→ 步骤3（服务C 503）日志
- **THEN** sequence 规则触发告警，alert.rule_type="sequence"

#### Scenario: 步骤不完整不触发
- **WHEN** 仅注入步骤1和步骤2，步骤3 缺失
- **THEN** 300 秒后序列状态超时重置，无告警产生

#### Scenario: 步骤超时重置
- **WHEN** 步骤1命中后，超过 window_seconds=300 秒未出现步骤2
- **THEN** sequence_state 重置为初始状态，步骤1需重新匹配

### Requirement: C4 否定关联规则场景
系统 SHALL 验证 negative correlation 规则：步骤1发生后在 window 内若步骤2始终未出现，则触发告警；若步骤2及时出现则不触发。

#### Scenario: 静默超时触发告警
- **WHEN** 注入 Pod 重启日志（步骤1），120s 内无 "startup completed" 日志（步骤2）
- **THEN** 120s 后触发告警，alert.correlation_type="negative"

#### Scenario: 正常完成不触发告警
- **WHEN** 注入 Pod 重启日志（步骤1），60s 内注入 "startup completed" 日志（步骤2）
- **THEN** 负关联条件不满足，无告警产生

### Requirement: 场景可一键复现
每个场景 SHALL 提供独立脚本，可在清空前次数据后重新执行，输出一致的告警结果。

#### Scenario: 清理后重跑
- **WHEN** 执行对应场景的 reset 脚本后再执行 run 脚本
- **THEN** 告警表中出现与上次相同数量和类型的告警（fingerprint 可不同）
