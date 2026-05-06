#!/usr/bin/env python3
"""
实验 5.5：资源消耗
- 变量：规则数 (50/100/200) × QPS (100/1000)
- 固定：HDFS_v1 数据集、eval_interval=30s、Engine replicas=3
- 采样：kubectl top pods 每 30s 一次，稳态持续 10min
- 输出：Engine/Redis/PG 的 CPU/内存随时间曲线

用法：
  python3 benchmark/exp_5_5_resource.py                    # 全部跑
  python3 benchmark/exp_5_5_resource.py --rule-count 50 --qps 100
  python3 benchmark/exp_5_5_resource.py --duration 300     # 稳态 5min
"""

import argparse
import csv
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lib.experiment_utils import (
    prepare_experiment, teardown_experiment,
    create_exp_rule, cleanup_exp_data,
    LOKI_URL, run, redis_cmd,
)

RESULTS_DIR = Path(__file__).parent / "results"
RESULTS_DIR.mkdir(exist_ok=True)


def create_rules_batch(count):
    """批量创建实验规则"""
    print("[rules] 创建 {} 条规则...".format(count), flush=True)
    ids = []
    for i in range(count):
        rid = create_exp_rule(
            suffix="5-5-{:04d}".format(i),
            rule_type="threshold",
            match_pattern="ERROR",
            window_seconds=60, threshold=100000, cooldown=300,
        )
        if rid:
            ids.append(rid)
    return ids


def start_injector(exp_id, qps, duration_s):
    line_count = qps * duration_s
    cmd = [
        "python3", "benchmark/log_injector.py",
        "--dataset", "HDFS_v1", "--start-line", "0",
        "--line-count", str(line_count), "--qps", str(qps),
        "--exp-id", exp_id, "--rule-type", "threshold",
        "--inject-keyword", "ERROR", "--namespace", "demo",
        "--pod", "exp55-pod", "--loki-url", LOKI_URL,
    ]
    return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def parse_top_line(line):
    """
    解析 `kubectl top pods` 输出
    格式: NAME  CPU(cores)  MEMORY(bytes)
    """
    parts = line.split()
    if len(parts) < 3:
        return None
    name = parts[0]
    cpu_raw = parts[1]  # e.g. "123m"
    mem_raw = parts[2]  # e.g. "256Mi"

    # CPU 单位 m
    cpu = 0
    m = re.match(r"(\d+)m?", cpu_raw)
    if m:
        cpu = int(m.group(1))
        if "m" not in cpu_raw:
            cpu *= 1000  # 核 → 毫核

    # 内存单位 Mi
    mem = 0
    m = re.match(r"(\d+)([MG]?i?)", mem_raw)
    if m:
        mem = int(m.group(1))
        unit = m.group(2)
        if unit.startswith("G"):
            mem *= 1024

    return {"pod": name, "cpu_milli": cpu, "mem_mi": mem}


def sample_metrics(rule_count, qps):
    """采样一次当前资源用量"""
    r = run(["kubectl", "top", "pods", "-n", "logsentinel", "--no-headers"], timeout=10)
    pods = []
    if r.returncode == 0:
        for line in r.stdout.strip().split("\n"):
            p = parse_top_line(line)
            if p:
                pods.append(p)

    # Redis 内存
    redis_mem = redis_cmd(["INFO", "memory"])
    used_mem = 0
    for ml in redis_mem.split("\n"):
        if ml.startswith("used_memory:"):
            used_mem = int(ml.split(":")[1].strip())
            break

    return {
        "ts": int(time.time()),
        "rule_count": rule_count,
        "qps": qps,
        "pods": pods,
        "redis_used_memory_bytes": used_mem,
    }


def run_one_combo(rule_count, qps, duration, rule_ids):
    """跑一组 (rule_count, qps) 组合"""
    print("\n━━━ rule_count={} qps={} 稳态 {}s ━━━".format(rule_count, qps, duration), flush=True)

    cleanup_exp_data(rule_ids[:rule_count])

    exp_id = "exp-5-5-r{}-q{}".format(rule_count, qps)
    inj = start_injector(exp_id, qps, duration + 60)  # 多跑 60s 确保稳态
    print("[run] 注入器启动 (PID={})".format(inj.pid), flush=True)

    print("[wait] 预热 60s 以进入稳态...", flush=True)
    time.sleep(60)

    samples = []
    t_end = time.time() + duration
    sample_interval = 30
    while time.time() < t_end:
        s = sample_metrics(rule_count, qps)
        samples.append(s)

        # 简要打印
        engine_pods = [p for p in s["pods"] if "engine" in p["pod"]]
        if engine_pods:
            avg_cpu = sum(p["cpu_milli"] for p in engine_pods) / len(engine_pods)
            avg_mem = sum(p["mem_mi"] for p in engine_pods) / len(engine_pods)
            print("  [sample] engine: cpu={:.0f}m mem={:.0f}Mi  redis_mem={:.1f}MB".format(
                avg_cpu, avg_mem, s["redis_used_memory_bytes"] / 1024 / 1024))

        time.sleep(sample_interval)

    # 停注入器
    try:
        inj.terminate()
        inj.wait(timeout=10)
    except Exception:
        inj.kill()

    return samples


def main():
    ap = argparse.ArgumentParser(description="实验 5.5：资源消耗")
    ap.add_argument("--rule-count", type=int, nargs="*", default=[50, 100, 200])
    ap.add_argument("--qps", type=int, nargs="*", default=[100, 1000])
    ap.add_argument("--duration", type=int, default=600,
                    help="稳态采样持续秒数（默认 10min）")
    ap.add_argument("--no-clean-loki", action="store_true")
    ap.add_argument("--keep-rules", action="store_true")
    args = ap.parse_args()

    disabled = prepare_experiment(clean_loki=not args.no_clean_loki)

    # 创建最大数量的规则（其他组合取前 N 条）
    max_count = max(args.rule_count)
    all_rule_ids = create_rules_batch(max_count)

    print("[wait] 等待 Engine 加载规则（65s）...", flush=True)
    time.sleep(65)

    all_samples = []
    try:
        for rc in args.rule_count:
            for qps in args.qps:
                samples = run_one_combo(rc, qps, args.duration, all_rule_ids)
                all_samples.extend(samples)
    finally:
        # 写原始采样 CSV
        raw_path = RESULTS_DIR / "resource_raw.csv"
        with open(str(raw_path), "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["ts", "exp_id", "rule_count", "qps", "pod",
                        "cpu_milli", "mem_mi", "redis_used_memory_mb"])
            for s in all_samples:
                exp_id = "exp-5-5-r{}-q{}".format(s["rule_count"], s["qps"])
                for p in s["pods"]:
                    w.writerow([
                        s["ts"], exp_id, s["rule_count"], s["qps"], p["pod"],
                        p["cpu_milli"], p["mem_mi"],
                        round(s["redis_used_memory_bytes"] / 1024 / 1024, 2),
                    ])

        # 写汇总 CSV（按 rule_count × qps × component 聚合）
        from collections import defaultdict
        agg = defaultdict(lambda: {"cpu": [], "mem": [], "redis": []})
        for s in all_samples:
            key_prefix = (s["rule_count"], s["qps"])
            for p in s["pods"]:
                # 识别组件类型
                pod = p["pod"]
                if "engine" in pod:
                    comp = "engine"
                elif "api" in pod:
                    comp = "api"
                elif "redis" in pod:
                    comp = "redis"
                elif "postgres" in pod or "postgresql" in pod:
                    comp = "postgresql"
                elif "loki" in pod:
                    comp = "loki"
                else:
                    comp = pod.split("-")[1] if "-" in pod else pod
                key = key_prefix + (comp,)
                agg[key]["cpu"].append(p["cpu_milli"])
                agg[key]["mem"].append(p["mem_mi"])
            # Redis 内存单独记录（全局，不区分 pod）
            key_redis = key_prefix + ("redis_mem",)
            agg[key_redis]["redis"].append(
                s["redis_used_memory_bytes"] / 1024 / 1024)

        summary_path = RESULTS_DIR / "resource_summary.csv"
        with open(str(summary_path), "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["rule_count", "qps", "component",
                        "cpu_avg_m", "cpu_max_m",
                        "mem_avg_mi", "mem_max_mi",
                        "samples", "exp_id"])
            for (rc, qps, comp), data in sorted(agg.items()):
                exp_id = "exp-5-5-r{}-q{}".format(rc, qps)
                cpus = data["cpu"]
                mems = data["mem"]
                if cpus:
                    w.writerow([
                        rc, qps, comp,
                        round(sum(cpus) / len(cpus)),
                        max(cpus),
                        round(sum(mems) / len(mems)) if mems else 0,
                        max(mems) if mems else 0,
                        len(cpus),
                        exp_id
                    ])

        print("\n[done] 原始 CSV: {}".format(raw_path), flush=True)
        print("[done] 汇总 CSV: {}".format(summary_path), flush=True)

        teardown_experiment(disabled, delete_exp_rules=not args.keep_rules)


if __name__ == "__main__":
    main()
