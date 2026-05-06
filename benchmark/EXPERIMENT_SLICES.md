# 实验数据切片说明

所有性能实验和对比实验使用固定切片，保证可复现。

## 主实验切片

| 数据集 | start_line | line_count | 用途 |
|--------|-----------|------------|------|
| HDFS_v1 | 0 | 10000 | 延迟实验(3.1)、资源实验(3.3)、Grafana 对比实验 |
| BGL | 0 | 10000 | 扩展性实验(3.2) |

## 数据集基本信息

- **HDFS_v1**：`benchmark/data/HDFS_v1/HDFS.log`，共 11,175,629 行
  - 异常标签：`benchmark/data/HDFS_v1/preprocessed/anomaly_label.csv`
  - 日志格式：`YYMMDD HHMMSS <thread> <level> <component>: <message>`
- **BGL**：`benchmark/data/BGL/BGL.log`，共 4,747,963 行
  - 日志格式：`<label> <unix_ts> <date> <node> <datetime> <node> <type> <component> <level> <message>`

## 注入命令模板

```bash
# 延迟实验（keyword 规则）
python3 benchmark/log_injector.py \
  --dataset HDFS_v1 --start-line 0 --line-count 10000 \
  --qps <QPS> --exp-id <exp_id> --rule-type keyword \
  --inject-keyword ERROR --namespace demo --pod demo-app \
  --eval-interval 30 --loki-url http://10.43.64.140:3100

# 扩展性实验（BGL）
python3 benchmark/log_injector.py \
  --dataset BGL --start-line 0 --line-count 10000 \
  --qps 1000 --exp-id <exp_id> --rule-type threshold \
  --inject-keyword OOMKilled --namespace demo --pod demo-app \
  --eval-interval 30 --loki-url http://10.43.64.140:3100

# Grafana 对比实验（与延迟实验使用相同切片）
# LogSentinel 和 Grafana 使用相同 exp_id，保证数据同源
python3 benchmark/log_injector.py \
  --dataset HDFS_v1 --start-line 0 --line-count 10000 \
  --qps 500 --exp-id <shared_exp_id> --rule-type threshold \
  --inject-keyword ERROR --namespace demo --pod demo-app \
  --eval-interval 30 --loki-url http://10.43.64.140:3100
```
