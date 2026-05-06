# LogSentinel 实验工具包

## 目录结构

```
benchmark/
├── data/                      # Loghub 数据集（.gitignore）
│   ├── HDFS_v1/              # HDFS_v1 11M 行
│   └── BGL/                  # BGL 4.7M 行
├── lib/
│   └── experiment_utils.py   # 实验公共工具（Loki 清理、规则管理、kubectl）
├── scenarios/                 # 功能测试场景脚本
│   ├── create_rules.py       # 创建 C1-C4 规则
│   ├── c1_inject.py          # C1 关键词场景（single/multi/cooldown）
│   ├── c2_inject.py          # C2 阈值场景（threshold/multipod）
│   ├── c3_inject.py          # C3 正向序列（complete/incomplete/timeout）
│   ├── c4_inject.py          # C4 否定关联（silent/normal）
│   ├── reset.py              # 清理场景告警和状态
│   ├── create_grafana_rule.py      # 创建 Grafana 等价规则
│   └── grafana_alert_watcher.py    # 监听 Grafana firing 时间
├── results/                   # 实验结果（.gitignore）
├── preprocess_loghub.py      # Loghub 预处理 + Loki push 验证
├── log_injector.py           # 主注入工具（QPS 控制 + 元数据记录）
├── analyze_latency.py        # 三段延迟分析（P50/P95/P99）
├── exp_5_1_latency.py        # 实验 5.1 延迟
├── exp_5_3_scaling.py        # 实验 5.3 扩展性
├── exp_5_5_resource.py       # 实验 5.5 资源消耗
├── exp_5_6_cooldown.py       # 实验 5.6 冷却消融
├── summarize_results.py      # 汇总所有 CSV 到论文表格
├── EXPERIMENT_SLICES.md      # 固定数据切片说明
└── GRAFANA_COMPARISON.md     # Grafana 对比实验说明
```

## 按需跑实验

每个实验脚本独立可跑，相互无依赖。建议顺序：

### 1. 前置验证（必做）

```bash
# 预处理验证：推 200 行 HDFS 到 Loki
python3 benchmark/preprocess_loghub.py \
  --dataset HDFS_v1 --line-count 200 --push
```

### 2. 功能测试（按需分阶段跑）

```bash
# C1 关键词（3 个阶段）
python3 benchmark/scenarios/c1_inject.py --phase single
python3 benchmark/scenarios/c1_inject.py --phase multi
python3 benchmark/scenarios/c1_inject.py --phase cooldown

# C2 阈值
python3 benchmark/scenarios/c2_inject.py --phase threshold
python3 benchmark/scenarios/c2_inject.py --phase multipod

# C3 正向序列
python3 benchmark/scenarios/c3_inject.py --phase complete
python3 benchmark/scenarios/c3_inject.py --phase incomplete
# timeout 需要 320s 等待，可选

# C4 否定关联
python3 benchmark/scenarios/c4_inject.py --phase silent
python3 benchmark/scenarios/c4_inject.py --phase normal

# 每个阶段跑完后，查看 LogSentinel 前端或 API 验证告警
curl http://10.43.17.47:8000/api/alerts | jq

# 场景间清理
python3 benchmark/scenarios/reset.py --scenario C1
python3 benchmark/scenarios/reset.py --all
```

### 3. 性能实验（重型，可分开跑）

**所有性能实验都会：**
- 实验前：自动禁用非 C1-C4 的旧规则 + 清理 Loki 数据
- 实验后：自动恢复旧规则 + 删除 EXP- 开头的实验规则

```bash
# 5.1 延迟实验（~2h，9 个组合 × 3 次）
python3 benchmark/exp_5_1_latency.py

# 只跑部分组合
python3 benchmark/exp_5_1_latency.py --rule-type keyword --qps 500 --repeat 1

# 5.3 扩展性实验（~10min）
python3 benchmark/exp_5_3_scaling.py

# 只跑 replicas=1
python3 benchmark/exp_5_3_scaling.py --replicas 1

# 5.5 资源实验（~72min，6 个组合 × 10min 稳态）
python3 benchmark/exp_5_5_resource.py

# 短版本测试（5min 稳态）
python3 benchmark/exp_5_5_resource.py --duration 300

# 5.6 冷却消融（~33min，3 个 cooldown × 10min）
python3 benchmark/exp_5_6_cooldown.py

# 短版本
python3 benchmark/exp_5_6_cooldown.py --duration 300
```

### 4. Grafana 对比实验

```bash
# 确认 Grafana 规则已创建
python3 benchmark/scenarios/create_grafana_rule.py

# 同时启动两系统的数据源
python3 benchmark/log_injector.py --dataset HDFS_v1 --line-count 10000 \
  --qps 500 --exp-id exp-compare-001 --rule-type threshold \
  --inject-keyword ERROR --namespace demo --pod demo-app &

# 后台监听 Grafana firing
python3 benchmark/scenarios/grafana_alert_watcher.py \
  --rule-uid ls-c2-equivalent --timeout 600 \
  --output benchmark/results/grafana_firing_exp-compare-001.json

# 对比两系统延迟
python3 benchmark/analyze_latency.py --exp-id exp-compare-001 --rule-id 15
# 读取 grafana_firing 文件，与 inject 元数据对比
```

### 5. 汇总结果

```bash
# 将所有 exp_5_*.csv 汇总到论文表格
python3 benchmark/summarize_results.py
# 产出 benchmark/results/summary/table_5_*.csv
```

## 实验前提检查

```bash
# 查看所有规则
python3 benchmark/lib/experiment_utils.py list-rules

# 手动禁用旧规则（如果某次实验意外被打断没恢复）
python3 benchmark/lib/experiment_utils.py disable-old

# 手动清理 EXP- 实验规则
python3 benchmark/lib/experiment_utils.py cleanup-exp

# 手动清 Loki
python3 benchmark/lib/experiment_utils.py clean-loki

# 调整 Engine 副本数
python3 benchmark/lib/experiment_utils.py scale --replicas 3
```

## 注意事项

1. **`--no-clean-loki`**：每个实验脚本默认会清 Loki，如果想连续多实验复用数据可加此参数
2. **`--keep-rules`**：实验后保留 EXP- 规则，便于手动复查
3. **场景规则 C1-C4（id=14/15/16/17）永远不会被实验脚本动**
4. **Engine aiohttp Unclosed session warning** 累积可能导致 OOM，长时间实验建议分批跑
5. **Redis 密码**脚本会从 secret 自动读取，无需手动设置
