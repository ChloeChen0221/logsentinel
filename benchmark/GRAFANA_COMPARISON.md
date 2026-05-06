# Grafana Alerting 对比实验说明

## 部署信息

| 组件 | 端口 | 说明 |
|------|------|------|
| Grafana Web UI | NodePort 30882 | `http://<node_ip>:30882` admin/admin |
| Loki datasource | ClusterIP 内部 | 指向 `logsentinel-loki.logsentinel:3100` |
| 告警规则 | `ls-c2-equivalent` | 与 LogSentinel C2 等价 |

## 等价阈值规则

**语义**：5 分钟内同一 namespace/pod 下 ERROR 日志数 >= 10

**LogQL**：
```logql
sum by (namespace, pod) (count_over_time({namespace="demo"} |= "ERROR" [5m]))
```

**Threshold**：`> 10`（对应 LogSentinel `threshold=10`）

**Evaluation Interval**：30s（与 LogSentinel `ENGINE_INTERVAL_SECONDS=30` 对齐）

## Firing 时间采集方式

### 方式 A（优先）：Grafana Alert Rule State API（自动）

```bash
# 轮询获取规则当前状态
curl -s -u admin:admin "http://<node_ip>:30882/api/prometheus/grafana/api/v1/rules"
# → 每条规则返回 state=inactive/pending/firing + lastEvaluation + activeAt

# 或查询活跃告警列表（只在 firing 后有数据）
curl -s -u admin:admin "http://<node_ip>:30882/api/alertmanager/grafana/api/v2/alerts"
# → firing 告警的 startsAt 字段即为首次 firing 时间
```

**使用脚本自动采集**：
```bash
python3 benchmark/scenarios/grafana_alert_watcher.py \
  --rule-uid ls-c2-equivalent \
  --timeout 600 \
  --output benchmark/results/grafana_firing_<exp_id>.json
```

输出格式：
```json
{
  "rule_uid": "ls-c2-equivalent",
  "title": "LS-C2-equivalent-ERROR-threshold",
  "first_firing_ts_ns": 1777370000000000000,
  "activeAt": "2026-05-04T07:30:00Z",
  "watch_start_ts_ns": 1777369800000000000
}
```

### 方式 B（备选）：截图法

如果 API 采集失败，打开 Grafana UI → Alerting → Alert rules，查看规则详情页
的 state history 面板，截图并在论文中注明采集方式。

## 对比实验操作步骤

1. **准备相同数据**（LogSentinel 和 Grafana 使用同一 exp_id）：
```bash
python3 benchmark/log_injector.py \
  --dataset HDFS_v1 --start-line 0 --line-count 10000 \
  --qps 500 --exp-id exp-compare-001 --rule-type threshold \
  --inject-keyword ERROR --namespace demo --pod demo-app
```

2. **同时启动 Grafana watcher**：
```bash
python3 benchmark/scenarios/grafana_alert_watcher.py \
  --rule-uid ls-c2-equivalent \
  --timeout 600 \
  --output benchmark/results/grafana_firing_exp-compare-001.json &
```

3. **分析延迟**：
   - LogSentinel：`benchmark/analyze_latency.py --exp-id exp-compare-001 --rule-id 15`
   - Grafana：读取 `grafana_firing_*.json` 中 `first_firing_ts_ns`，与注入元数据对比

## 公平性约束

- ✓ 同一 Loki 实例
- ✓ 同一 exp_id 和注入数据
- ✓ 相同评估间隔（30s）
- ✓ 等价规则语义（LogQL count_over_time 对应 LogSentinel threshold+group_by）
- ✗ 不对比 C3 序列和 C4 否定关联（Grafana 不原生支持，只做定性分析）
- ✗ 不做 ElastAlert 实测（引入 Elasticsearch 额外变量）
