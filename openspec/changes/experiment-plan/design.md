## Context

LogSentinel 已在单节点 K3s 集群上完整部署（API × 2、Engine × 3、Loki、PostgreSQL、Redis），但 Loki 内无日志数据，缺少 Promtail 采集链路和压测工具。实验需要两类数据来源：Promtail 采集的真实 K8s 日志（功能测试）和 Loghub 数据集回放（性能/对比实验）。

关键约束：
- Loki 配置了 `reject_old_samples: true, max_age: 168h`，所有注入日志的时间戳必须在 7 天窗口内
- 磁盘剩余 19GB，需控制 Loghub + Loki 存储在 8GB 以内
- 单节点 K3s，主性能实验规模需保守（避免 Loki/单节点成为瓶颈而非 Worker 分片能力）

## Goals / Non-Goals

**Goals:**
- 部署 Promtail DaemonSet，使 Engine 能查到真实 K8s 日志
- 构建 `benchmark/log_injector.py`，支持 Loghub 文件回放 + 时间戳重写 + 可控 QPS + exp_id/push_ack_ts 记录
- 定义并可复现四个功能测试场景（C1 关键词 / C2 阈值 / C3 序列 / C4 否定关联）
- 部署 Grafana Alerting 作为实测对比系统（等价阈值规则延迟对比）
- 执行性能实验（延迟/扩展/资源/冷却消融）并收集数据
- 整理 LogSentinel / Grafana Alerting / ElastAlert 三系统功能覆盖和配置复杂度对比表

**Non-Goals:**
- 不修改 LogSentinel 核心代码（engine、API、前端）
- 不部署 ElastAlert 做性能实测（依赖 ES，引入额外变量，磁盘不足）
- 不实现 Prometheus metrics 端点（留作未来工作）
- 不做多节点 K8s 扩展（单节点 K3s 足够）
- 不以 Precision/Recall/F1 作为主对比指标（LogSentinel 是规则引擎，非异常检测模型）

## Decisions

### 决策 1：延迟测量方法与口径区分

系统存在两种不同口径的延迟，必须明确区分：

**功能链路 E2E 延迟**（用于功能测试验证）：
```
Pod 日志输出 → Promtail 采集 → Loki 可查 → Engine 评估 → Alert 入库
```
包含 Promtail 采集抖动，不适合做精确性能对比。

**引擎评估延迟**（用于主性能压测，主论文口径）：
```
log_injector push ack (push_ack_ts_ns) → Engine 评估 → Alert 入库 (alert.created_at)
```
QPS 精确可控、可重复，不含 Promtail 采集抖动，论文中须注明采用此口径。

**实现方式**：注入器记录 `inject_ts_ns`、`push_ack_ts_ns` 到 JSONL 文件，实验后与 `alert.created_at`（API 查询）对账，分三段输出延迟数据。不改动 LogSentinel 源码。

### 决策 2：数据来源分工

**1. 功能测试数据源（C1-C4）**
K8s demo Pod 产生的真实 stdout/stderr 日志，经 Promtail DaemonSet 采集进入 Loki。用于功能闭环截图和 E2E 验证，体现系统在真实 K8s 场景下的端到端工作链路。

**2. 性能实验数据源（3.1-3.4）**
Loghub 数据集回放，主要使用 HDFS_1 和 BGL。通过 `benchmark/log_injector.py` 进行时间戳重写、QPS 控制和 Loki push（引擎评估延迟口径）。注入器在原始日志前附加 `exp_id`、`line_id`，并按实验需要注入含目标关键词（如 `ERROR` / `OOMKilled`）的日志，保证规则稳定触发。

**3. 对比实验数据源**
同一批 Loghub 回放数据，同时供 LogSentinel 和 Grafana Alerting 查询，保证同源 Loki、相同 exp_id、相同注入节奏。ElastAlert 不做性能实测，只做定性分析。

**数据集选择说明：**
- **HDFS_1**（~1.5GB，11M 行）：日志格式稳定，用于延迟、扩展性、资源消耗主实验，以及 optional anomaly label 辅助分析
- **BGL**（~700MB，4.7M 行）：系统日志形态，行频率更高，用于补充高频回放场景
- 主实验不依赖 Precision/Recall/F1，Loghub anomaly label 只作为 optional 字段保留在元数据中，不作为主结论依据

**实验记录要求：** 每轮实验须记录 dataset 名称、start_line、line_count、QPS、exp_id、规则类型、评估间隔，写入 results 元数据，保证可复现。

### 决策 3：对比系统选型与边界

**Grafana Alerting 纳入实测对比**：复用同一 Loki 数据源，在相同日志输入、相同评估间隔（30s）、相同存储后端下可控制变量，对比最公平。性能对比只做等价阈值规则，不扩展到序列/否定关联（两系统在这两类能力上不等价）。

**ElastAlert 只做定性分析**：依赖 Elasticsearch，会引入额外日志写入链路、ES 索引刷新机制和存储后端差异，难以隔离告警系统本身的性能差异；且 ES 需额外 8GB+ 磁盘（当前剩余 19GB）。ElastAlert 纳入功能覆盖、配置复杂度和部署依赖分析。

**对比实验结论口径**：不要求 LogSentinel 必须快于 Grafana Alerting；若两者延迟处于同一量级，即说明 LogSentinel 在基础阈值场景下具备可接受性能，同时提供更丰富的规则表达能力（序列关联、否定关联）。

### 决策 4：时间戳重写策略

Loghub 日志原始时间戳为 2008-2010 年，超出 Loki 7 天窗口会被拒收。

策略：将每条日志时间戳重写为 `now() - (original_ts - dataset_start_ts)`，保留日志间相对时序关系，绝对时间落在注入时间附近。Engine 的时间窗口语义（`window_seconds`）依然有效。

### 决策 5：水平扩展实验规模

主实验规模（单节点 K3s 可承受）：replicas=1/2/3，固定 100 条规则，QPS=100/500/1000，评估间隔 30s。

可选压力上限（标注 optional）：replicas=3/5，规则数=500，QPS=1000/3000/5000。规模保守的原因：单节点高 QPS 下 Loki 本身可能成为瓶颈，掩盖 Worker 分片能力。

### 决策 6：功能测试场景拆分为 4 个

C1（keyword）/ C2（threshold）/ C3（sequence）/ C4（negative correlation）各自独立，论文可分别证明每种规则类型的正确性，避免 keyword 和 threshold 混为一个场景被追问。

## Risks / Trade-offs

| 风险 | 缓解措施 |
|------|---------|
| Loki 拒收 >7 天日志 | 注入器强制时间戳重写，assert 时间差 < 6h |
| 单节点高 QPS 下 Loki 成为瓶颈 | 主实验 QPS ≤ 1000，可选实验单独说明瓶颈位置 |
| Grafana firing 时间难以自动采集 | 优先用 Grafana Alert History API；备选截图记录，论文中注明方式 |
| aiohttp Unclosed session warning | 记录在论文局限性章节，不影响功能 |
| 磁盘不足 | 每轮实验后清理 Loki 数据；Loghub 只保留 HDFS_1 + BGL |

## Migration Plan

1. 部署 Promtail → 验证 Loki 有数据 → Engine 能查到日志
2. 创建 C1-C4 规则 → 运行场景 → 截图记录
3. 下载 Loghub HDFS_1 + BGL → 预处理脚本 → 验证注入成功
4. 部署 Grafana → 配置等价阈值规则 → 验证能触发告警
5. 执行性能实验 3.1 → 3.2 → 3.3 → 3.4
6. 执行对比实验（延迟对比 + 功能/配置复杂度对比）
7. 整理数据 → 生成论文图表

回滚：所有新增组件独立 namespace 或独立目录，`kubectl delete ns monitoring` / `rm -rf benchmark/` 可完整清除。

## Open Questions

- Grafana Alert History API 路径需实测确认（不同 Grafana 版本 API 路径有差异）
- `benchmark/` 脚本纳入 Git，原始数据写入 `.gitignore`
- Loghub HDFS_1 anomaly label 为 block 级，若用于辅助分析需说明映射假设
