#!/usr/bin/env python3
"""
C3 正向序列规则场景验证（3 步序列 SERVICE_A_CRASH → SERVICE_B_TIMEOUT → SERVICE_C_503，window=300s）
- 阶段 complete：三步顺序注入，验证触发告警
- 阶段 incomplete：只注入前 2 步，验证不触发
- 阶段 timeout：步骤 1 命中后超过 300s 再注入步骤 2，验证状态重置

用法：
  python3 benchmark/scenarios/c3_inject.py --phase complete
  python3 benchmark/scenarios/c3_inject.py --phase incomplete
  python3 benchmark/scenarios/c3_inject.py --phase timeout
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
                "job": "{}/{}".format(namespace, pod), "app": "c3-demo",
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


def phase_complete(loki_url: str):
    """三步完整序列"""
    print("[C3-complete] 步骤 1: SERVICE_A_CRASH")
    push_log(loki_url, "demo", "service-a", "SERVICE_A_CRASH fatal error service A died")
    print("[C3-complete] 等待 35s Engine 评估步骤 1...")
    time.sleep(35)

    print("[C3-complete] 步骤 2: SERVICE_B_TIMEOUT")
    push_log(loki_url, "demo", "service-b", "SERVICE_B_TIMEOUT connection to service-a timed out")
    print("[C3-complete] 等待 35s Engine 评估步骤 2...")
    time.sleep(35)

    print("[C3-complete] 步骤 3: SERVICE_C_503")
    push_log(loki_url, "demo", "service-c", "SERVICE_C_503 upstream service unavailable")
    print("[C3-complete] 等待 35s Engine 评估步骤 3（最终触发）...")
    time.sleep(35)
    print("[C3-complete] 完成，预期 rule_id=16 创建 1 条 sequence 告警")


def phase_incomplete(loki_url: str):
    """只注入前 2 步，步骤 3 缺失"""
    print("[C3-incomplete] 步骤 1: SERVICE_A_CRASH")
    push_log(loki_url, "demo", "service-a", "SERVICE_A_CRASH (incomplete test)")
    time.sleep(35)

    print("[C3-incomplete] 步骤 2: SERVICE_B_TIMEOUT")
    push_log(loki_url, "demo", "service-b", "SERVICE_B_TIMEOUT (incomplete test)")
    time.sleep(35)

    print("[C3-incomplete] 不注入步骤 3，等待 60s 验证无告警...")
    time.sleep(60)
    print("[C3-incomplete] 完成，预期 rule_id=16 不新增告警（检查 sequence_state 应为 step1 已命中）")


def phase_timeout(loki_url: str):
    """步骤 1 命中后等待超过 window 再注入步骤 2，验证超时重置"""
    print("[C3-timeout] 步骤 1: SERVICE_A_CRASH")
    push_log(loki_url, "demo", "service-a", "SERVICE_A_CRASH (timeout test)")
    print("[C3-timeout] 等待 320s 超过 window=300s（序列状态应超时重置）...")
    time.sleep(320)

    print("[C3-timeout] 现在注入步骤 2，预期不推进（因步骤 1 已失效）")
    push_log(loki_url, "demo", "service-b", "SERVICE_B_TIMEOUT (timeout test)")
    time.sleep(35)
    print("[C3-timeout] 完成，验证 sequence_state 是否重置")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", choices=["complete", "incomplete", "timeout"], required=True)
    ap.add_argument("--loki-url", default="http://10.43.64.140:3100")
    args = ap.parse_args()

    phases = {"complete": phase_complete, "incomplete": phase_incomplete, "timeout": phase_timeout}
    phases[args.phase](args.loki_url)


if __name__ == "__main__":
    main()
