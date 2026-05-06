#!/usr/bin/env python3
"""
Loghub 数据集预处理工具
- 解析 HDFS_v1 / BGL 日志格式
- 时间戳重写到当前时间窗口（保留相对时序）
- 生成 Loki push payload
- 可选：验证推送到 Loki（HTTP 204）
"""

import argparse
import csv
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import urllib.request
import urllib.error

# ── 数据集解析 ───────────────────────────────────────────────────────────────

def parse_hdfs_line(line: str) -> Tuple[Optional[int], str]:
    """解析 HDFS.log 一行，返回 (unix_ts_ms, message)"""
    # 格式: 081109 203518 143 INFO dfs.DataNode: ...
    m = re.match(r'^(\d{6})\s+(\d{6})\s+', line)
    if not m:
        return None, line.strip()
    date_str = m.group(1)  # YYMMDD
    time_str = m.group(2)  # HHMMSS
    try:
        dt = datetime.strptime(f"20{date_str} {time_str}", "%Y%m%d %H%M%S")
        ts_ms = int(dt.replace(tzinfo=timezone.utc).timestamp() * 1000)
        return ts_ms, line.strip()
    except ValueError:
        return None, line.strip()


def parse_bgl_line(line: str) -> Tuple[Optional[int], str]:
    """解析 BGL.log 一行，返回 (unix_ts_ms, message)"""
    # 格式: - 1117838570 2005.06.03 R02-M1-N0-C:J12-U11 2005-06-03-15.42.50.363779 ...
    parts = line.split(None, 5)
    if len(parts) < 2:
        return None, line.strip()
    try:
        ts_ms = int(parts[1]) * 1000
        return ts_ms, line.strip()
    except ValueError:
        return None, line.strip()


PARSERS = {
    "HDFS_v1": parse_hdfs_line,
    "BGL": parse_bgl_line,
}


def load_anomaly_labels(label_file: Path) -> Set[str]:
    """读取 HDFS_v1 anomaly_label.csv，返回异常 BlockId 集合"""
    anomaly_blocks = set()
    try:
        with open(label_file) as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("Label", "").strip() == "Anomaly":
                    anomaly_blocks.add(row.get("BlockId", "").strip())
    except Exception as e:
        print(f"[warn] 无法读取 anomaly label: {e}", file=sys.stderr)
    return anomaly_blocks


# ── 时间戳重写 ───────────────────────────────────────────────────────────────

def rewrite_timestamps(entries: List[Tuple[Optional[int], str]], anchor_offset_s: int = 10, compress_window_s: int = 20) -> List[Tuple[int, str]]:
    """
    将日志时间戳映射到 [now-anchor-compress, now-anchor]，让 Engine 在下一评估周期能查到。
    """
    valid = [(ts, msg) for ts, msg in entries if ts is not None]
    if not valid:
        now_ms = int(time.time() * 1000)
        return [(now_ms - anchor_offset_s * 1000, msg) for _, msg in entries]

    src_ts = [ts for ts, _ in valid]
    src_start, src_end = min(src_ts), max(src_ts)
    src_span = src_end - src_start if src_end > src_start else 1
    now_ms = int(time.time() * 1000)
    target_end_ms = now_ms - anchor_offset_s * 1000
    target_start_ms = target_end_ms - compress_window_s * 1000

    result = []
    for ts, msg in entries:
        if ts is None:
            result.append((target_start_ms, msg))
        else:
            ratio = (ts - src_start) / src_span
            new_ts = int(target_start_ms + ratio * compress_window_s * 1000)
            result.append((new_ts, msg))
    return result


# ── Loki push ────────────────────────────────────────────────────────────────

def build_loki_payload(entries: List[Tuple[int, str]], stream_labels: Dict) -> Dict:
    """构建 Loki push payload"""
    values = [[str(ts * 1_000_000), msg] for ts, msg in entries]  # ms → ns
    return {
        "streams": [{
            "stream": stream_labels,
            "values": values
        }]
    }


def push_to_loki(payload: dict, loki_url: str) -> bool:
    """推送到 Loki，返回是否成功（HTTP 204）"""
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{loki_url}/loki/api/v1/push",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 204
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:200]
        print(f"[error] Loki push HTTP {e.code}: {body}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"[error] Loki push failed: {e}", file=sys.stderr)
        return False


# ── 主流程 ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Loghub 预处理 + Loki push 验证")
    parser.add_argument("--dataset", choices=["HDFS_v1", "BGL"], required=True)
    parser.add_argument("--data-dir", default="benchmark/data", help="数据集根目录")
    parser.add_argument("--start-line", type=int, default=0)
    parser.add_argument("--line-count", type=int, default=100)
    parser.add_argument("--namespace", default="benchmark")
    parser.add_argument("--pod", default="loghub-replay")
    parser.add_argument("--container", default="log")
    parser.add_argument("--loki-url", default="http://10.43.64.140:3100")
    parser.add_argument("--push", action="store_true", help="推送到 Loki 并验证")
    parser.add_argument("--output", help="输出 payload JSON 到文件")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    dataset_dir = data_dir / args.dataset

    # 找日志文件
    if args.dataset == "HDFS_v1":
        log_file = dataset_dir / "HDFS.log"
        label_file = dataset_dir / "preprocessed" / "anomaly_label.csv"
        anomaly_blocks = load_anomaly_labels(label_file)
    else:
        log_file = dataset_dir / "BGL.log"
        anomaly_blocks = set()

    if not log_file.exists():
        print(f"[error] 找不到日志文件: {log_file}", file=sys.stderr)
        sys.exit(1)

    parse_fn = PARSERS[args.dataset]

    # 读取指定切片
    entries_raw = []
    with open(log_file, errors="replace") as f:
        for i, line in enumerate(f):
            if i < args.start_line:
                continue
            if i >= args.start_line + args.line_count:
                break
            ts, msg = parse_fn(line)
            entries_raw.append((ts, msg))

    print(f"[info] 读取 {len(entries_raw)} 行（{args.dataset} line {args.start_line}-{args.start_line + args.line_count - 1}）")

    # 时间戳重写
    entries = rewrite_timestamps(entries_raw)

    # 验证时间戳在 7 天窗口内
    now_ms = int(time.time() * 1000)
    max_age_ms = 168 * 3600 * 1000
    out_of_window = sum(1 for ts, _ in entries if abs(now_ms - ts) > max_age_ms)
    if out_of_window:
        print(f"[warn] {out_of_window} 条日志时间戳超出 168h 窗口！", file=sys.stderr)
    else:
        print(f"[info] 所有时间戳在 168h 窗口内 ✓")

    # 构建 payload
    stream_labels = {
        "namespace": args.namespace,
        "pod": args.pod,
        "container": args.container,
        "job": f"{args.namespace}/{args.pod}",
        "app": "loghub-replay",
    }
    payload = build_loki_payload(entries, stream_labels)

    if args.output:
        Path(args.output).write_text(json.dumps(payload, indent=2))
        print(f"[info] payload 写入 {args.output}")

    if args.push:
        print(f"[info] 推送到 {args.loki_url} ...")
        ok = push_to_loki(payload, args.loki_url)
        if ok:
            print("[info] Loki push 成功（HTTP 204）✓")
        else:
            print("[error] Loki push 失败", file=sys.stderr)
            sys.exit(1)
    else:
        print(f"[info] 预处理完成，未推送（加 --push 推送到 Loki）")
        print(f"[info] 示例日志: {entries[0][1][:80]}")


if __name__ == "__main__":
    main()
