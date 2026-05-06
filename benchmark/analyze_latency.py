#!/usr/bin/env python3
"""
延迟分析脚本：读取 inject 元数据 + LogSentinel API alerts，输出三段延迟 P50/P95/P99

三段延迟定义：
  L1 = push_ack_ts_ns - inject_ts_ns     （注入到 Loki 确认写入）
  L2 = alert.created_at - push_ack_ts_ns （Loki 可查到 Engine 入库）
  L3 = alert.created_at - inject_ts_ns   （端到端总延迟）

用法：
  python3 benchmark/analyze_latency.py \
    --exp-id exp-test001 \
    --rule-id 10 \
    --api-url http://10.43.17.47:8000 \
    --results-dir benchmark/results
"""

import argparse
import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import List


def percentile(data: List[float], p: float) -> float:
    if not data:
        return 0.0
    s = sorted(data)
    idx = (len(s) - 1) * p / 100.0
    lo, hi = int(idx), min(int(idx) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (idx - lo)


def fetch_alerts(api_url: str, rule_id: int) -> list:
    """从 LogSentinel API 获取指定规则的告警列表"""
    url = "{}/api/alerts?limit=1000".format(api_url)
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read())
            if isinstance(data, list):
                alerts = data
            else:
                alerts = data.get("items", data.get("alerts", []))
            if rule_id:
                alerts = [a for a in alerts if a.get("rule_id") == rule_id]
            return alerts
    except Exception as e:
        print("[error] 获取告警失败: {}".format(e), file=sys.stderr)
        return []


def parse_alert_ts_ns(created_at: str) -> int:
    """解析 alert.created_at（ISO 格式）为纳秒时间戳"""
    # 兼容带/不带时区
    s = created_at.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except Exception:
        # Python 3.6 fallback
        s2 = s.split("+")[0].split(".")[0]
        dt = datetime.strptime(s2, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1e9)


def main():
    ap = argparse.ArgumentParser(description="LogSentinel 延迟分析")
    ap.add_argument("--exp-id", required=True, help="实验 ID")
    ap.add_argument("--rule-id", type=int, default=0, help="规则 ID（0=不过滤）")
    ap.add_argument("--api-url", default="http://10.43.17.47:8000")
    ap.add_argument("--results-dir", default="benchmark/results")
    ap.add_argument("--output-csv", default="", help="输出 CSV 路径（默认打印到 stdout）")
    args = ap.parse_args()

    results_dir = Path(args.results_dir)
    jsonl_path = results_dir / "inject_{}.jsonl".format(args.exp_id)
    meta_path = results_dir / "inject_{}_meta.json".format(args.exp_id)

    if not jsonl_path.exists():
        print("[error] 找不到元数据文件: {}".format(jsonl_path), file=sys.stderr)
        sys.exit(1)

    # 读取注入元数据
    inject_records = {}  # line_id -> record
    with open(str(jsonl_path)) as f:
        for line in f:
            rec = json.loads(line.strip())
            inject_records[rec["line_id"]] = rec

    # 读取实验元数据
    exp_meta = {}
    if meta_path.exists():
        exp_meta = json.loads(meta_path.read_text())
        print("[info] 实验: {} dataset={} qps={} rule_type={}".format(
            args.exp_id, exp_meta.get("dataset"), exp_meta.get("qps"), exp_meta.get("rule_type")))

    # 获取告警
    alerts = fetch_alerts(args.api_url, args.rule_id)
    print("[info] 获取到 {} 条告警（rule_id={}）".format(len(alerts), args.rule_id or "全部"))

    if not alerts:
        print("[warn] 无告警数据，无法计算延迟")
        sys.exit(0)

    # 计算三段延迟
    # 策略：用告警的 created_at 与该实验期间的 push_ack_ts 中位数匹配
    # （高 QPS 场景下告警与具体日志行一对一映射困难，用批次 ack 时间作为近似）
    push_acks_ns = [rec["push_ack_ts_ns"] for rec in inject_records.values()
                    if rec.get("push_ack_ts_ns")]
    inject_ts_list = [rec["inject_ts_ns"] for rec in inject_records.values()]

    if not push_acks_ns:
        print("[warn] 无 push_ack_ts_ns 数据", file=sys.stderr)
        sys.exit(1)

    # 取注入开始时间作为基准
    inject_start_ns = min(inject_ts_list)
    inject_end_ns = max(inject_ts_list)

    # L1: push 确认延迟（所有批次的平均）
    l1_list = []
    batch_seen = set()
    for rec in inject_records.values():
        ack = rec.get("push_ack_ts_ns")
        inj = rec.get("inject_ts_ns")
        if ack and inj and ack not in batch_seen:
            batch_seen.add(ack)
            l1_list.append((ack - inj) / 1e6)  # → ms

    # L2 & L3: 基于 alert.created_at
    l2_list = []
    l3_list = []
    ref_push_ack_ns = sorted(push_acks_ns)[-1]  # 最后一批 ack 时间

    for alert in alerts:
        created_at = alert.get("created_at", "")
        if not created_at:
            continue
        try:
            alert_ts_ns = parse_alert_ts_ns(created_at)
        except Exception:
            continue
        # L2: 最后一批推送完成到告警创建
        l2 = (alert_ts_ns - ref_push_ack_ns) / 1e6
        # L3: 注入开始到告警创建
        l3 = (alert_ts_ns - inject_start_ns) / 1e6
        if l2 >= 0:
            l2_list.append(l2)
        if l3 >= 0:
            l3_list.append(l3)

    def fmt_pct(data, label):
        if not data:
            return "{}: 无数据".format(label)
        return "{}: P50={:.0f}ms  P95={:.0f}ms  P99={:.0f}ms  (n={})".format(
            label,
            percentile(data, 50),
            percentile(data, 95),
            percentile(data, 99),
            len(data)
        )

    print("\n── 延迟报告 ──────────────────────────────────────────")
    print("exp_id     : {}".format(args.exp_id))
    print("注入行数   : {}".format(len(inject_records)))
    print("告警数     : {}".format(len(alerts)))
    print()
    print(fmt_pct(l1_list, "L1 注入→Loki确认  "))
    print(fmt_pct(l2_list, "L2 Loki确认→告警  "))
    print(fmt_pct(l3_list, "L3 端到端          "))
    print("────────────────────────────────────────────────────\n")

    if args.output_csv:
        import csv
        with open(args.output_csv, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["exp_id", "segment", "P50_ms", "P95_ms", "P99_ms", "n"])
            for label, data in [("L1_inject_to_ack", l1_list),
                                 ("L2_ack_to_alert", l2_list),
                                 ("L3_end_to_end", l3_list)]:
                w.writerow([
                    args.exp_id, label,
                    round(percentile(data, 50), 1),
                    round(percentile(data, 95), 1),
                    round(percentile(data, 99), 1),
                    len(data)
                ])
        print("[done] CSV 写入: {}".format(args.output_csv))


if __name__ == "__main__":
    main()
