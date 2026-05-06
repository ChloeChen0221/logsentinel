## 1. 基础设施准备

- [x] 1.1 编写 Promtail DaemonSet Helm values / YAML（含 namespace/pod/container/app label），部署到 logsentinel namespace
- [x] 1.2 验证 Loki labels 接口返回 namespace/pod/container，Engine 日志出现 total_logs > 0
- [x] 1.3 下载 Loghub HDFS_1 数据集（~1.5GB）和 BGL 数据集（~700MB）到 benchmark/data/
- [x] 1.4 编写 `benchmark/preprocess_loghub.py`：解析 HDFS_1 日志行 + 时间戳重写 + 生成 Loki push payload
- [x] 1.5 验证预处理后的 payload 成功推入 Loki（HTTP 204，无 entry too far behind 错误）

## 2. 日志注入工具

- [x] 2.1 编写 `benchmark/log_injector.py`：支持 --qps / --dataset / --start-line / --line-count / --namespace / --pod / --exp-id / --inject-keyword 参数
- [x] 2.2 实现时间戳重写逻辑，保证相对时序一致，绝对时间在当前 -6h 到 now 之间
- [x] 2.3 实现 exp_id/line_id 写入日志正文，格式：`exp_id=<id> line_id=<n> <原始日志>`；支持 --inject-keyword 在正文前附加关键词保证规则触发
- [x] 2.4 实现 push_ack_ts_ns 记录：Loki 返回 HTTP 204 后记录时间戳到元数据
- [x] 2.5 实现元数据写出到 `results/inject_<exp_id>.jsonl`，字段：exp_id / line_id / inject_ts_ns / push_ack_ts_ns / namespace / pod / container / rule_type / is_anomaly / message
- [x] 2.6 实现实验级元数据写出到 `results/inject_<exp_id>_meta.json`，字段：dataset / start_line / line_count / qps / exp_id / rule_type / eval_interval / inject_keyword
- [x] 2.7 选择 HDFS_1 和 BGL 的固定数据切片（各选 10000 行作为主实验 slice），记录 dataset/start_line/line_count 到实验说明文档
- [x] 2.8 编写 `benchmark/analyze_latency.py`：读取 inject 元数据 + 查 API alerts，输出三段延迟（注入→ack、ack→alert、端到端）P50/P95/P99

## 3. 功能测试场景

- [x] 3.1 通过 API 创建 C1 规则（keyword，pattern="ERROR"，window=0，threshold=1，group_by=pod）
- [x] 3.2 部署 Demo Pod（产生 ERROR 日志），验证 C1 单条触发、hit_count 递增、cooldown 生效
- [x] 3.3 通过 API 创建 C2 规则（threshold，pattern="OOMKilled"，window=60s，threshold=10，group_by=pod）
- [x] 3.4 编写 `benchmark/scenarios/c2_inject.py`：注入 9 条验证不触发，再注入 1 条验证触发；验证多 Pod 独立分组
- [x] 3.5 通过 API 创建 C3 规则（sequence，3 steps，window=300s，correlation_type=sequence）
- [x] 3.6 编写 `benchmark/scenarios/c3_inject.py`：验证完整三步触发、步骤不完整不触发、超时重置
- [x] 3.7 通过 API 创建 C4 规则（sequence，window=120s，correlation_type=negative）
- [x] 3.8 编写 `benchmark/scenarios/c4_inject.py`：验证静默超时触发、正常完成不触发
- [x] 3.9 为四个场景各编写 reset 脚本（清理告警/序列状态/Demo Pod）

## 4. Grafana 对比系统部署

- [x] 4.1 部署 Grafana（monitoring namespace），配置 Loki datasource 指向 logsentinel-loki.logsentinel:3100
- [x] 4.2 在 Grafana Alerting 中配置等价阈值规则：`count_over_time({namespace=~".+"} |= "ERROR" [5m]) >= 10`，by namespace/pod，evaluation interval=30s
- [x] 4.3 验证 Grafana Alerting 在相同注入数据下能触发告警
- [x] 4.4 确认 Grafana firing 时间采集方式（Alert History API 路径或截图），记录到实验说明文档

## 5. 性能实验执行

- [x] 5.1 实验 3.1（延迟）：使用 HDFS_1 固定切片，批量创建 keyword/threshold/sequence 规则（附加对应关键词），QPS=100/500/1000，固定 interval=30s，每组 3 次，输出三段延迟 CSV
- [ ] 5.2 可选：延迟敏感性实验，固定 QPS=500、HDFS_1 切片，interval=10s/30s/60s 对比
- [x] 5.3 实验 3.2（扩展）：使用 BGL 固定切片，scale engine replicas=1/2/3，固定 100 规则 × QPS=1000，记录 elapsed_seconds 和规则分配；记录 exp_id 和 dataset slice
- [ ] 5.4 可选压力上限：replicas=3/5，规则数=500，QPS=3000/5000（标注 optional，结果作为参考）
- [x] 5.5 实验 3.3（资源）：使用 HDFS_1 固定切片，规则数 50/100/200 × QPS 100/1000，kubectl top 每 30s 采样，稳态 10min；每组记录 exp_id
- [x] 5.6 实验 3.4（冷却消融）：cooldown=0/60/300，持续注入 10min（自定义 synthetic ERROR 日志即可），统计 raw_matches / alert_count / notification_count，计算压降比例
- [x] 5.7 编写数据汇总脚本，将各实验 CSV 合并为论文表格格式，汇总时带上 dataset/exp_id 列

## 6. 对比实验执行

- [ ] 6.1 确定 Grafana 对比实验使用的 HDFS_1 固定切片（dataset/start_line/line_count），与 5.1 延迟实验共用同一切片
- [ ] 6.2 对比延迟：两系统同时连接同一 Loki，使用相同 exp_id 和数据切片注入，记录各自 P50/P95/P99，每组 3 次；确保 Grafana evaluation interval=30s 与 LogSentinel 对齐
- [ ] 6.3 对比表达力（定性）：记录 Grafana Alerting 对 C3 序列场景的表达方式（需要几条规则/额外组件）
- [ ] 6.4 整理配置复杂度对比：LogSentinel 规则 JSON 字段数 vs Grafana AlertRule + LogQL 配置行数；补充 ElastAlert 定性分析（功能覆盖/部署依赖/是否需要 ES）
- [ ] 6.5 整理三系统功能覆盖对比表（keyword/threshold/sequence/negative 四类规则的支持情况）

## 7. 数据分析与论文图表

- [ ] 7.1 生成延迟 P50/P95/P99 箱线图（按规则类型分组）
- [ ] 7.2 生成水平扩展 speedup 曲线（实测 vs 理想线性，replicas=1/2/3）
- [ ] 7.3 生成资源消耗折线图（CPU/内存 vs 规则数）
- [ ] 7.4 生成冷却消融对比柱状图（三组 cooldown 配置的通知数 + 压降比例）
- [ ] 7.5 生成 LogSentinel vs Grafana Alerting 延迟对比表（P50/P95/P99）
- [ ] 7.6 整理功能对比表和配置复杂度表（含 ElastAlert 定性列）
- [ ] 7.7 整理功能测试截图（C1-C4 告警面板 + Engine 日志片段）
