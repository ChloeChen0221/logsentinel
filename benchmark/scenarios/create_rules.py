#!/usr/bin/env python3
"""
创建 C1-C4 四个功能测试场景的规则
- C1 关键词规则（keyword）
- C2 阈值规则（threshold）
- C3 正向序列规则（sequence）
- C4 否定关联规则（sequence + negative）

用法：
  python3 benchmark/scenarios/create_rules.py --api-url http://10.43.17.47:8000
  python3 benchmark/scenarios/create_rules.py --scenario C2   # 只创建 C2
"""

import argparse
import json
import sys
import urllib.request
import urllib.error


SCENARIOS = {
    "C1": {
        "name": "C1-keyword-ERROR",
        "severity": "high",
        "selector_namespace": "demo",
        "match_type": "contains",
        "match_pattern": "ERROR",
        "window_seconds": 0,
        "threshold": 1,
        "group_by": ["namespace", "pod"],
        "cooldown_seconds": 60,
        "rule_type": "keyword",
        "notify_config": [{"type": "console", "name": "console"}],
    },
    "C2": {
        "name": "C2-threshold-OOMKilled",
        "severity": "high",
        "selector_namespace": "demo",
        "match_type": "contains",
        "match_pattern": "OOMKilled",
        "window_seconds": 60,
        "threshold": 10,
        "group_by": ["namespace", "pod"],
        "cooldown_seconds": 60,
        "rule_type": "threshold",
        "notify_config": [{"type": "console", "name": "console"}],
    },
    "C3": {
        "name": "C3-sequence-cascade",
        "severity": "critical",
        "selector_namespace": "demo",
        "match_type": "contains",
        "match_pattern": "SERVICE_A_CRASH",  # step0，整体规则 pattern 用第一步
        "window_seconds": 300,
        "threshold": 1,
        "group_by": ["namespace"],
        "cooldown_seconds": 60,
        "rule_type": "sequence",
        "correlation_type": "sequence",
        "steps": [
            {"step_order": 0, "match_type": "contains",
             "match_pattern": "SERVICE_A_CRASH", "window_seconds": 300, "threshold": 1},
            {"step_order": 1, "match_type": "contains",
             "match_pattern": "SERVICE_B_TIMEOUT", "window_seconds": 300, "threshold": 1},
            {"step_order": 2, "match_type": "contains",
             "match_pattern": "SERVICE_C_503", "window_seconds": 300, "threshold": 1},
        ],
        "notify_config": [{"type": "console", "name": "console"}],
    },
    "C4": {
        "name": "C4-negative-startup",
        "severity": "high",
        "selector_namespace": "demo",
        "match_type": "contains",
        "match_pattern": "POD_RESTARTED",
        "window_seconds": 120,
        "threshold": 1,
        "group_by": ["namespace", "pod"],
        "cooldown_seconds": 60,
        "rule_type": "sequence",
        "correlation_type": "negative",
        "steps": [
            {"step_order": 0, "match_type": "contains",
             "match_pattern": "POD_RESTARTED", "window_seconds": 120, "threshold": 1},
            {"step_order": 1, "match_type": "contains",
             "match_pattern": "startup completed", "window_seconds": 120, "threshold": 1},
        ],
        "notify_config": [{"type": "console", "name": "console"}],
    },
}


def http_post(url: str, payload: dict) -> tuple:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def http_get(url: str):
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception as e:
        return None


def find_rule_by_name(api_url: str, name: str):
    rules = http_get("{}/api/rules".format(api_url)) or []
    for r in rules:
        if r.get("name") == name:
            return r
    return None


def create_scenario(api_url: str, scenario_key: str) -> dict:
    config = SCENARIOS[scenario_key].copy()

    # 检查是否已存在同名规则
    existing = find_rule_by_name(api_url, config["name"])
    if existing:
        print("[skip] {} 已存在，id={}".format(config["name"], existing["id"]))
        return existing

    status, resp = http_post("{}/api/rules".format(api_url), config)
    if status == 200 or status == 201:
        print("[ok] {}: id={} rule_type={} pattern={}".format(
            scenario_key, resp.get("id"), resp.get("rule_type"), resp.get("match_pattern")))
        return resp
    else:
        print("[error] {} 创建失败 status={}: {}".format(scenario_key, status, resp), file=sys.stderr)
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--api-url", default="http://10.43.17.47:8000")
    ap.add_argument("--scenario", choices=list(SCENARIOS.keys()) + ["ALL"], default="ALL")
    args = ap.parse_args()

    keys = list(SCENARIOS.keys()) if args.scenario == "ALL" else [args.scenario]

    created = {}
    for k in keys:
        rule = create_scenario(args.api_url, k)
        if rule:
            created[k] = rule["id"]

    print("\n[done] 已创建/已存在: {}".format(created))


if __name__ == "__main__":
    main()
