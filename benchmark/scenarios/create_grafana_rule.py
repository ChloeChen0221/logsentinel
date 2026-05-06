#!/usr/bin/env python3
"""
在 Grafana Alerting 创建与 LogSentinel C2 等价的阈值规则
规则语义：5 分钟内同一 namespace/pod 下 ERROR 日志数 >= 10
LogQL: sum by (namespace, pod) (count_over_time({namespace="demo"} |= "ERROR" [5m])) >= 10

用法：
  python3 benchmark/scenarios/create_grafana_rule.py
"""

import argparse
import json
import sys
import urllib.request
import urllib.error
import base64


LOKI_UID_DEFAULT = "P8E80F9AEF21F6940"
FOLDER_UID = "ls-compare"


def http_req(url: str, method: str, payload=None, user="admin", password="admin"):
    data = json.dumps(payload).encode() if payload else None
    auth = base64.b64encode("{}:{}".format(user, password).encode()).decode()
    req = urllib.request.Request(
        url, data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": "Basic {}".format(auth),
        },
        method=method
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read()
            return resp.status, json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        return e.code, body
    except Exception as e:
        return 0, str(e)


def build_alert_rule(datasource_uid: str) -> dict:
    """构造 Grafana Alert Rule payload（对应 C2 阈值规则）"""
    return {
        "uid": "ls-c2-equivalent",
        "title": "LS-C2-equivalent-ERROR-threshold",
        "ruleGroup": "logsentinel-compare",
        "folderUID": FOLDER_UID,
        "condition": "C",
        "noDataState": "OK",
        "execErrState": "Error",
        "for": "0s",
        "annotations": {
            "description": "等价 LogSentinel C2：5min 内同一 namespace/pod 下 ERROR >= 10",
        },
        "labels": {
            "system": "grafana",
            "scenario": "C2-equivalent",
        },
        "data": [
            {
                "refId": "A",
                "queryType": "range",
                "relativeTimeRange": {"from": 300, "to": 0},
                "datasourceUid": datasource_uid,
                "model": {
                    "expr": 'sum by (namespace, pod) (count_over_time({namespace="demo"} |= "ERROR" [5m]))',
                    "intervalMs": 1000,
                    "maxDataPoints": 43200,
                    "refId": "A",
                    "queryType": "range",
                },
            },
            {
                "refId": "B",
                "queryType": "",
                "relativeTimeRange": {"from": 0, "to": 0},
                "datasourceUid": "__expr__",
                "model": {
                    "type": "reduce",
                    "refId": "B",
                    "expression": "A",
                    "reducer": "last",
                    "datasource": {"type": "__expr__", "uid": "__expr__"},
                },
            },
            {
                "refId": "C",
                "queryType": "",
                "relativeTimeRange": {"from": 0, "to": 0},
                "datasourceUid": "__expr__",
                "model": {
                    "type": "threshold",
                    "refId": "C",
                    "expression": "B",
                    "conditions": [{
                        "evaluator": {"type": "gt", "params": [10]},
                        "operator": {"type": "and"},
                        "query": {"params": ["B"]},
                        "reducer": {"type": "last", "params": []},
                        "type": "query"
                    }],
                    "datasource": {"type": "__expr__", "uid": "__expr__"},
                },
            },
        ],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--grafana-url", default="http://21.6.224.183:30882")
    ap.add_argument("--datasource-uid", default=LOKI_UID_DEFAULT)
    args = ap.parse_args()

    rule = build_alert_rule(args.datasource_uid)

    # Grafana 10.4 provisioning API：直接 POST 单条规则
    rule_url = "{}/api/v1/provisioning/alert-rules".format(args.grafana_url)

    # 检查是否已存在（按 uid）
    check_url = "{}/{}".format(rule_url, rule["uid"])
    status, _ = http_req(check_url, "GET")
    if status == 200:
        # 已存在则 PUT 更新
        status, resp = http_req(check_url, "PUT", rule)
        action = "更新"
    else:
        status, resp = http_req(rule_url, "POST", rule)
        action = "创建"

    if status in (200, 201, 202):
        print("[ok] Grafana 告警规则{}成功: {}".format(action, rule["title"]))
        print("     UID       : {}".format(rule["uid"]))
        print("     Folder    : {}".format(FOLDER_UID))
        print("     LogQL     : {}".format(rule["data"][0]["model"]["expr"]))
        print("     Threshold : > 10")
        print("     Eval      : 30s (通过 rule group)")

        # 将 rule group 的评估间隔设为 30s
        group_url = "{}/api/v1/provisioning/folder/{}/rule-groups/logsentinel-compare".format(
            args.grafana_url, FOLDER_UID)
        status2, resp2 = http_req(group_url, "PUT", {
            "title": "logsentinel-compare",
            "folderUid": FOLDER_UID,
            "interval": "30s",
        })
        if status2 in (200, 201, 202):
            print("[ok] Rule group interval 设置为 30s")
        else:
            print("[warn] Rule group interval 设置失败 status={}: {}".format(status2, resp2))
    else:
        print("[error] {}失败 status={}: {}".format(action, status, resp), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
