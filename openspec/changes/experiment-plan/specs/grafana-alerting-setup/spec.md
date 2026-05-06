## ADDED Requirements

### Requirement: Grafana Alerting 独立部署
系统 SHALL 在独立 namespace `monitoring` 部署 Grafana，连接 logsentinel namespace 的同一 Loki 实例，用于对比实验。

#### Scenario: Grafana 连接 Loki
- **WHEN** Grafana 部署完成，配置 Loki datasource 指向 `http://logsentinel-loki.logsentinel:3100`
- **THEN** Grafana datasource 测试连接返回成功

### Requirement: 等价阈值规则配置
Grafana Alerting SHALL 配置与 LogSentinel C2 阈值规则语义等价的告警规则，用于性能对比实验。

规则语义：5 分钟内同一 namespace/pod 下 ERROR 日志数量 ≥ 10。
  - LogQL 使用 `sum by (namespace, pod) (count_over_time({namespace=~".+"} |= "ERROR" [5m]))` 或等价聚合表达式（需明确按 namespace/pod 分组）
  - 分组维度与 LogSentinel group_by=[namespace,pod] 保持一致
- evaluation interval 设置为 30s，与 LogSentinel 对齐

对比实验只要求实现与 C2 阈值规则等价的配置，不要求 Grafana 覆盖 LogSentinel 的序列关联和否定关联规则类型。

#### Scenario: 等价规则触发
- **WHEN** 相同日志注入条件（相同 exp_id、同一 Loki）下两系统同时运行
- **THEN** Grafana Alerting 在 ±30s 范围内与 LogSentinel 触发告警时间可对比

#### Scenario: Grafana firing 时间可采集
- **WHEN** Grafana alert 状态变为 firing
- **THEN** 通过 Grafana Alert History API（`/api/v1/provisioning/alert-rules` 或 `/api/alertmanager/grafana/api/v2/alerts`）或截图方式记录 firing 时间；若使用截图，需在论文中注明测量方式

### Requirement: 对比实验公平性约束
对比实验 SHALL 保证两系统使用相同 Loki 实例、相同注入数据（相同 exp_id）、相同评估间隔（30s），结果差异仅来自系统本身实现差异。

#### Scenario: 评估间隔一致
- **WHEN** 两系统同时运行对比实验
- **THEN** LogSentinel ENGINE_INTERVAL_SECONDS=30，Grafana evaluation interval=30s

### Requirement: 序列规则表达力定性记录
实验 SHALL 记录 Grafana Alerting 对三步序列规则（C3 场景）的表达局限，作为定性对比证据，不做量化测量。

#### Scenario: 序列表达力定性对比
- **WHEN** 尝试在 Grafana Alerting 中用单条规则表达 C3 三步序列场景
- **THEN** 记录是否支持、需要几条规则或额外组件（如 recording rules、外部状态机）、配置复杂度，写入论文功能对比表
