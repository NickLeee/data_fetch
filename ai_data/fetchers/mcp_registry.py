#!/usr/bin/env python3
"""MCP 官方 Registry → series mcp_registry.jsonl，日级，免 key。

GET https://registry.modelcontextprotocol.io/v0/servers?version=latest 拉全量。
已知服务端行为（2026-10 实测）：
- limit 上限 100（更大 422，limit=3 曾 500）；version=latest 让每 server 只回最新版一条
- cursor 是排他下界、可跳跃（cursor='m' 直接从 m 开头续拉）→ 按首字母分段并行拉
- 带 cursor 的深页很慢（本机每页 5~30s），总量约数万条；串行拉全量要 1 小时级，
  分段并行（默认 10 线程）压到分钟级。registry server name 规范为小写字母开头为主，
  数字/符号开头的归入第一段（'' 段）。
- raw 存精简映射 {name: {version, published_at}}（全量原始条目每天数十 MB，超 raw
  层合理体量；重解析需要时可用 servers/{name}/versions 端点逐条回补）
series：{date, total_servers, new_count}；new_count = publishedAt 当日(UTC)的条数。
"""

import string
import sys
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

import common

SOURCE = "mcp_registry"
BASE = "https://registry.modelcontextprotocol.io/v0/servers?version=latest&limit=100"
META_KEY = "io.modelcontextprotocol.registry/official"
WORKERS = 10


def fetch_segment(start, end):
    """拉 name ∈ [start, end) 的段（end=None 表示到尽头）。cursor 从段起点跳。"""
    out = []
    cursor = start or None
    while True:
        url = BASE + ("&cursor=" + urllib.parse.quote(cursor) if cursor else "")
        d = common.http_json(url, timeout=90, retries=3)
        batch = d.get("servers") or []
        for s in batch:
            name = (s.get("server") or {}).get("name") or ""
            if end and name.lower() >= end:
                out.append(s)  # 大小写差异导致的边界条目：收下，fetch_all 按 name 去重
                return out
            out.append(s)
        cursor = (d.get("metadata") or {}).get("nextCursor")
        if not cursor or not batch:
            return out
        time.sleep(0.2)


def fetch_all():
    # 段边界：''(数字/符号等，到 'a' 为止) + a..y + z(到尽头)
    bounds = [""] + list(string.ascii_lowercase)
    segments = [(bounds[i], bounds[i + 1] if i + 1 < len(bounds) else None)
                for i in range(len(bounds))]
    servers = {}  # name -> 条目（去重）
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(fetch_segment, s, e): (s, e) for s, e in segments}
        for fut, (s, e) in futs.items():
            batch = fut.result()
            for item in batch:
                name = (item.get("server") or {}).get("name")
                if name:
                    servers[name] = item
            print(f"  segment [{s or '^'},{e or '$'}): {len(batch)} entries", file=sys.stderr)
    return servers


def main():
    try:
        today = common.utc_today()
        servers = fetch_all()
        if not servers:
            raise RuntimeError("registry returned 0 servers")
        summary = {}
        new_today = []
        for name, s in servers.items():
            meta = (s.get("_meta") or {}).get(META_KEY) or {}
            published = str(meta.get("publishedAt", ""))
            summary[name] = {"version": (s.get("server") or {}).get("version"),
                             "published_at": published}
            if published[:10] == today:
                new_today.append(name)
        row = {
            "date": today,
            "total_servers": len(servers),
            "new_count": len(new_today),
        }
        common.write_raw(SOURCE, {
            "fetched_at": common.utc_now_iso(),
            "total_servers": len(servers),
            "new_today_names": sorted(new_today),
            "servers": summary,
        })
        added = common.append_series(SOURCE, [row], [])
        common.write_health(SOURCE, 1)
        print(f"{SOURCE}: total_servers={len(servers)} new_today={len(new_today)} ({added} new)")
    except Exception as e:
        common.write_health(SOURCE, 0, status="error", error=str(e))
        print(f"{SOURCE} error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
