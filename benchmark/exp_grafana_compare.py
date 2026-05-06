#!/usr/bin/env python3
"""
实验 5：Grafana Alerting 等价阈值规则延迟对比（简化版）

设计原则：
- 不在 trial 间清 Loki（避免 Engine last_query_time 重置问题）
- LogSentinel 规则: window=60s, threshold=10
- Grafana 规则: count_over_time [1m] >= 10（等价，1分钟窗口）
- 每次注入 QPS=20（每秒20条），持续 3s（共60条），确保 1 分钟内远超 10 条
- 延迟 = min(push_ack_ts_ns) -> alert.created_at / Grafana firing activeAt
- 注入完成后等 90s（3个评估周期）再统计
- 3 次重复，每次间隔 300s（确保 Grafana [1m] 窗口清空）

输出：benchmark/results/grafana_compare_summary.csv
      benchmark/results/grafana_compare_notes.md
"""

import base64
import csv
import datetime
import json
import subprocess
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lib.experiment_utils import (
    prepare_experiment, teardown_experiment,
    cleanup_exp_data, create_exp_rule, delete_rule,
    LOKI_URL, API_URL, run,
)

GRAFANA_URL = "http://21.6.224.183:30882"
RESULTS_DIR = Path(__file__).parent / "results"
RESULTS_DIR.mkdir(exist_ok=True)

LS_RULE_ID = None


def time_ns():
    return int(time.time() * 1e9)


def grafana_get(path):
    auth = base64.b64encode(b"admin:admin").decode()
    req = urllib.request.Request(
        "{}{}".format(GRAFANA_URL, path),
        headers={"Authorization": "Basic {}".format(auth)},
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


def create_or_update_grafana_rule():
    """创建 Grafana 等价规则（window=1m, threshold=10）"""
    auth = base64.b64encode(b"admin:admin").decode()
    rule = {
        "uid": "ls-compare-v2",
        "title": "LS-Compare-threshold-1m",
        "ruleGroup": "ls-compare-group",
        "folderUID": "ls-compare",
        "condition": "C",
        "noDataState": "OK",
        "execErrState": "Error",
        "for": "0s",
        "data": [
            {
                "refId": "A",
                "queryType": "range",
                "relativeTimeRange": {"from": 60, "to": 0},
                "datasourceUid": "P8E80F9AEF21F6940",
                "model": {
                    "expr": 'sum by (namespace, pod) (count_over_time({namespace="demo"} |= "ERROR" [1m]))',
                    "intervalMs": 1000, "maxDataPoints": 43200,
                    "refId": "A", "queryType": "range",
                },
            },
            {
                "refId": "B", "queryType": "",
                "relativeTimeRange": {"from": 0, "to": 0},
                "datasourceUid": "__expr__",
                "model": {"type": "reduce", "refId": "B", "expression": "A",
                          "reducer": "last",
                          "datasource": {"type": "__expr__", "uid": "__expr__"}},
            },
            {
                "refId": "C", "queryType": "",
                "relativeTimeRange": {"from": 0, "to": 0},
                "datasourceUid": "__expr__",
                "model": {
                    "type": "threshold", "refId": "C", "expression": "B",
                    "conditions": [{"evaluator": {"type": "gt", "params": [10]},
                                   "operator": {"type": "and"},
                                   "query": {"params": ["B"]},
                                   "reducer": {"type": "last", "params": []},
                                   "type": "query"}],
                    "datasource": {"type": "__expr__", "uid": "__expr__"},
                },
            },
        ],
    }
    data = json.dumps(rule).encode()
    # 先尝试 PUT（更新），再 POST（创建）
    for method, url in [
        ("PUT", "{}/api/v1/provisioning/alert-rules/ls-compare-v2".format(GRAFANA_URL)),
        ("POST", "{}/api/v1/provisioning/alert-rules".format(GRAFANA_URL)),
    ]:
        try:
            req = urllib.request.Request(
                url, data=data,
                headers={"Authorization": "Basic {}".format(auth),
                         "Content-Type": "application/json"},
                method=method
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                print("[grafana] 规则已{}（uid=ls-compare-v2，window=1m，threshold=10）".format(
                    "更新" if method == "PUT" else "创建"), flush=True)
                return True
        except urllib.error.HTTPError as e:
            if method == "PUT" and e.code == 404:
                continue
            print("[grafana warn] {} {} {}".format(method, e.code, e.read().decode()), flush=True)
            if method == "POST":
                return False
    return False


def inject_logs_sync(exp_id, qps, count):
    """同步注入指定数量的日志，返回 (min_push_ack_ns, max_push_ack_ns)"""
    cmd = [
        "python3", "benchmark/log_injector.py",
        "--dataset", "HDFS_v1", "--start-line", "0",
        "--line-count", str(count), "--qps", str(qps),
        "--exp-id", exp_id,
        "--rule-type", "threshold",
        "--inject-keyword", "ERROR",
        "--namespace", "demo", "--pod", "compare-pod",
        "--eval-interval", "30",
        "--loki-url", LOKI_URL,
    ]
    r = run(cmd, timeout=count // qps + 60)
    if r.returncode != 0:
        print("[error] 注入失败: {}".format(r.stderr), flush=True)
        return None, None
    jsonl = RESULTS_DIR / "inject_{}.jsonl".format(exp_id)
    if not jsonl.exists():
        return None, None
    acks = []
    with open(str(jsonl)) as f:
        for line in f:
            try:
                acks.append(json.loads(line)["push_ack_ts_ns"])
            except Exception:
                pass
    if not acks:
        return None, None
    return min(acks), max(acks)


def get_ls_alert_ts(rule_id, after_ts_ns):
    """查 LogSentinel 告警创建时间（UTC ns），返回最新的"""
    req = urllib.request.Request("{}/api/alerts".format(API_URL))
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
    except Exception:
        return None
    if not isinstance(data, list):
        data = data.get("items", [])
    alerts = [a for a in data if a.get("rule_id") == rule_id]
    if not alerts:
        return None
    for a in sorted(alerts, key=lambda x: x.get("created_at", ""), reverse=True):
        try:
            s = a["created_at"].split(".")[0].rstrip("Z")
            dt = datetime.datetime.strptime(s, "%Y-%m-%dT%H:%M:%S")
            ts = int(dt.replace(tzinfo=datetime.timezone.utc).timestamp() * 1e9)
            # 告警时间必须在第一批注入之后
            if ts >= after_ts_ns:
                return ts
        except Exception:
            pass
    return None


def get_grafana_firing_ts(after_ts_ns):
    """轮询 Grafana，返回 firing activeAt（UTC ns），或 None"""
    d = grafana_get("/api/prometheus/grafana/api/v1/rules")
    if not d:
        return None
    for group in d.get("data", {}).get("groups", []):
        for rule in group.get("rules", []):
            if "Compare" in rule.get("name", "") or "compare" in rule.get("name", ""):
                if rule.get("state") == "firing":
                    for alert in rule.get("alerts", []):
                        active_at = alert.get("activeAt", "")
                        if active_at:
                            try:
                                s = active_at.split(".")[0].rstrip("Z")
                                dt = datetime.datetime.strptime(s, "%Y-%m-%dT%H:%M:%S")
                                ts = int(dt.replace(tzinfo=datetime.timezone.utc).timestamp() * 1e9)
                                if ts >= after_ts_ns:
                                    return ts
                            except Exception:
                                pass
    return None


def run_one_trial(trial, qps, inject_count):
    exp_id = "exp-grafana-compare-{:02d}".format(trial)
    print("\n  [trial {}] exp_id={} 注入{}条".format(trial, exp_id, inject_count), flush=True)

    # 清理 LS 历史告警（不清 Loki）
    cleanup_exp_data([LS_RULE_ID])

    # 记录注入开始时间（UTC）
    print("  [inject] 开始注入 {} 条（QPS={}）...".format(inject_count, qps), flush=True)
    min_ack, max_ack = inject_logs_sync(exp_id, qps, inject_count)
    if not min_ack:
        return None, None, "inject_failed"

    inject_start_ns = min_ack  # 第一批 push ack 作为参考时间
    print("  [inject] 完成，首批ack={} UTC".format(
        datetime.datetime.utcfromtimestamp(min_ack / 1e9).strftime("%H:%M:%S")), flush=True)

    # 等待 3 个评估周期（90s）
    print("  [wait] 等待 Engine 评估（90s）...", flush=True)
    time.sleep(90)

    # 采集 LS 延迟
    ls_ts = get_ls_alert_ts(LS_RULE_ID, inject_start_ns)
    ls_ms = round((ls_ts - inject_start_ns) / 1e6) if ls_ts else None

    # 采集 Grafana firing 时间
    grafana_ts = get_grafana_firing_ts(inject_start_ns)
    grafana_ms = round((grafana_ts - inject_start_ns) / 1e6) if grafana_ts else None

    print("  [result] LS={}ms  Grafana={}ms".format(ls_ms, grafana_ms), flush=True)

    # trial 间等待（让 Grafana 1min 窗口清空，避免下轮 count_over_time 受上轮影响）
    if trial < 3:
        print("  [wait] 等待 90s 让 Grafana 窗口清空...", flush=True)
        time.sleep(90)

    return ls_ms, grafana_ms, ""


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--qps", type=int, default=20)
    ap.add_argument("--inject-count", type=int, default=100,
                    help="每次注入条数（默认100，QPS=20注入5s，确保1min内>10条）")
    ap.add_argument("--repeat", type=int, default=3)
    ap.add_argument("--no-clean-loki", action="store_true")
    args = ap.parse_args()

    disabled = prepare_experiment(clean_loki=not args.no_clean_loki)

    # 创建/更新 Grafana 规则（1min窗口）
    create_or_update_grafana_rule()

    # 创建 LogSentinel 对比规则（window=60s, threshold=10）
    global LS_RULE_ID
    LS_RULE_ID = create_exp_rule(
        suffix='compare-ls',
        rule_type='threshold',
        match_pattern='ERROR',
        window_seconds=60,
        threshold=10,
        cooldown=0,
    )
    print("[rules] LogSentinel 对比规则 id={} (window=60s, threshold=10)".format(
        LS_RULE_ID), flush=True)

    print("[wait] 等待 Engine 加载规则（65s）...", flush=True)
    time.sleep(65)

    rows = []
    try:
        for trial in range(1, args.repeat + 1):
            ls_ms, grafana_ms, notes = run_one_trial(trial, args.qps, args.inject_count)
            rows.append({
                "trial": trial,
                "ls_ms": ls_ms,
                "grafana_ms": grafana_ms,
                "notes": notes,
            })
    finally:
        # 写 CSV
        csv_path = RESULTS_DIR / "grafana_compare_summary.csv"
        with open(str(csv_path), "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["system", "qps", "eval_interval", "run_id", "exp_id",
                        "p50_ms", "p95_ms", "p99_ms", "avg_ms", "max_ms",
                        "firing_time_source", "notes"])
            for row in rows:
                eid = "exp-grafana-compare-{:02d}".format(row["trial"])
                for system, key in [("LogSentinel", "ls_ms"), ("Grafana", "grafana_ms")]:
                    val = row[key]
                    w.writerow([
                        system, args.qps, 30, row["trial"], eid,
                        val, val, val, val, val,
                        "prometheus_rules_api",
                        row["notes"],
                    ])
        print("[done] CSV: {}".format(csv_path), flush=True)

        # 汇总
        ls_vals = [r["ls_ms"] for r in rows if r["ls_ms"] is not None]
        gr_vals = [r["grafana_ms"] for r in rows if r["grafana_ms"] is not None]

        print("\n=== 延迟汇总 ===", flush=True)
        if ls_vals:
            ls_vals.sort()
            print("  LogSentinel (n={}): P50={}ms avg={:.0f}ms".format(
                len(ls_vals), ls_vals[len(ls_vals)//2], sum(ls_vals)/len(ls_vals)), flush=True)
        if gr_vals:
            gr_vals.sort()
            print("  Grafana     (n={}): P50={}ms avg={:.0f}ms".format(
                len(gr_vals), gr_vals[len(gr_vals)//2], sum(gr_vals)/len(gr_vals)), flush=True)

        if LS_RULE_ID:
            delete_rule(LS_RULE_ID)

        teardown_experiment(disabled, delete_exp_rules=False)


if __name__ == "__main__":
    main()
