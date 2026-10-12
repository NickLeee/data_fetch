#!/usr/bin/env python3
"""Smithery MCP 使用量榜 → series mcp_smithery.jsonl，日级，免 key。

实现方式：GET https://smithery.ai/servers（服务端渲染页），从 Next.js RSC
内嵌数据（self.__next_f.push chunks）中提取 qualifiedName/useCount/displayName。
注意：列表分页是客户端行为（?page=N 无效），只能拿到首屏 top 30，作为每日
使用量榜快照。RSC 解析依赖其字段命名，结构变化时需要跟改（2026-10 实测有效）。
"""

import re
import sys
import urllib.request

import common

SOURCE = "mcp_smithery"
URL = "https://smithery.ai/servers"
UA = {"User-Agent": "Mozilla/5.0"}
TOP_N = 30


def parse_servers(html):
    """从 RSC payload 提取 server 对象。字段间可能有别的键，逐对象宽松匹配。
    页面 RSC 里对象顺序不严格按使用量（混有 featured 段），按 useCount 降序重排定 rank。"""
    dec = html.encode().decode("unicode_escape", errors="ignore")
    objs = re.findall(
        r'\{[^{}]*"qualifiedName":"([^"]+)"[^{}]*?"useCount":(\d+)[^{}]*\}', dec)
    rows = []
    seen = set()
    for qname, use_count in objs:
        if qname in seen:
            continue
        seen.add(qname)
        rows.append({"server": qname, "use_count": int(use_count)})
    rows.sort(key=lambda r: r["use_count"], reverse=True)
    return rows


def main():
    try:
        date = common.utc_today()
        html = urllib.request.urlopen(
            urllib.request.Request(URL, headers=UA), timeout=60).read().decode("utf-8", errors="replace")
        servers = parse_servers(html)[:TOP_N]
        if not servers:
            raise RuntimeError("no servers parsed from RSC payload")
        rows = [{"date": date, "server": s["server"], "use_count": s["use_count"],
                 "rank": i + 1} for i, s in enumerate(servers)]
        common.write_raw(SOURCE, {"fetched_at": common.utc_now_iso(), "url": URL,
                                  "servers": servers, "html_head": html[:2000]})
        added = common.append_series(SOURCE, rows, ["server"])
        common.write_health(SOURCE, len(rows))
        print(f"{SOURCE}: {len(rows)} rows, {added} new")
    except Exception as e:
        common.write_health(SOURCE, 0, status="error", error=str(e))
        print(f"{SOURCE} error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
