## Why

LogSentinel 核心功能已开发完成，需要通过系统化实验验证其正确性、性能表现及相对于同类工具的竞争力，以支撑毕业论文的实验章节。当前 Loki 无数据、无压测工具、无对比系统，必须补齐实验基础设施并按计划执行实验。

## What Changes

- **新增** Promtail DaemonSet，采集 K8s Pod 日志并推入 Loki（功能测试数据源）
- **新增** `benchmark/log_injector.py`：支持 Loghub 数据集回放 + 时间戳重写 + 可控 QPS + exp_id/push_ack_ts 记录（性能/对比实验数据源）
- **新增** `benchmark/scenarios/`：功能测试四个 E2E 场景（C1 关键词 / C2 阈值 / C3 正向序列 / C4 否定关联）的规则配置与复现脚本
- **新增** Grafana + Grafana Alerting 部署（等价阈值规则延迟实测对比）
- **新增** `benchmark/results/`：实验原始数据与分析脚本
- **不改动** LogSentinel 核心业务代码（引擎、API、前端）

## Capabilities

### New Capabilities

- `promtail-deployment`：Promtail DaemonSet 部署配置，采集 K8s Pod 日志到 Loki（含 namespace/pod/container/app label）
- `log-injector`：Loghub 数据集预处理 + 时间戳重写 + Loki push 注入工具，支持可控 QPS、exp_id/line_id 追踪、push_ack_ts_ns 记录和三段延迟分析
- `e2e-scenarios`：功能测试四场景（C1 关键词 / C2 阈值 / C3 正向序列 / C4 否定关联）的规则定义与复现脚本
- `grafana-alerting-setup`：Grafana Alerting 部署与等价阈值规则配置，用于实测延迟对比；ElastAlert 只做功能/配置复杂度定性分析
- `experiment-execution`：性能实验（引擎评估延迟/扩展性/资源/冷却消融）和对比实验（延迟对比 + 功能覆盖 + 配置复杂度）的执行脚本与数据分析

### Modified Capabilities

（无，不变更现有功能规格）

## Impact

- **新增文件**：`benchmark/` 目录、`helm-charts/promtail/`、`helm-charts/grafana/`
- **不涉及** backend/frontend 代码变更
- **磁盘消耗**：Loghub 数据集约 3GB，实验结果约 1GB，共需 4GB 剩余空间（当前 19GB 可用，充足）
- **资源影响**：Promtail DaemonSet 极轻量（requests: 50m CPU / 64Mi），Grafana 约 200m CPU / 256Mi
- **风险**：Loki `reject_old_samples_max_age=168h`，注入器必须做时间戳重写；ElastAlert 不做性能实测，避免引入 ES 存储后端变量和磁盘压力
