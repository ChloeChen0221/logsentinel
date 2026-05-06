## ADDED Requirements

### Requirement: 延迟口径定义
实验 SHALL 明确区分两种延迟口径，论文中须注明主性能实验采用"引擎评估延迟"口径。

**功能链路 E2E 延迟**（用于功能测试小规模验证）：
`Pod 日志输出 → Promtail 采集 → Loki 可查 → Alert 入库`

**引擎评估延迟**（用于主性能压测，QPS 可控、可重复）：
`log_injector push ack (push_ack_ts_ns) → Engine 评估 → Alert 入库 (alert.created_at)`

#### Scenario: 延迟口径在论文中说明
- **WHEN** 性能实验数据整理完毕
- **THEN** 论文中注明主性能实验不含 Promtail 采集抖动，使用注入器直推 Loki 的口径

### Requirement: 实验数据源说明
所有性能实验和对比实验 SHALL 明确数据来源，不使用纯随机 synthetic 日志。

| 实验类型 | 数据来源 | 数据集 |
|---------|---------|-------|
| 功能测试 C1-C4 | K8s demo Pod 真实 stdout/stderr，经 Promtail 采集 | - |
| 性能实验 3.1-3.4 | Loghub 回放（引擎评估延迟口径） | HDFS_1 主实验，BGL 补充 |
| Grafana 对比实验 | 同一批 Loghub 回放，同一 Loki，相同 exp_id | HDFS_1 固定切片 |

注入器在原始 Loghub 日志前附加目标关键词（如 `ERROR` / `OOMKilled`），保证规则稳定触发。每轮实验记录：dataset 名称、start_line、line_count、QPS、exp_id、规则类型、评估间隔。

#### Scenario: 实验元数据可追溯
- **WHEN** 任意一轮性能实验完成
- **THEN** results 目录下存在对应的元数据文件，包含 dataset/start_line/line_count/qps/exp_id/rule_type/eval_interval 字段

### Requirement: 端到端延迟实验（3.1）
实验 SHALL 测量三种规则类型（keyword/threshold/sequence）在不同 QPS（100/500/1000）下的引擎评估延迟，评估间隔固定 30s，每组配置运行 3 次取中位数。输入日志来自 Loghub HDFS_1 回放，注入器附加匹配关键词保证规则稳定触发。可选追加延迟敏感性实验（interval=10s/30s/60s，固定 QPS=500）。

#### Scenario: 延迟数据可采集
- **WHEN** 以指定 QPS 运行注入器并等待告警产生
- **THEN** 可从 inject 元数据（push_ack_ts_ns）和 `/api/alerts`（created_at）计算出三段延迟

#### Scenario: 结果输出
- **WHEN** 运行 `benchmark/analyze_latency.py`
- **THEN** 输出 P50/P95/P99 延迟 CSV，按规则类型分组

### Requirement: 水平扩展性实验（3.2）
实验 SHALL 测量 Engine replicas（1/2/3）时的评估吞吐量变化，固定 100 条规则、QPS=1000、评估间隔 30s，输入日志来自 Loghub BGL 回放（高频场景）。可选追加 replicas=5、规则数=500、QPS=3000/5000 的压力上限实验（标注 optional）。

#### Scenario: 扩展操作可执行
- **WHEN** 执行 `kubectl scale deployment logsentinel-engine --replicas=N`
- **THEN** N 个 Engine Pod 均处于 Running 状态，分片日志显示规则按 rule_id % N 均匀分配

#### Scenario: 吞吐量数据采集
- **WHEN** 各副本数配置稳定运行 5 分钟
- **THEN** 从 Engine 日志的 `elapsed_seconds` 字段可统计单轮评估耗时和每 Worker 分配规则数

### Requirement: 资源消耗实验（3.3）
实验 SHALL 在规则数（50/100/200）× QPS（100/1000）矩阵下，测量 Engine Pod CPU/内存和 Redis 内存占用，稳态持续 10 分钟，每 30 秒采样一次。输入日志来自 Loghub HDFS_1 回放，固定相同 dataset slice，不同组次只变动规则数和 QPS。

#### Scenario: 资源指标采集
- **WHEN** 实验进入稳态（启动后 2 分钟）
- **THEN** `kubectl top pods -n logsentinel` 返回非零 CPU/内存值

#### Scenario: Redis 内存趋势
- **WHEN** 规则数从 50 增加到 200
- **THEN** Redis INFO memory 中 `used_memory` 随规则数增加呈正相关趋势

### Requirement: 冷却与去重消融实验（3.4）
实验 SHALL 在相同注入条件下，对比三组 cooldown 配置（cooldown=0 / cooldown=60 / cooldown=300）的告警通知数量，统计实际压降比例，不预设数值结论。

实验配置：单条 ERROR 规则，每秒注入 1 条，持续 10 分钟。统计每组的：原始匹配日志数、告警实例数、通知数，并计算 `1 - actual_notifications / raw_matches`。

注意：不单独设置"仅去重"组，因系统中去重与冷却耦合，无法独立关闭去重。

#### Scenario: cooldown=0 基线
- **WHEN** cooldown=0 且持续注入 10 分钟
- **THEN** notifications 表记录通知数，作为基线

#### Scenario: cooldown 压降效果
- **WHEN** cooldown=60 或 cooldown=300 且相同注入条件
- **THEN** 通知数相比基线有明显压降，输出实际压降比例

#### Scenario: 首次告警不延迟
- **WHEN** cooldown=60s，首条触发日志注入后
- **THEN** 第一条通知在 1 个评估周期（≤30s）内产生

### Requirement: LogSentinel 与 Grafana Alerting 等价阈值规则延迟对比
实验 SHALL 在同一 Loki 数据源、同一注入器、同一 30s 评估间隔下，对比 LogSentinel 与 Grafana Alerting 对等价阈值规则的告警延迟。

规则语义：5 分钟内同一 namespace/pod 下 ERROR 日志数量 ≥ 10。
- LogSentinel：threshold 规则，`group_by=[namespace,pod]`，window=300s，threshold=10
- Grafana Alerting：LogQL `sum by (namespace, pod) (count_over_time(...))`，evaluation interval=30s

两系统使用相同 Loghub HDFS_1 数据切片（相同 dataset/start_line/line_count/exp_id），同一 Loki 实例，同一注入节奏。

延迟定义：
- LogSentinel：`push_ack_ts_ns → alert.created_at`
- Grafana Alerting：`push_ack_ts_ns → alert state=firing 时间`（通过 Grafana Alert History API 或截图记录）

实验口径：不要求 LogSentinel 必须快于 Grafana Alerting；若两者延迟处于同一量级，即说明 LogSentinel 在基础阈值场景下具备可接受性能，同时提供更丰富的规则表达能力。序列关联和否定关联不纳入性能对比。

#### Scenario: 两系统使用相同数据
- **WHEN** 对比实验开始
- **THEN** 两个系统连接同一 Loki 实例，使用同一批次注入数据（相同 exp_id）

#### Scenario: 延迟对比输出
- **WHEN** 两系统均产生告警后
- **THEN** 输出包含两系统 P50/P95/P99 延迟对比的表格，每组重复 3 次

### Requirement: 对比实验功能覆盖与配置复杂度对比
实验 SHALL 整理 LogSentinel、Grafana Alerting、ElastAlert 三个系统的功能覆盖和配置复杂度对比表，ElastAlert 只做定性分析，不做性能实测。

对比维度：支持规则类型、是否原生支持序列关联、是否原生支持否定关联、配置字段数、是否需要手写查询语言、依赖存储后端、部署复杂度。

ElastAlert 不部署实测的原因：依赖 Elasticsearch，引入额外日志写入链路和索引刷新机制，难以隔离告警系统本身的性能差异。

#### Scenario: 功能覆盖表整理
- **WHEN** 对比实验完成
- **THEN** 论文中包含三系统功能对比表，LogSentinel 的序列/否定关联能力在表中有明确标注

#### Scenario: 配置复杂度记录
- **WHEN** 完成 Grafana 等价规则配置
- **THEN** 记录 LogSentinel 规则 JSON 字段数 vs Grafana AlertRule + LogQL 配置行数，作为配置复杂度量化依据
