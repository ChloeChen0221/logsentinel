#!/usr/bin/env python3
"""
C2 阈值规则场景验证（window=60s, threshold=10, pattern=OOMKilled）
- 阶段 A：注入 9 条验证不触发
- 阶段 B：再注入 1 条（共 10 条）验证触发
- 阶段 C：3 个 Pod 各注入 10 条验证独立分组

用法：
  python3 benchmark/scenarios/c2_inject.py --phase threshold
  python3 benchmark/scenarios/c2_inject.py --phase multipod
"""

import argparse
import json
import sys
import time
import urllib.request


def push_log(loki_url: str, namespace: str, pod: str, message: str):
    ts_ns = str(int(time.time() * 1e9))
    payload = {
        "streams": [{
            "stream": {
                "namespace": namespace, "pod": pod, "container": "app",
                "job": "{}/{}".format(namespace, pod), "app": "c2-demo",
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


def phase_threshold(loki_url: str):
    """验证阈值边界"""
    pod = "c2-threshold-pod"
    print("[C2-threshold] 阶段 A：注入 9 条 OOMKilled（pod={}）".format(pod))
    for i in range(9):
        push_log(loki_url, "demo", pod, "OOMKilled memory limit exceeded container #{}".format(i))
        time.sleep(0.1)
    print("[C2-threshold] 等待 35s，预期此时应无 C2 告警（未达阈值）...")
    time.sleep(35)

    print("[C2-threshold] 阶段 B：再注入 1 条（共 10 条）")
    push_log(loki_url, "demo", pod, "OOMKilled memory limit exceeded container #9 (trigger)")
    print("[C2-threshold] 等待 35s，预期此时应触发告警...")
    time.sleep(35)
    print("[C2-threshold] 完成，请查询 rule_id=15 验证告警创建")


def phase_multipod(loki_url: str):
    """验证多 Pod 独立分组"""
    print("[C2-multipod] 3 个 Pod 各注入 10 条 OOMKilled")
    for pod in ["c2-pod-a", "c2-pod-b", "c2-pod-c"]:
        for i in range(10):
            push_log(loki_url, "demo", pod, "OOMKilled {} container #{}".format(pod, i))
            time.sleep(0.05)
        print("[C2-multipod] {} 完成 10 条注入".format(pod))
        time.sleep(0.5)
    print("[C2-multipod] 等待 35s...")
    time.sleep(35)
    print("[C2-multipod] 完成，预期 rule_id=15 有 3 条 fingerprint 不同的告警")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", choices=["threshold", "multipod"], required=True)
    ap.add_argument("--loki-url", default="http://10.43.64.140:3100")
    args = ap.parse_args()

    phases = {"threshold": phase_threshold, "multipod": phase_multipod}
    phases[args.phase](args.loki_url)


if __name__ == "__main__":
    main()
