## ADDED Requirements

### Requirement: Loghub 数据集时间戳重写
注入工具 SHALL 将 Loghub 数据集中的原始时间戳重写为当前时间附近的值，保留日志间相对时序关系，确保所有时间戳落在 Loki `reject_old_samples_max_age=168h` 窗口内。

#### Scenario: 时间戳重写后被 Loki 接受
- **WHEN** 执行注入器回放 Loghub HDFS_1 数据集
- **THEN** Loki HTTP 响应码为 204，无 `entry too far behind` 错误

#### Scenario: 相对时序保留
- **WHEN** 原始数据集中日志 A 比日志 B 早 30 秒
- **THEN** 注入到 Loki 后，日志 A 的时间戳仍比日志 B 早 30 秒

### Requirement: 可控 QPS 注入
注入工具 SHALL 支持通过参数指定目标 QPS，实际注入速率与目标 QPS 的误差 SHALL 在 ±10% 以内（测量窗口 10 秒）。

#### Scenario: 指定 QPS 注入
- **WHEN** 以 `--qps 1000` 参数运行注入器
- **THEN** 10 秒内平均注入速率在 900-1100 条/秒之间

#### Scenario: 注入完成后记录元数据
- **WHEN** 注入任务完成
- **THEN** 生成 `results/inject_<exp_id>.jsonl`，每行包含以下字段：
  `{exp_id, line_id, inject_ts_ns, push_ack_ts_ns, namespace, pod, container, rule_type, is_anomaly, message}`

### Requirement: 实验级唯一标识
注入工具 SHALL 为每次实验生成唯一 `exp_id`，并在每条注入日志的正文或 structured metadata 中携带 `exp_id` 和 `line_id`，用于后续与告警精确对账。

#### Scenario: exp_id/line_id 写入日志
- **WHEN** 以 `--exp-id exp001` 参数运行注入器
- **THEN** 每条推送到 Loki 的日志正文中包含 `exp_id=exp001 line_id=<序号>`，可通过 LogQL 过滤查询

#### Scenario: push_ack_ts_ns 记录
- **WHEN** Loki push 请求返回 HTTP 204
- **THEN** 记录该批次最后一条日志对应的 `push_ack_ts_ns`（纳秒时间戳）到元数据文件

### Requirement: 延迟分段分析
分析脚本 SHALL 从元数据文件和 LogSentinel API 计算以下三段延迟，并输出 P50/P95/P99：
- `push_ack_ts_ns - inject_ts_ns`：注入到 Loki 确认写入的耗时
- `alert.created_at - push_ack_ts_ns`：Loki 可查到 Engine 评估入库的耗时
- `alert.created_at - inject_ts_ns`：端到端总延迟

#### Scenario: 三段延迟输出
- **WHEN** 运行 `python benchmark/analyze_latency.py --exp-id exp001 --rule-id <id>`
- **THEN** 输出包含三段延迟 P50/P95/P99 的 CSV 表格

### Requirement: 实验元数据完整记录
注入工具 SHALL 为每轮实验记录完整的可复现元数据，包括数据集信息和注入参数，写入 results 目录。

#### Scenario: 元数据包含数据集信息
- **WHEN** 注入任务完成
- **THEN** `results/inject_<exp_id>.jsonl` 的 header 行（或伴随的 `results/inject_<exp_id>_meta.json`）包含：`dataset`（HDFS_1/BGL）、`start_line`、`line_count`、`qps`、`exp_id`、`rule_type`、`eval_interval`

#### Scenario: 关键词注入保证规则触发
- **WHEN** 以 `--inject-keyword ERROR` 参数运行注入器
- **THEN** 每条日志正文前附加指定关键词（如 `ERROR`），保证与目标规则的 match_pattern 匹配，不依赖原始 Loghub 日志内容中偶发的关键词出现

### Requirement: 数据集切片固定
注入工具 SHALL 支持通过 `--start-line` 和 `--line-count` 参数指定数据集切片，对比实验中 LogSentinel 与 Grafana Alerting 必须使用相同的切片（相同 dataset、start_line、line_count、exp_id）。

#### Scenario: 固定切片可复现
- **WHEN** 以相同 `--dataset HDFS_1 --start-line 0 --line-count 10000 --exp-id exp001` 参数两次运行注入器
- **THEN** 注入到 Loki 的日志内容和时序完全一致（时间戳因重写会有微小偏差，相对顺序不变）
注入工具 SHOULD 从 Loghub HDFS_1 的 anomaly 标签文件中读取异常行号，并在元数据中标记 `is_anomaly: true/false`。该字段仅用于辅助分析，不作为主实验的核心指标依赖。

#### Scenario: 异常标签字段存在
- **WHEN** 使用 HDFS_1 数据集运行注入器且提供 anomaly label 文件
- **THEN** 元数据 JSONL 中每行包含 `is_anomaly` 字段（true/false），不要求与主实验结果强绑定
