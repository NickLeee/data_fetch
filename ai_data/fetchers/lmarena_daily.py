#!/usr/bin/env python3
"""LMArena (arena.ai) text 总榜 → series lmarena_daily.jsonl，日级，免 key。

数据源沿革：lmarena.ai 2026 年整站 301 到 arena.ai；/leaderboard 为 Next.js SSR，
榜单数据内嵌在 RSC payload（self.__next_f.push chunks）的 entries 数组里：
{"rank","rankUpper","rankLower","modelKey","modelDisplayName","rating","votes",...}。
注意 2026 年内计分制已从 Elo(~1500) 换成归一化 rating(~±0.2)，字段名仍为 rating，
series 沿用原名。页面默认内嵌 text 总榜（Overall）top 50；更多名次由客户端 API
（/nextjs-api/leaderboard*）加载，该路径被 Cloudflare WAF 定向拦截，故只取 SSR 部分。
arena.ai 的 /leaderboard 对本机出口 IP 间歇性 403（managed challenge，多试可过）；
若 Actions 机房同样被挡，本 fetcher 按失败路径非零退出并记录 health。
合规提示：arena.ai ToS 有反自动化抓取条款，启用前请评估（详见任务报告）。
"""

import json
import re
import sys
import urllib.request

import common

SOURCE = "lmarena_daily"
URL = "https://arena.ai/leaderboard"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
      "Accept": "text/html,application/xhtml+xml"}
TOP_N = 50  # 页面 SSR 实际只内嵌 top 10


def extract_json_array(text, start):
    """从 text[start]（必须是 '['）括号平衡提取完整 JSON 数组文本。"""
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if esc:
            esc = False
            continue
        if ch == "\\":
            esc = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None


def parse_leaderboards(html):
    """从 RSC payload 提取所有榜的 entries，返回 list[list[dict]]。"""
    chunks = re.findall(r'self\.__next_f\.push\(\[1,\\?"(.*?)"\]\)</script>', html, re.S)
    if not chunks:
        return []
    dec = "".join(chunks).encode().decode("unicode_escape", errors="ignore")
    boards = []
    for m in re.finditer(r'"entries":\[', dec):
        arr_txt = extract_json_array(dec, m.end() - 1)
        if not arr_txt:
            continue
        try:
            arr = json.loads(arr_txt)
        except Exception:
            continue
        if arr and isinstance(arr[0], dict) and "modelDisplayName" in arr[0] and "rating" in arr[0]:
            boards.append(arr)
    return boards


def main():
    try:
        date = common.utc_today()
        req = urllib.request.Request(URL, headers=UA)
        html = urllib.request.urlopen(req, timeout=60).read().decode("utf-8", errors="replace")
        boards = parse_leaderboards(html)
        if not boards:
            raise RuntimeError("no leaderboard entries parsed (page structure changed or blocked)")
        text_board = boards[0][:TOP_N]  # 第一个榜 = text 总榜（页面默认主榜）
        rows = [{
            "date": date,
            "model": e["modelDisplayName"],
            "rank": e["rank"],
            "rating": round(e["rating"], 4),
            "votes": e.get("votes"),
        } for e in text_board]
        if not rows:
            raise RuntimeError("text board empty")
        common.write_raw(SOURCE, {"fetched_at": common.utc_now_iso(), "url": URL,
                                  "boards_count": len(boards), "html": html})
        added = common.append_series(SOURCE, rows, ["model"])
        common.write_health(SOURCE, len(rows))
        print(f"{SOURCE}: {len(rows)} rows, {added} new")
    except Exception as e:
        common.write_health(SOURCE, 0, status="error", error=str(e))
        print(f"{SOURCE} error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
