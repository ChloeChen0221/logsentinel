#!/usr/bin/env python3
"""
场景 reset 脚本：清理告警、序列状态、通知、窗口计数器
（API 无 DELETE 端点，通过 kubectl exec 直连 PostgreSQL + Redis 清理）

用法：
  python3 benchmark/scenarios/reset.py --scenario C1
  python3 benchmark/scenarios/reset.py --all
"""

import argparse
import subprocess
import sys


def _run(cmd, timeout=20):
    """Python 3.6 兼容的 subprocess.run(capture_output=True)"""
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          universal_newlines=True, timeout=timeout)


SCENARIO_RULES = {"C1": 14, "C2": 15, "C3": 16, "C4": 17}

PG_POD = "logsentinel-postgresql-0"
PG_NS = "logsentinel"
PG_USER = "logsentinel"
PG_DB = "logsentinel"
PG_PASSWORD = "logsentinel"

REDIS_POD = "logsentinel-redis-master-0"
REDIS_NS = "logsentinel"


def psql(sql: str) -> str:
    cmd = [
        "kubectl", "exec", "-n", PG_NS, PG_POD, "--",
        "sh", "-c",
        "PGPASSWORD={} psql -U {} -d {} -tAc \"{}\"".format(
            PG_PASSWORD, PG_USER, PG_DB, sql)
    ]
    try:
        r = _run(cmd, timeout=20)
        if r.returncode != 0:
            print("[psql error] {}".format(r.stderr), file=sys.stderr)
            return ""
        return r.stdout.strip()
    except Exception as e:
        print("[psql exc] {}".format(e), file=sys.stderr)
        return ""


def redis_cmd(args):
    """执行 redis-cli 命令"""
    cmd = ["kubectl", "exec", "-n", REDIS_NS, REDIS_POD, "--", "redis-cli"] + args
    r = _run(cmd, timeout=10)
    if "NOAUTH" in (r.stderr or "") or "NOAUTH" in (r.stdout or ""):
        pwd_cmd = ["kubectl", "get", "secret", "-n", REDIS_NS, "logsentinel-redis",
                   "-o", "jsonpath={.data.redis-password}"]
        p = _run(pwd_cmd, timeout=10)
        pwd_b64 = p.stdout.strip()
        if pwd_b64:
            import base64
            pwd = base64.b64decode(pwd_b64).decode()
            cmd = ["kubectl", "exec", "-n", REDIS_NS, REDIS_POD, "--",
                   "redis-cli", "-a", pwd, "--no-auth-warning"] + args
            r = _run(cmd, timeout=10)
    return r.stdout.strip()


def reset_rule(rule_id: int, scenario: str):
    # 1. 删除 notifications（依赖 alerts 的外键）
    alert_ids = psql("SELECT id FROM alerts WHERE rule_id = {};".format(rule_id))
    if alert_ids:
        ids = ",".join(alert_ids.split("\n"))
        deleted_notif = psql("DELETE FROM notifications WHERE alert_id IN ({}) RETURNING id;".format(ids))
        n_count = len(deleted_notif.split("\n")) if deleted_notif else 0
    else:
        n_count = 0

    # 2. 删除 alerts
    deleted = psql("DELETE FROM alerts WHERE rule_id = {} RETURNING id;".format(rule_id))
    a_count = len(deleted.split("\n")) if deleted else 0

    # 3. C3/C4：清理序列状态（Redis）
    s_count = 0
    if scenario in ("C3", "C4"):
        # 序列状态 key 格式：logsentinel:seq_state:{rule_id}:*
        result = redis_cmd(["--scan", "--pattern",
                            "logsentinel:seq_state:{}:*".format(rule_id)])
        if result:
            keys = result.split("\n")
            s_count = len(keys)
            for k in keys:
                if k:
                    redis_cmd(["DEL", k])

    # 4. 清理窗口计数器 ZSET（如果有）
    result = redis_cmd(["--scan", "--pattern",
                        "logsentinel:window:{}:*".format(rule_id)])
    if result:
        for k in result.split("\n"):
            if k:
                redis_cmd(["DEL", k])

    # 5. 清理冷却标记
    redis_cmd(["DEL", "logsentinel:cooldown:{}".format(rule_id)])

    print("[{}] rule_id={} 删除 alerts={} notifications={} seq_states={}".format(
        scenario, rule_id, a_count, n_count, s_count))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", choices=list(SCENARIO_RULES.keys()))
    ap.add_argument("--rule-id", type=int)
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()

    if args.all:
        for s, rid in SCENARIO_RULES.items():
            reset_rule(rid, s)
    elif args.scenario:
        reset_rule(SCENARIO_RULES[args.scenario], args.scenario)
    elif args.rule_id:
        reset_rule(args.rule_id, "custom")
    else:
        print("[error] 需指定 --scenario / --rule-id / --all")
        sys.exit(1)


if __name__ == "__main__":
    main()
