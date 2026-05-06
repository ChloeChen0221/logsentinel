#!/usr/bin/env python3
"""
C1 关键词规则场景验证
- 验证单条 ERROR 日志触发告警
- 验证多 Pod 独立分组（3 个 Pod 各产生 ERROR）
- 验证冷却期 hit_count 递增但不重复通知

用法：
  # 1. 触发单条告警（单 Pod）
  python3 benchmark/scenarios/c1_inject.py --phase single

  # 2. 多 Pod 独立分组验证
  python3 benchmark/scenarios/c1_inject.py --phase multi

  # 3. 冷却期 hit_count 递增验证
  python3 benchmark/scenarios/c1_inject.py --phase cooldown
"""

import argparse
import json
import sys
import time
import urllib.request


def push_log(loki_url: str, namespace: str, pod: str, message: str):
    """推送一条日志到 Loki"""
    ts_ns = str(int(time.time() * 1e9))
    payload = {
        "streams": [{
            "stream": {
                "namespace": namespace,
                "pod": pod,
                "container": "app",
                "job": "{}/{}".format(namespace, pod),
                "app": "c1-demo",
            },
            "values": [[ts_ns, message]]
        }]
    }
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        "{}/loki/api/v1/push".format(loki_url),
        data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.status == 204


def phase_single(loki_url: str):
    """单条 ERROR 触发告警"""
    print("[C1-single] 推送 1 条 ERROR 日志到 demo/demo-app")
    ok = push_log(loki_url, "demo", "demo-app", "ERROR test single-log alert trigger")
    print("[C1-single] push ok={}".format(ok))
    print("[C1-single] 等待 35s 让 Engine 评估（下一个评估周期 ≤30s）...")
    time.sleep(35)
    print("[C1-single] 完成，请查询 alerts 表验证 C1 告警（rule_id=14）是否创建")


def phase_multi(loki_url: str):
    """3 个 Pod 各自产生 ERROR，验证独立分组"""
    print("[C1-multi] 向 3 个 Pod 各推送 1 条 ERROR")
    for pod in ["demo-app-1", "demo-app-2", "demo-app-3"]:
        ok = push_log(loki_url, "demo", pod, "ERROR multi-pod group_by test from {}".format(pod))
        print("[C1-multi] {} push ok={}".format(pod, ok))
        time.sleep(0.5)
    print("[C1-multi] 等待 35s 让 Engine 评估...")
    time.sleep(35)
    print("[C1-multi] 完成，请验证 rule_id=14 应有 3 条 fingerprint 不同的告警")


def phase_cooldown(loki_url: str):
    """冷却期内持续注入：hit_count 递增，通知数不增加"""
    pod = "demo-app-cooldown"
    print("[C1-cooldown] 开始阶段 1：首次触发（pod={}）".format(pod))
    push_log(loki_url, "demo", pod, "ERROR cooldown test first trigger")
    print("[C1-cooldown] 等待 35s 首次告警...")
    time.sleep(35)

    print("[C1-cooldown] 阶段 2：冷却期内持续注入 10 条（cooldown=60s）")
    for i in range(10):
        push_log(loki_url, "demo", pod, "ERROR cooldown continuous hit #{}".format(i))
        time.sleep(2)  # 共 20s，仍在 cooldown 内
    print("[C1-cooldown] 等待 10s Engine 下轮评估...")
    time.sleep(10)

    print("[C1-cooldown] 完成，预期：")
    print("  - alert.hit_count 应递增到约 11（首次1 + 10次）")
    print("  - notifications 表只有 1 条通知（首次触发）")
    print("  - 冷却结束后（60s）再次触发才会产生新通知")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", choices=["single", "multi", "cooldown"], required=True)
    ap.add_argument("--loki-url", default="http://10.43.64.140:3100")
    args = ap.parse_args()

    phases = {"single": phase_single, "multi": phase_multi, "cooldown": phase_cooldown}
    phases[args.phase](args.loki_url)


if __name__ == "__main__":
    main()
