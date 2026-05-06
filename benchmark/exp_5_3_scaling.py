#!/usr/bin/env python3
"""
实验 5.3：水平扩展性
- 变量：Engine replicas (1/2/3)
- 固定：100 条实验规则、QPS=1000、BGL 数据集、eval_interval=30s
- 测量：单轮评估耗时（elapsed_seconds）、每 Worker 规则分配数、总吞吐
- 输出：benchmark/results/exp_5_3_scaling.csv

用法：
  python3 benchmark/exp_5_3_scaling.py              # 全部跑
  python3 benchmark/exp_5_3_scaling.py --replicas 1 # 只跑 replicas=1
  python3 benchmark/exp_5_3_scaling.py --rule-count 50
"""

import argparse
import csv
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lib.experiment_utils import (
    prepare_experiment, teardown_experiment,
    create_exp_rule, cleanup_exp_data,
    scale_engine, get_engine_pods,
    LOKI_URL, run,
)

RESULTS_DIR = Path(__file__).parent / "results"
RESULTS_DIR.mkdir(exist_ok=True)


def create_rules_batch(count):
    """批量创建 count 条实验规则（threshold 类型）"""
    print("[rules] 批量创建 {} 条规则...".format(count), flush=True)
    rule_ids = []
    for i in range(count):
        rid = create_exp_rule(
            suffix="5-3-{:04d}".format(i),
            rule_type="threshold",
            match_pattern="ERROR",
            window_seconds=60,
            threshold=100000,  # 故意设高，不要触发告警，只测评估开销
            cooldown=300,
        )
        if rid:
            rule_ids.append(rid)
        if (i + 1) % 20 == 0:
            print("  [rules] 已创建 {}/{}".format(i + 1, count), flush=True)
    print("[rules] 创建完成 {} 条".format(len(rule_ids)), flush=True)
    return rule_ids


def start_injector_background(exp_id, qps, duration_s):
    """后台启动注入器（注入 duration_s 秒）"""
    line_count = qps * duration_s
    cmd = [
        "python3", "benchmark/log_injector.py",
        "--dataset", "BGL",
        "--start-line", "0",
        "--line-count", str(line_count),
        "--qps", str(qps),
        "--exp-id", exp_id,
        "--rule-type", "threshold",
        "--inject-keyword", "ERROR",
        "--namespace", "demo",
        "--pod", "exp53-pod",
        "--eval-interval", "30",
        "--loki-url", LOKI_URL,
    ]
    return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def collect_engine_metrics(sample_duration_s):
    """
    在 sample_duration_s 秒内，采样各 Engine Pod 的 Cycle 日志
    返回 {pod_name: [(elapsed_s, rule_count), ...]}
    """
    pods = get_engine_pods()
    metrics = {pod: [] for pod in pods}
    print("[collect] 开始采样 {} 个 Pod 的 {}s 评估日志".format(len(pods), sample_duration_s), flush=True)

    # 记录采样窗口的起点
    start_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    time.sleep(sample_duration_s)

    # kubectl logs --since=Xs 拉取窗口内日志
    for pod in pods:
        r = run(["kubectl", "logs", "-n", "logsentinel", pod,
                 "--since={}s".format(sample_duration_s + 5)], timeout=30)
        if r.returncode != 0:
            continue
        for line in r.stdout.splitlines():
            if "Engine cycle completed" not in line and "Cycle sharding result" not in line:
                continue
            try:
                # 日志是 JSON
                if line.startswith("{"):
                    data = json.loads(line)
                    if data.get("event") == "Engine cycle completed":
                        metrics[pod].append({
                            "elapsed_s": data.get("elapsed_seconds"),
                            "rule_count": data.get("rule_count"),
                            "event": "cycle_completed",
                        })
                    elif data.get("event") == "Cycle sharding result":
                        metrics[pod].append({
                            "alive_workers": data.get("alive_workers"),
                            "my_rules": data.get("my_rules"),
                            "total_rules": data.get("total_rules"),
                            "event": "sharding",
                        })
            except Exception:
                pass
    return metrics


def analyze_replicas(replicas, metrics, rule_count):
    """汇总指标"""
    all_cycles = []
    sharding_summary = {}
    for pod, records in metrics.items():
        for r in records:
            if r["event"] == "cycle_completed":
                all_cycles.append((pod, r["elapsed_s"], r["rule_count"]))
            elif r["event"] == "sharding":
                sharding_summary[pod] = r

    # 每 Pod 规则分配数
    pod_rule_counts = {pod: s.get("my_rules", 0) for pod, s in sharding_summary.items()}
    # 每 Pod 平均 elapsed
    pod_elapsed = {}
    for pod, elapsed, _ in all_cycles:
        pod_elapsed.setdefault(pod, []).append(elapsed)

    result = {
        "replicas": replicas,
        "total_rule_count": rule_count,
        "pods": len(pod_rule_counts),
        "pod_rule_counts": pod_rule_counts,
        "avg_elapsed_per_pod": {p: sum(v) / len(v) if v else 0
                                 for p, v in pod_elapsed.items()},
        "total_cycles": len(all_cycles),
        "cycle_per_pod": {p: len(v) for p, v in pod_elapsed.items()},
    }

    # 分配均匀度（最大-最小）/ 平均
    counts = list(pod_rule_counts.values())
    if counts:
        avg = sum(counts) / len(counts)
        result["balance_stddev"] = round((max(counts) - min(counts)) / avg if avg else 0, 3)

    return result


def main():
    ap = argparse.ArgumentParser(description="实验 5.3：水平扩展性")
    ap.add_argument("--replicas", type=int, nargs="*", default=[1, 2, 3])
    ap.add_argument("--rule-count", type=int, default=100)
    ap.add_argument("--qps", type=int, default=1000)
    ap.add_argument("--inject-duration", type=int, default=60,
                    help="注入持续秒数（需 >= 2 个评估周期）")
    ap.add_argument("--sample-duration", type=int, default=90,
                    help="采样评估日志的窗口（秒），一般 3 个评估周期")
    ap.add_argument("--no-clean-loki", action="store_true")
    ap.add_argument("--keep-rules", action="store_true")
    args = ap.parse_args()

    disabled = prepare_experiment(clean_loki=not args.no_clean_loki)

    # 创建批量规则（只创建一次，所有 replicas 复用）
    rule_ids = create_rules_batch(args.rule_count)

    results = []
    try:
        for replicas in args.replicas:
            print("\n━━━ replicas={} ━━━".format(replicas), flush=True)

            # 清理规则关联数据
            cleanup_exp_data(rule_ids)

            # 调整 engine 副本数
            if not scale_engine(replicas):
                print("[error] scale 失败，跳过", file=sys.stderr, flush=True)
                continue

            # 等待 Engine 重新加载规则 + 分片稳定
            print("[wait] 等待 Engine 分片稳定（65s）...", flush=True)
            time.sleep(65)

            # 启动后台注入
            exp_id = "exp-5-3-r{}".format(replicas)
            injector = start_injector_background(exp_id, args.qps, args.inject_duration)
            print("[run] 注入器已启动 (QPS={}, duration={}s, flush=True)".format(
                args.qps, args.inject_duration))

            # 等注入稳定后采样
            time.sleep(10)
            metrics = collect_engine_metrics(args.sample_duration)

            # 等注入完成
            try:
                injector.wait(timeout=60)
            except subprocess.TimeoutExpired:
                injector.kill()

            # 分析
            result = analyze_replicas(replicas, metrics, args.rule_count)
            results.append(result)
            print("[result] replicas={} total_rules={} pods={} balance_stddev={}".format(
                result["replicas"], result["total_rule_count"],
                result["pods"], result.get("balance_stddev", "-")))
            for pod, cnt in result["pod_rule_counts"].items():
                avg_el = result["avg_elapsed_per_pod"].get(pod, 0)
                print("    {} my_rules={} avg_elapsed={:.3f}s cycles={}".format(
                    pod, cnt, avg_el, result["cycle_per_pod"].get(pod, 0)))
    finally:
        # 恢复 engine 到 3 副本（原始状态）
        print("\n[cleanup] 恢复 engine 副本数到 3...", flush=True)
        scale_engine(3)

        # 写结果 CSV
        csv_path = RESULTS_DIR / "exp_5_3_scaling.csv"
        with open(csv_path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["replicas", "total_rules", "pods", "balance_stddev",
                        "pod_name", "my_rules", "avg_elapsed_s", "cycles"])
            for r in results:
                for pod, cnt in r["pod_rule_counts"].items():
                    w.writerow([
                        r["replicas"], r["total_rule_count"], r["pods"],
                        r.get("balance_stddev", ""), pod, cnt,
                        round(r["avg_elapsed_per_pod"].get(pod, 0), 4),
                        r["cycle_per_pod"].get(pod, 0),
                    ])
        print("[done] 结果: {}".format(csv_path), flush=True)

        teardown_experiment(disabled, delete_exp_rules=not args.keep_rules)


if __name__ == "__main__":
    main()
