"""共享 IO 助手：输出目录解析、raw 快照、series 幂等追加、health 文件。

刻意保持薄：只放所有 fetcher 都需要的文件/HTTP IO，不做抽象层。
输出目录默认 <ai_data>/data/（与本文件相对定位，与 cwd 无关），
环境变量 AI_DATA_DIR 可覆盖（本地调试用，输出到临时目录）。
"""

import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

AI_DATA_ROOT = Path(__file__).resolve().parent.parent
_override = os.environ.get("AI_DATA_DIR")
DATA_DIR = Path(_override) if _override else AI_DATA_ROOT / "data"


def utc_now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def utc_today():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def http_json(url, method="GET", payload=None, headers=None, timeout=60, retries=3):
    """GET/POST JSON，返回解析后的对象。payload 为 dict 时自动序列化并补 Content-Type。

    瞬时网络错误（SSL 断流、超时、5xx）重试 retries 次，间隔 2s/5s。
    """
    hdrs = {"Accept": "application/json", "User-Agent": "ai_data-fetcher (contact: local)"}
    if headers:
        hdrs.update(headers)
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        hdrs.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    err = None
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            err = e
            if isinstance(e, urllib.error.HTTPError):
                if e.code == 429 and attempt < retries:
                    time.sleep(15 + attempt * 15)  # 限流：等久一点
                    continue
                if e.code < 500:
                    break  # 其他 4xx 重试无意义
            if attempt < retries:
                time.sleep(2 + attempt * 3)
    raise err


def write_raw(source, payload):
    """写 data/raw/<source>/<YYYY-MM-DD>.json（UTC 日期），返回路径。"""
    d = DATA_DIR / "raw" / source
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{utc_today()}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return path


def append_series(series_name, rows, key_fields):
    """追加 data/series/<series_name>.jsonl，一行一个 JSON。

    幂等：已存在相同 (date, *key_fields) 的行则跳过。返回实际追加的行数。
    """
    path = DATA_DIR / "series" / f"{series_name}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = set()
    if path.exists():
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                r = json.loads(line)
                existing.add(tuple([r.get("date")] + [r.get(k) for k in key_fields]))
    added = 0
    with open(path, "a", encoding="utf-8") as f:
        for r in rows:
            key = tuple([r.get("date")] + [r.get(k) for k in key_fields])
            if key in existing:
                continue
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            existing.add(key)
            added += 1
    return added


def write_health(source, rows_count, status="ok", error=None):
    """写 data/health/<source>.json。失败时保留上一次成功的 last_success。"""
    path = DATA_DIR / "health" / f"{source}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    last_success = None
    if status == "ok":
        last_success = utc_now_iso()
    elif path.exists():
        try:
            last_success = json.loads(path.read_text(encoding="utf-8")).get("last_success")
        except Exception:
            pass
    doc = {
        "source": source,
        "status": status,
        "rows": rows_count,
        "last_success": last_success,
        "error": error,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
