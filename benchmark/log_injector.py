#!/usr/bin/env python3
"""
LogSentinel 实验日志注入工具

功能：
  - 从 Loghub 数据集（HDFS_v1 / BGL）按切片读取日志
  - 时间戳重写到当前时间窗口，保留相对时序
  - 在每条日志前附加 exp_id/line_id（及可选关键词）
  - 以指定 QPS 批量推送到 Loki
  - 记录 inject_ts_ns / push_ack_ts_ns 等元数据到 results/

用法示例：
  python3 benchmark/log_injector.py \
    --dataset HDFS_v1 --start-line 0 --line-count 10000 \
    --qps 500 --exp-id exp001 --rule-type threshold \
    --inject-keyword ERROR \
    --namespace demo --pod demo-app \
    --loki-url http://10.43.64.140:3100 \
    --results-dir benchmark/results
"""

import argparse
import json
import re
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import urllib.request
import urllib.error


# ── 数据集解析 ────────────────────────────────────────────────────────────────

def parse_hdfs_line(line: str) -> Optional[int]:
    """返回 HDFS 日志行的 unix_ts_ms，解析失败返回 None"""
    m = re.match(r'^(\d{6})\s+(\d{6})\s+', line)
    if not m:
        return None
    try:
        dt = datetime.strptime("20{} {}".format(m.group(1), m.group(2)), "%Y%m%d %H%M%S")
        return int(dt.replace(tzinfo=timezone.utc).timestamp() * 1000)
    except ValueError:
        return None


def parse_bgl_line(line: str) -> Optional[int]:
    """返回 BGL 日志行的 unix_ts_ms，解析失败返回 None"""
    parts = line.split(None, 2)
    if len(parts) < 2:
        return None
    try:
        return int(parts[1]) * 1000
    except ValueError:
        return None


PARSERS = {"HDFS_v1": parse_hdfs_line, "BGL": parse_bgl_line}
LOG_FILES = {"HDFS_v1": "HDFS_v1/HDFS.log", "BGL": "BGL/BGL.log"}
LABEL_FILE = "HDFS_v1/preprocessed/anomaly_label.csv"


def load_anomaly_block_ids(data_dir: Path) -> set:
    """读取 HDFS_v1 异常 block ID 集合"""
    label_path = data_dir / LABEL_FILE
    anomaly = set()
    if not label_path.exists():
        return anomaly
    import csv
    with open(str(label_path)) as f:
        for row in csv.DictReader(f):
            if row.get("Label", "").strip() == "Anomaly":
                anomaly.add(row.get("BlockId", "").strip())
    return anomaly


def is_anomaly_line(message: str, anomaly_blocks: set) -> bool:
    """判断一条日志是否包含异常 block ID"""
    if not anomaly_blocks:
        return False
    m = re.search(r'blk_-?\d+', message)
    return bool(m and m.group(0) in anomaly_blocks)


# ── 时间戳重写 ────────────────────────────────────────────────────────────────

def rewrite_timestamps(
    raw_ts_list: List[Optional[int]],
    anchor_offset_s: int = 10,
    compress_window_s: int = 20
) -> List[int]:
    """
    重写时间戳：所有日志的时间戳压缩映射到 [now-anchor_offset_s-compress_window_s, now-anchor_offset_s]。
    这样 Engine 在下一个评估周期（30s）内一定能查到这批日志。

    anchor_offset_s: 最新日志距 now 的偏移秒数（默认 10s，在 Engine 查询窗口内）
    compress_window_s: 日志时间跨度压缩后的秒数（默认 20s）
    """
    valid = [ts for ts in raw_ts_list if ts is not None]
    now_ms = int(time.time() * 1000)
    # 目标窗口：[now - anchor - compress, now - anchor]
    target_end_ms = now_ms - anchor_offset_s * 1000
    target_start_ms = target_end_ms - compress_window_s * 1000

    if not valid:
        return [target_start_ms] * len(raw_ts_list)

    src_start = min(valid)
    src_end = max(valid)
    src_span = src_end - src_start if src_end > src_start else 1

    result = []
    for ts in raw_ts_list:
        if ts is None:
            result.append(target_start_ms)
        else:
            # 线性映射到目标窗口
            ratio = (ts - src_start) / src_span
            new_ts = int(target_start_ms + ratio * compress_window_s * 1000)
            result.append(new_ts)
    return result


# ── Loki 推送 ─────────────────────────────────────────────────────────────────

def time_ns() -> int:
    """Python 3.6 兼容的纳秒时间戳"""
    return int(time.time() * 1e9)


def push_batch(
    values: List[List],
    stream_labels: Dict,
    loki_url: str
) -> Tuple[bool, int]:
    """
    推送一批日志到 Loki。
    返回 (success, push_ack_ts_ns)
    """
    payload = json.dumps({
        "streams": [{"stream": stream_labels, "values": values}]
    }).encode()
    req = urllib.request.Request(
        "{}/loki/api/v1/push".format(loki_url),
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
                ack_ts = time_ns()
                return resp.status == 204, ack_ts
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:200]
        print("[error] Loki push HTTP {}: {}".format(e.code, body), file=sys.stderr)
        return False, time_ns()
    except Exception as e:
        print("[error] Loki push failed: {}".format(e), file=sys.stderr)
        return False, time_ns()


# ── QPS 控制 ──────────────────────────────────────────────────────────────────

class RateLimiter:
    def __init__(self, qps: int, batch_size: int = 100):
        self.interval = batch_size / qps  # 每批次应间隔的秒数
        self.batch_size = batch_size
        self._last = time.monotonic()

    def wait(self):
        now = time.monotonic()
        elapsed = now - self._last
        if elapsed < self.interval:
            time.sleep(self.interval - elapsed)
        self._last = time.monotonic()


# ── 主流程 ────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="LogSentinel 实验日志注入工具")
    ap.add_argument("--dataset", choices=["HDFS_v1", "BGL"], required=True)
    ap.add_argument("--data-dir", default="benchmark/data")
    ap.add_argument("--start-line", type=int, default=0)
    ap.add_argument("--line-count", type=int, default=10000)
    ap.add_argument("--qps", type=int, default=500, help="目标注入速率（条/秒）")
    ap.add_argument("--exp-id", default=None, help="实验 ID，默认自动生成")
    ap.add_argument("--rule-type", default="", help="本次实验对应的规则类型（记录用）")
    ap.add_argument("--eval-interval", type=int, default=30, help="Engine 评估间隔（记录用）")
    ap.add_argument("--inject-keyword", default="", help="在日志前附加的关键词（如 ERROR/OOMKilled）")
    ap.add_argument("--namespace", default="demo")
    ap.add_argument("--pod", default="demo-app")
    ap.add_argument("--container", default="app")
    ap.add_argument("--loki-url", default="http://10.43.64.140:3100")
    ap.add_argument("--results-dir", default="benchmark/results")
    ap.add_argument("--batch-size", type=int, default=100, help="每次 Loki push 的日志条数")
    ap.add_argument("--dry-run", action="store_true", help="不推送，只输出元数据")
    args = ap.parse_args()

    exp_id = args.exp_id or "exp-{}".format(uuid.uuid4().hex[:8])
    data_dir = Path(args.data_dir)
    results_dir = Path(args.results_dir)
    results_dir.mkdir(parents=True, exist_ok=True)

    log_file = data_dir / LOG_FILES[args.dataset]
    if not log_file.exists():
        print("[error] 找不到日志文件: {}".format(log_file), file=sys.stderr)
        sys.exit(1)

    parse_fn = PARSERS[args.dataset]

    # 加载异常标签（HDFS_v1 可选）
    anomaly_blocks = set()
    if args.dataset == "HDFS_v1":
        anomaly_blocks = load_anomaly_block_ids(data_dir)

    print("[info] exp_id={} dataset={} lines={}-{} qps={} keyword='{}'".format(
        exp_id, args.dataset, args.start_line,
        args.start_line + args.line_count - 1, args.qps, args.inject_keyword
    ))

    # 读取切片
    raw_lines = []
    raw_ts = []
    with open(str(log_file), errors="replace") as f:
        for i, line in enumerate(f):
            if i < args.start_line:
                continue
            if i >= args.start_line + args.line_count:
                break
            raw_lines.append(line.rstrip())
            raw_ts.append(parse_fn(line))

    print("[info] 读取 {} 行".format(len(raw_lines)))

    # Loki 时间戳在 push 时动态生成（now-5s），无需预先重写
    # 保留 new_ts 仅用于元数据中的相对时序参考
    new_ts = rewrite_timestamps(raw_ts)

    # 验证时间戳窗口（参考用）
    now_ms = int(time.time() * 1000)
    out_of_window = sum(1 for ts in new_ts if abs(now_ms - ts) > 168 * 3600 * 1000)
    if out_of_window:
        print("[warn] {} 条原始时间戳超出 168h 窗口（Loki push 时将用实时时间戳）".format(out_of_window))
    else:
        print("[info] 将使用实时时间戳（now-5s）推送到 Loki，确保 Engine 查询窗口覆盖 ✓")

    stream_labels = {
        "namespace": args.namespace,
        "pod": args.pod,
        "container": args.container,
        "job": "{}/{}".format(args.namespace, args.pod),
        "app": "loghub-replay",
    }

    # 准备元数据输出文件
    jsonl_path = results_dir / "inject_{}.jsonl".format(exp_id)
    meta_path = results_dir / "inject_{}_meta.json".format(exp_id)

    rate_limiter = RateLimiter(args.qps, args.batch_size)
    records = []
    total_pushed = 0
    failed_batches = 0

    with open(str(jsonl_path), "w") as jsonl_f:
        batch_values = []
        batch_meta = []

        for idx, (msg_raw, ts_ms) in enumerate(zip(raw_lines, new_ts)):
            line_id = args.start_line + idx
            inject_ts_ns = time_ns()

            # 构造注入消息：[keyword] exp_id=X line_id=Y <原始日志>
            parts = []
            if args.inject_keyword:
                parts.append(args.inject_keyword)
            parts.append("exp_id={} line_id={}".format(exp_id, line_id))
            parts.append(msg_raw)
            message = " ".join(parts)

            # Loki 需要纳秒时间戳字符串
            # 注意：这里先用占位符，在批次 push 前更新为实时时间戳
            batch_values.append([None, message])  # ts 在 push 前更新
            batch_meta.append({
                "exp_id": exp_id,
                "line_id": line_id,
                "inject_ts_ns": inject_ts_ns,
                "push_ack_ts_ns": None,  # 批次推送后回填
                "namespace": args.namespace,
                "pod": args.pod,
                "container": args.container,
                "rule_type": args.rule_type,
                "is_anomaly": is_anomaly_line(msg_raw, anomaly_blocks),
                "message": message,
            })

            # 攒够一批或最后一条
            if len(batch_values) >= args.batch_size or idx == len(raw_lines) - 1:
                rate_limiter.wait()

                # 在 push 前把时间戳更新为当前时间 - 5s（确保在 Engine 下次查询窗口内）
                now_ns = time_ns()
                loki_ts_ns = now_ns - 5 * 1_000_000_000  # now - 5s（单位：ns）
                for i, v in enumerate(batch_values):
                    batch_values[i] = [str(loki_ts_ns), v[1]]

                if args.dry_run:
                    ack_ts = time_ns()
                    ok = True
                else:
                    ok, ack_ts = push_batch(batch_values, stream_labels, args.loki_url)

                # 回填 push_ack_ts_ns
                for rec in batch_meta:
                    rec["push_ack_ts_ns"] = ack_ts
                    jsonl_f.write(json.dumps(rec) + "\n")

                if ok:
                    total_pushed += len(batch_values)
                else:
                    failed_batches += 1

                batch_values = []
                batch_meta = []

                # 进度
                if (idx + 1) % 1000 == 0 or idx == len(raw_lines) - 1:
                    print("[info] 进度 {}/{} 已推送 {} 条".format(
                        idx + 1, len(raw_lines), total_pushed))

    # 写实验级元数据
    meta = {
        "exp_id": exp_id,
        "dataset": args.dataset,
        "start_line": args.start_line,
        "line_count": args.line_count,
        "qps": args.qps,
        "rule_type": args.rule_type,
        "eval_interval": args.eval_interval,
        "inject_keyword": args.inject_keyword,
        "namespace": args.namespace,
        "pod": args.pod,
        "container": args.container,
        "loki_url": args.loki_url,
        "total_pushed": total_pushed,
        "failed_batches": failed_batches,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    meta_path.write_text(json.dumps(meta, indent=2))

    print("\n[done] exp_id={} 推送 {} 条，失败批次 {}".format(
        exp_id, total_pushed, failed_batches))
    print("[done] 元数据: {}".format(jsonl_path))
    print("[done] 实验元数据: {}".format(meta_path))


if __name__ == "__main__":
    main()
