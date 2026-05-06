#!/usr/bin/env python3
"""
Grafana Alert 状态监听：记录规则从 normal/pending 到 firing 的时间戳
用于对比实验的延迟测量。

Grafana Alert API（10.4）：
  - /api/prometheus/grafana/api/v1/rules
    返回每个规则的 state / lastEvaluation / activeAt
  - /api/alertmanager/grafana/api/v2/alerts
    返回活跃告警（state=firing）及触发时间

用法：
  # 持续监听，捕获 rule_uid 首次变为 firing 的时间
  python3 benchmark/scenarios/grafana_alert_watcher.py \
    --rule-uid ls-c2-equivalent \
    --timeout 600 \
    --output benchmark/results/grafana_firing.json

输出：
  {
    "rule_uid": "ls-c2-equivalent",
    "title": "LS-C2-equivalent-ERROR-threshold",
    "first_firing_ts_ns": <纳秒时间戳>,
    "activeAt": "2026-05-04T07:30:00Z",
    "watch_start_ts_ns": <开始监听时间>
  }
"""

import argparse
import base64
import json
import sys
import time
import urllib.request
import urllib.error


def http_get(url: str, user="admin", password="admin"):
    auth = base64.b64encode("{}:{}".format(user, password).encode()).decode()
    req = urllib.request.Request(
        url,
        headers={"Authorization": "Basic {}".format(auth)},
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, {}
    except Exception as e:
        return 0, {}


def watch_rule(grafana_url: str, rule_uid: str, timeout: int, poll_interval: float = 2.0):
    """轮询 Grafana API，捕获规则首次 firing 时间"""
    watch_start = time.time()
    watch_start_ns = int(watch_start * 1e9)
    rules_url = "{}/api/prometheus/grafana/api/v1/rules".format(grafana_url)

    print("[watcher] 监听 rule_uid={} timeout={}s".format(rule_uid, timeout))

    while time.time() - watch_start < timeout:
        status, d = http_get(rules_url)
        if status != 200:
            time.sleep(poll_interval)
            continue

        groups = d.get("data", {}).get("groups", [])
        for g in groups:
            for r in g.get("rules", []):
                # Grafana alert rules 在 prometheus API 中 uid 在 labels 或 alerts.labels 中
                state = r.get("state", "")
                labels = r.get("labels", {}) or {}
                # uid 可能在 name 或者通过 alerts 子列表查找
                alerts = r.get("alerts", [])

                # 判断是否是我们的规则（按 name 或 title 匹配）
                is_target = (
                    rule_uid in (r.get("name") or "")
                    or rule_uid in (r.get("uid") or "")
                    or any(rule_uid in (a.get("labels", {}).get("__alert_rule_uid__", "") or "") for a in alerts)
                )
                if not is_target:
                    # 尝试匹配所有规则（仅调试用）
                    continue

                if state == "firing":
                    activeAt = None
                    if alerts:
                        activeAt = alerts[0].get("activeAt")
                    firing_ts_ns = int(time.time() * 1e9)
                    return {
                        "rule_uid": rule_uid,
                        "title": r.get("name"),
                        "state": state,
                        "first_firing_ts_ns": firing_ts_ns,
                        "activeAt": activeAt,
                        "watch_start_ts_ns": watch_start_ns,
                        "watch_duration_s": round(time.time() - watch_start, 2),
                    }
                else:
                    print("[watcher] state={} elapsed={:.1f}s".format(
                        state, time.time() - watch_start), end="\r")

        time.sleep(poll_interval)

    return {
        "rule_uid": rule_uid,
        "state": "timeout",
        "watch_start_ts_ns": watch_start_ns,
        "watch_duration_s": timeout,
        "first_firing_ts_ns": None,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--grafana-url", default="http://21.6.224.183:30882")
    ap.add_argument("--rule-uid", required=True, help="Grafana alert rule UID")
    ap.add_argument("--timeout", type=int, default=600)
    ap.add_argument("--poll-interval", type=float, default=2.0)
    ap.add_argument("--output", default="", help="输出 JSON 文件路径")
    args = ap.parse_args()

    result = watch_rule(args.grafana_url, args.rule_uid, args.timeout, args.poll_interval)

    print()
    print("[result]", json.dumps(result, indent=2))

    if args.output:
        with open(args.output, "w") as f:
            json.dump(result, f, indent=2)
        print("[done] 写入 {}".format(args.output))


if __name__ == "__main__":
    main()
