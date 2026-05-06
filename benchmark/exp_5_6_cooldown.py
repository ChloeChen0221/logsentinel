#!/usr/bin/env python3
"""
实验 5.6：冷却与去重消融
- 变量：cooldown = 0 / 60 / 300（秒）
- 固定：单规则 threshold window=60s threshold=5，QPS=10，持续 10min
- 测量：raw_matches（原始匹配日志数）、alert_count、notification_count
- 输出：压降比例 = 1 - actual_notifications / raw_matches

用法：
  python3 benchmark/exp_5_6_cooldown.py                    # 全部跑
  python3 benchmark/exp_5_6_cooldown.py --cooldown 60      # 只跑 cooldown=60
  python3 benchmark/exp_5_6_cooldown.py --duration 300     # 5 分钟（默认 10min）
"""

import argparse
import csv
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lib.experiment_utils import (
    prepare_experiment, teardown_experiment,
    create_exp_rule, cleanup_exp_data, delete_rule,
    psql, LOKI_URL,
)

RESULTS_DIR = Path(__file__).parent / "results"
RESULTS_DIR.mkdir(exist_ok=True)


def start_injector(exp_id, qps, duration_s):
    line_count = qps * duration_s
    cmd = [
        "python3", "benchmark/log_injector.py",
        "--dataset", "HDFS_v1", "--start-line", "0",
        "--line-count", str(line_count), "--qps", str(qps),
        "--exp-id", exp_id, "--rule-type", "threshold",
        "--inject-keyword", "ERROR", "--namespace", "demo",
        "--pod", "exp56-pod", "--loki-url", LOKI_URL,
    ]
    return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def get_stats(rule_id):
    """查询指定规则的告警数、hit_count 总和、通知数"""
    alert_count = psql(
        "SELECT count(*) FROM alerts WHERE rule_id = {};".format(rule_id)).strip() or "0"
    hit_sum = psql(
        "SELECT COALESCE(SUM(hit_count), 0) FROM alerts WHERE rule_id = {};".format(rule_id)).strip() or "0"
    notif_count = psql(
        "SELECT count(*) FROM notifications n JOIN alerts a ON n.alert_id = a.id "
        "WHERE a.rule_id = {};".format(rule_id)).strip() or "0"
    return {
        "alert_count": int(alert_count),
        "total_hit_count": int(hit_sum),
        "notification_count": int(notif_count),
    }


def run_one_cooldown(cooldown, duration, qps, rid, extra_wait=0):
    """跑一组 cooldown 配置（规则已预先创建，传入 rule_id）"""
    print("\n━━━ cooldown={} duration={}s qps={} rule_id={} ━━━".format(
        cooldown, duration, qps, rid), flush=True)

    cleanup_exp_data([rid])

    # 启动注入
    exp_id = "exp-5-6-cd{}".format(cooldown)
    inj = start_injector(exp_id, qps, duration)
    print("[run] 注入器启动，持续 {}s...".format(duration), flush=True)

    # 等待注入 + 3 个评估周期 + 额外等待
    wait_s = duration + 90 + extra_wait
    print("[wait] 等待注入完成 + 评估收敛 + 额外{}s，共 {}s".format(extra_wait, wait_s), flush=True)
    time.sleep(wait_s)

    try:
        inj.terminate()
        inj.wait(timeout=10)
    except Exception:
        inj.kill()

    # 统计
    stats = get_stats(rid)
    stats["rule_id"] = rid
    stats["cooldown_s"] = cooldown
    stats["duration_s"] = duration
    stats["qps"] = qps
    raw_matches = stats["total_hit_count"] if stats["total_hit_count"] > 0 else qps * duration
    stats["raw_matches"] = raw_matches
    stats["injected_lines"] = qps * duration
    stats["reduction_ratio"] = round(
        1 - stats["notification_count"] / raw_matches, 4
    ) if raw_matches > 0 else 0

    print("[result] cooldown={}s:".format(cooldown), flush=True)
    print("  injected_lines    : {}".format(stats["injected_lines"]), flush=True)
    print("  raw_matches       : {} (total_hit_count)".format(stats["raw_matches"]), flush=True)
    print("  alert_count       : {}".format(stats["alert_count"]), flush=True)
    print("  notification_count: {}".format(stats["notification_count"]), flush=True)
    print("  reduction_ratio   : {:.2%}".format(stats["reduction_ratio"]), flush=True)

    return stats


def main():
    ap = argparse.ArgumentParser(description="实验 5.6：冷却与去重消融")
    ap.add_argument("--cooldown", type=int, nargs="*", default=[0, 60, 300])
    ap.add_argument("--duration", type=int, default=600, help="注入持续秒数")
    ap.add_argument("--qps", type=int, default=10, help="注入 QPS（默认每秒 1 条匹配）")
    ap.add_argument("--no-clean-loki", action="store_true")
    args = ap.parse_args()

    disabled = prepare_experiment(clean_loki=not args.no_clean_loki)

    # 一次性预创建所有 cooldown 规则，保持规则列表稳定，避免分片变化
    print("[rules] 预创建所有实验规则...", flush=True)
    rule_map = {}  # cooldown -> rule_id
    for cd in args.cooldown:
        rid = create_exp_rule(
            suffix="5-6-cd{}".format(cd),
            rule_type="threshold",
            match_pattern="ERROR",
            window_seconds=60, threshold=5, cooldown=cd,
        )
        if rid:
            rule_map[cd] = rid
            print("[rules] cooldown={} => rule_id={}".format(cd, rid), flush=True)
        else:
            print("[error] cooldown={} 规则创建失败".format(cd), flush=True)

    # 等待 Engine 加载新规则（2 个周期）
    print("[wait] 等待 Engine 加载规则（65s）...", flush=True)
    time.sleep(65)

    results = []
    try:
        for cd in args.cooldown:
            rid = rule_map.get(cd)
            if not rid:
                continue
            # cooldown=60 额外等 60s，让最后一次 cooldown 窗口确保结束后再统计
            extra = 60 if cd == 60 else 0
            r = run_one_cooldown(cd, args.duration, args.qps, rid, extra_wait=extra)
            if r:
                results.append(r)
    finally:
        # 写 CSV
        csv_path = RESULTS_DIR / "cooldown_summary.csv"
        with open(str(csv_path), "w", newline="") as f:
            w = csv.writer(f)
            w.writerow([
                "cooldown_seconds", "duration_s", "qps", "injected_lines",
                "raw_matches", "alert_count", "notification_count",
                "reduction_ratio", "notes"
            ])
            for r in results:
                w.writerow([
                    r["cooldown_s"], r["duration_s"], r["qps"],
                    r.get("injected_lines", ""),
                    r["raw_matches"],
                    r["alert_count"], r["notification_count"],
                    r["reduction_ratio"], ""
                ])
        print("\n[done] 结果 CSV: {}".format(csv_path), flush=True)

        teardown_experiment(disabled, delete_exp_rules=True)


if __name__ == "__main__":
    main()
