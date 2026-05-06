#!/usr/bin/env python3
"""
汇总所有实验 CSV 结果，输出论文表格格式

用法：
  python3 benchmark/summarize_results.py
  python3 benchmark/summarize_results.py --output-dir benchmark/results/summary
"""

import argparse
import csv
from pathlib import Path
from collections import defaultdict


RESULTS_DIR = Path(__file__).parent / "results"


def summarize_5_1_latency(results_dir: Path, output_dir: Path):
    """延迟实验：按 rule_type × qps 聚合，取 3 次 trial 的中位数"""
    src = results_dir / "exp_5_1_latency_summary.csv"
    if not src.exists():
        print("[skip] {} 不存在".format(src))
        return

    # 结构：{(rule_type, qps, segment): [P50_trial1, P50_trial2, ...]}
    p50 = defaultdict(list)
    p95 = defaultdict(list)
    p99 = defaultdict(list)

    with open(src) as f:
        for row in csv.DictReader(f):
            key = (row["rule_type"], row["qps"], row["segment"])
            try:
                p50[key].append(float(row["P50_ms"]))
                p95[key].append(float(row["P95_ms"]))
                p99[key].append(float(row["P99_ms"]))
            except (ValueError, TypeError):
                pass

    # 中位数
    def median(lst):
        if not lst:
            return 0
        s = sorted(lst)
        n = len(s)
        return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2

    out = output_dir / "table_5_1_latency.csv"
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["rule_type", "qps", "segment", "P50_ms_median",
                    "P95_ms_median", "P99_ms_median", "trials"])
        for key in sorted(p50.keys()):
            w.writerow([
                key[0], key[1], key[2],
                round(median(p50[key]), 1),
                round(median(p95[key]), 1),
                round(median(p99[key]), 1),
                len(p50[key]),
            ])
    print("[done] 延迟表: {}".format(out))


def summarize_5_3_scaling(results_dir: Path, output_dir: Path):
    """扩展性：按 replicas 聚合，计算 speedup"""
    src = results_dir / "exp_5_3_scaling.csv"
    if not src.exists():
        print("[skip] {} 不存在".format(src))
        return

    by_replicas = defaultdict(list)
    with open(src) as f:
        for row in csv.DictReader(f):
            try:
                r = int(row["replicas"])
                cycles = int(row["cycles"])
                elapsed = float(row["avg_elapsed_s"])
                by_replicas[r].append({
                    "pod": row["pod_name"],
                    "my_rules": int(row["my_rules"]),
                    "cycles": cycles,
                    "elapsed_s": elapsed,
                })
            except (ValueError, TypeError):
                pass

    # baseline = replicas=1 的吞吐
    baseline_throughput = None
    rows = []
    for r in sorted(by_replicas.keys()):
        pods = by_replicas[r]
        total_rules = sum(p["my_rules"] for p in pods)
        total_cycles = sum(p["cycles"] for p in pods)
        avg_elapsed = sum(p["elapsed_s"] for p in pods) / len(pods) if pods else 0
        # 吞吐 = 总评估次数 × 规则数 / 采样时长（近似）
        throughput = total_cycles * (total_rules / len(pods)) if pods else 0

        if baseline_throughput is None and r == 1:
            baseline_throughput = throughput
        speedup = throughput / baseline_throughput if baseline_throughput else 0

        counts = [p["my_rules"] for p in pods]
        balance_ratio = max(counts) / min(counts) if counts and min(counts) > 0 else 0

        rows.append([r, total_rules, len(pods), round(avg_elapsed, 4),
                     round(throughput, 1), round(speedup, 2),
                     round(balance_ratio, 2)])

    out = output_dir / "table_5_3_scaling.csv"
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["replicas", "total_rules", "pods", "avg_elapsed_s",
                    "throughput", "speedup", "balance_ratio_max_min"])
        w.writerows(rows)
    print("[done] 扩展性表: {}".format(out))


def summarize_5_5_resource(results_dir: Path, output_dir: Path):
    """资源：按 (rule_count, qps) 聚合，取稳态均值"""
    src = results_dir / "exp_5_5_resource.csv"
    if not src.exists():
        print("[skip] {} 不存在".format(src))
        return

    # 只统计 engine Pod
    by_combo = defaultdict(lambda: {"cpu": [], "mem": [], "redis_mb": []})
    with open(src) as f:
        for row in csv.DictReader(f):
            if "engine" not in row["pod"]:
                # 只对 engine 聚合；redis 单独统计
                if "redis" in row["pod"]:
                    pass
                continue
            key = (int(row["rule_count"]), int(row["qps"]))
            try:
                by_combo[key]["cpu"].append(int(row["cpu_milli"]))
                by_combo[key]["mem"].append(int(row["mem_mi"]))
                by_combo[key]["redis_mb"].append(float(row["redis_used_memory_mb"]))
            except (ValueError, TypeError):
                pass

    out = output_dir / "table_5_5_resource.csv"
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["rule_count", "qps", "engine_cpu_milli_avg",
                    "engine_mem_mi_avg", "redis_mem_mb_avg", "samples"])
        for key in sorted(by_combo.keys()):
            data = by_combo[key]
            n = len(data["cpu"])
            w.writerow([
                key[0], key[1],
                round(sum(data["cpu"]) / n) if n else 0,
                round(sum(data["mem"]) / n) if n else 0,
                round(sum(data["redis_mb"]) / n, 1) if n else 0,
                n,
            ])
    print("[done] 资源表: {}".format(out))


def summarize_5_6_cooldown(results_dir: Path, output_dir: Path):
    """冷却消融：保留原始结果，添加压降比例"""
    src = results_dir / "exp_5_6_cooldown.csv"
    if not src.exists():
        print("[skip] {} 不存在".format(src))
        return

    out = output_dir / "table_5_6_cooldown.csv"
    with open(src) as fi, open(out, "w", newline="") as fo:
        reader = csv.DictReader(fi)
        fieldnames = list(reader.fieldnames) + ["compression_pct"]
        writer = csv.DictWriter(fo, fieldnames=fieldnames)
        writer.writeheader()
        for row in reader:
            try:
                ratio = float(row["compression_ratio"])
                row["compression_pct"] = "{:.2f}%".format(ratio * 100)
            except Exception:
                row["compression_pct"] = ""
            writer.writerow(row)
    print("[done] 冷却表: {}".format(out))


def main():
    ap = argparse.ArgumentParser(description="汇总所有实验结果")
    ap.add_argument("--results-dir", default=str(RESULTS_DIR))
    ap.add_argument("--output-dir", default=str(RESULTS_DIR / "summary"))
    args = ap.parse_args()

    results_dir = Path(args.results_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    summarize_5_1_latency(results_dir, output_dir)
    summarize_5_3_scaling(results_dir, output_dir)
    summarize_5_5_resource(results_dir, output_dir)
    summarize_5_6_cooldown(results_dir, output_dir)

    print("\n[all done] 汇总目录: {}".format(output_dir))


if __name__ == "__main__":
    main()
