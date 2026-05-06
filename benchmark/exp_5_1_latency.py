#!/usr/bin/env python3
"""
实验 5.1：端到端延迟
- 变量：规则类型 (keyword/threshold/sequence) × QPS (100/500/1000)
- 固定：eval_interval=30s，HDFS_v1 切片 10000 行，每组重复 3 次
- 输出：三段延迟 CSV (benchmark/results/exp_5_1_latency.csv)

用法：
  python3 benchmark/exp_5_1_latency.py                      # 全部跑
  python3 benchmark/exp_5_1_latency.py --rule-type keyword  # 只跑 keyword
  python3 benchmark/exp_5_1_latency.py --qps 500            # 只跑 QPS=500
  python3 benchmark/exp_5_1_latency.py --repeat 1           # 每组只跑 1 次
  python3 benchmark/exp_5_1_latency.py --no-clean-loki      # 不清 Loki
"""

import argparse
import csv
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lib.experiment_utils import (
    prepare_experiment, teardown_experiment,
    create_exp_rule, cleanup_exp_data, loki_clean_data,
    API_URL, LOKI_URL,
)

RESULTS_DIR = Path(__file__).parent / "results"
RESULTS_DIR.mkdir(exist_ok=True)

DEFAULT_QPS_LIST = [100, 500, 1000]
DEFAULT_RULE_TYPES = ["keyword", "threshold", "sequence"]
LINE_COUNT = 2000  # 每次注入行数（按最小 QPS 100 下 20s 计算）


def run_injection(exp_id, rule_type, qps, rule_id):
    """运行一次注入"""
    print("  [inject] exp_id={} type={} qps={} rule_id={}".format(
        exp_id, rule_type, qps, rule_id))
    cmd = [
        "python3", "benchmark/log_injector.py",
        "--dataset", "HDFS_v1",
        "--start-line", "0",
        "--line-count", str(LINE_COUNT),
        "--qps", str(qps),
        "--exp-id", exp_id,
        "--rule-type", rule_type,
        "--inject-keyword", "ERROR",
        "--namespace", "demo",
        "--pod", "exp51-pod",
        "--eval-interval", "30",
        "--loki-url", LOKI_URL,
    ]
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       universal_newlines=True, timeout=300)
    if r.returncode != 0:
        print("[inject error] {}".format(r.stderr), file=sys.stderr, flush=True)
        return False
    return True


def run_analysis(exp_id, rule_id):
    """运行延迟分析"""
    csv_path = RESULTS_DIR / "latency_{}.csv".format(exp_id)
    cmd = [
        "python3", "benchmark/analyze_latency.py",
        "--exp-id", exp_id,
        "--rule-id", str(rule_id),
        "--api-url", API_URL,
        "--results-dir", str(RESULTS_DIR),
        "--output-csv", str(csv_path),
    ]
    subprocess.run(cmd, timeout=60)
    return csv_path


def create_rule_for_type(rule_type):
    """为指定类型创建实验规则"""
    suffix = "5-1-{}".format(rule_type)
    if rule_type == "keyword":
        return create_exp_rule(suffix, "keyword", "ERROR",
                               window_seconds=0, threshold=1, cooldown=0)
    elif rule_type == "threshold":
        return create_exp_rule(suffix, "threshold", "ERROR",
                               window_seconds=60, threshold=10, cooldown=0)
    elif rule_type == "sequence":
        # 序列规则：step1=ERROR（简化版，容易触发）
        steps = [{
            "step_order": 0, "match_type": "contains",
            "match_pattern": "ERROR", "window_seconds": 60, "threshold": 1
        }, {
            "step_order": 1, "match_type": "contains",
            "match_pattern": "ERROR", "window_seconds": 60, "threshold": 1
        }]
        return create_exp_rule(suffix, "sequence", "ERROR",
                               window_seconds=60, threshold=1, cooldown=0,
                               steps=steps, correlation_type="sequence")


def merge_csvs(output_path):
    """合并所有 latency_*.csv 到一个汇总 CSV"""
    rows = []
    for csv_file in sorted(RESULTS_DIR.glob("latency_exp-5-1-*.csv")):
        with open(csv_file) as f:
            reader = csv.DictReader(f)
            for row in reader:
                # exp_id 示例：exp-5-1-keyword-100-1
                parts = row["exp_id"].split("-")
                if len(parts) >= 5:
                    row["rule_type"] = parts[3]
                    row["qps"] = parts[4]
                    row["trial"] = parts[5] if len(parts) >= 6 else "1"
                rows.append(row)

    if not rows:
        print("[warn] 无结果数据", file=sys.stderr, flush=True)
        return

    fieldnames = ["exp_id", "rule_type", "qps", "trial", "segment",
                  "P50_ms", "P95_ms", "P99_ms", "n"]
    with open(output_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k, "") for k in fieldnames})
    print("[done] 汇总 CSV: {}".format(output_path), flush=True)


def main():
    ap = argparse.ArgumentParser(description="实验 5.1：端到端延迟")
    ap.add_argument("--rule-type", choices=DEFAULT_RULE_TYPES)
    ap.add_argument("--qps", type=int)
    ap.add_argument("--repeat", type=int, default=3)
    ap.add_argument("--no-clean-loki", action="store_true")
    ap.add_argument("--keep-rules", action="store_true",
                    help="实验后保留 EXP- 规则（便于复跑）")
    args = ap.parse_args()

    rule_types = [args.rule_type] if args.rule_type else DEFAULT_RULE_TYPES
    qps_list = [args.qps] if args.qps else DEFAULT_QPS_LIST

    # 准备
    disabled = prepare_experiment(clean_loki=not args.no_clean_loki)

    # 预创建所有 rule_type 的规则（一次性），等 Engine 加载后再开始注入
    rule_ids = {}
    for rt in rule_types:
        rid = create_rule_for_type(rt)
        if rid:
            rule_ids[rt] = rid
            print("[rules] 创建 {} 规则 id={}".format(rt, rid), flush=True)
        else:
            print("[error] 规则创建失败，跳过 {}".format(rt), flush=True)

    print("[wait] 等待 Engine 加载所有规则（65s）...", flush=True)
    time.sleep(65)

    total = len(rule_types) * len(qps_list) * args.repeat
    done = 0
    start_time = time.time()

    try:
        for rt in rule_types:
            if rt not in rule_ids:
                continue
            rid = rule_ids[rt]

            for qps in qps_list:
                for trial in range(1, args.repeat + 1):
                    done += 1
                    exp_id = "exp-5-1-{}-{}-{}".format(rt, qps, trial)
                    print("\n━━━ [{}/{}] {} QPS={} trial={} ━━━".format(
                        done, total, rt, qps, trial))

                    # 清理该规则的历史数据
                    cleanup_exp_data([rid])

                    # 注入
                    if not run_injection(exp_id, rt, qps, rid):
                        continue

                    # 等待 Engine 评估：2 个周期 = 60s
                    print("  [wait] 等待 Engine 评估（60s）...", flush=True)
                    time.sleep(60)

                    # 分析
                    run_analysis(exp_id, rid)

                    elapsed = time.time() - start_time
                    remaining = elapsed / done * (total - done)
                    print("  [progress] 已完成 {}/{}，预计剩余 {:.0f}min".format(
                        done, total, remaining / 60))
    finally:
        # 汇总
        summary = RESULTS_DIR / "exp_5_1_latency_summary.csv"
        merge_csvs(summary)

        # 清理
        teardown_experiment(disabled, delete_exp_rules=not args.keep_rules)


if __name__ == "__main__":
    main()
