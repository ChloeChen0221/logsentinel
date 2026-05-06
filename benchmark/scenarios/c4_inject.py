#!/usr/bin/env python3
"""
C4 否定关联场景验证（POD_RESTARTED 后 120s 内应出现 "startup completed"）
- 阶段 silent：只注入步骤 1，120s 内不注入步骤 2，验证超时告警
- 阶段 normal：注入步骤 1 后 60s 内注入步骤 2，验证不告警

用法：
  python3 benchmark/scenarios/c4_inject.py --phase silent
  python3 benchmark/scenarios/c4_inject.py --phase normal
"""

import argparse
import json
import time
import urllib.request


def push_log(loki_url: str, namespace: str, pod: str, message: str):
    ts_ns = str(int(time.time() * 1e9))
    payload = {
        "streams": [{
            "stream": {
                "namespace": namespace, "pod": pod, "container": "app",
                "job": "{}/{}".format(namespace, pod), "app": "c4-demo",
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


def phase_silent(loki_url: str):
    """静默超时触发告警"""
    pod = "c4-silent-pod"
    print("[C4-silent] 步骤 1: POD_RESTARTED (pod={})".format(pod))
    push_log(loki_url, "demo", pod, "POD_RESTARTED silent test - expecting timeout alert")
    print("[C4-silent] 等待 150s（>120s window），不注入步骤 2...")
    time.sleep(150)
    print("[C4-silent] 等待 35s Engine 评估否定条件...")
    time.sleep(35)
    print("[C4-silent] 完成，预期 rule_id=17 触发 negative 告警")


def phase_normal(loki_url: str):
    """正常启动不触发告警"""
    pod = "c4-normal-pod"
    print("[C4-normal] 步骤 1: POD_RESTARTED (pod={})".format(pod))
    push_log(loki_url, "demo", pod, "POD_RESTARTED normal test")
    print("[C4-normal] 等待 60s（<120s window）后注入步骤 2...")
    time.sleep(60)

    print("[C4-normal] 步骤 2: startup completed")
    push_log(loki_url, "demo", pod, "startup completed normal test")
    print("[C4-normal] 等待 90s 验证无超时告警...")
    time.sleep(90)
    print("[C4-normal] 完成，预期 rule_id=17 不新增告警")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", choices=["silent", "normal"], required=True)
    ap.add_argument("--loki-url", default="http://10.43.64.140:3100")
    args = ap.parse_args()

    phases = {"silent": phase_silent, "normal": phase_normal}
    phases[args.phase](args.loki_url)


if __name__ == "__main__":
    main()
