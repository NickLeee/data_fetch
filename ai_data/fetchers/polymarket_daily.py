#!/usr/bin/env python3
"""Polymarket 预测市场（gamma API，免 key）→ series polymarket_daily.jsonl，日级。

三个系列（月度市场每月轮换，slug 不写死，按搜索 + 当月/当年正则动态解析）：
① 本月最大市值公司  largest-company-end-of-{month}-{year}
② 本年底最大市值公司 largest-company-end-of-december-{year}
③ 最强 AI 模型（月度 which-company-has-the-best-ai-model-end-of-{month}
            年度 which-company-has-best-ai-model-end-of-{year}）
某系列当月未创建则跳过并在输出说明，不算失败；全部找不到才算失败（0 行）。

event.markets 是二元市场数组（每候选公司一个），series 行取 outcome=groupItemTitle
（公司/实验室名）、probability=outcomePrices 里 "Yes" 的价格（隐含概率）。
"""

import json
import re
import sys
import time
import urllib.parse
from datetime import datetime, timezone

import common

SOURCE = "polymarket_daily"
GAMMA = "https://gamma-api.polymarket.com"

NOW = datetime.now(timezone.utc)
MONTH = NOW.strftime("%B").lower()   # 如 "october"
YEAR = NOW.strftime("%Y")            # 如 "2026"

# (系列名, 搜索词, 当月/当年 slug 正则)
SERIES = [
    ("largest_company_monthly", "largest company market cap",
     rf"^largest-company-end-of-{MONTH}-{YEAR}$"),
    ("largest_company_yearly", "largest company market cap",
     rf"^largest-company-end-of-december-{YEAR}$"),
    ("best_ai_model_monthly", "best AI model",
     rf"^which-company-has-the-best-ai-model-end-of-{MONTH}$"),
    ("best_ai_model_yearly", "best AI model",
     rf"^which-company-has-best-ai-model-end-of-{YEAR}$"),
]


def search_events(query):
    url = f"{GAMMA}/public-search?q={urllib.parse.quote(query)}"
    return common.http_json(url, timeout=30).get("events", [])


def main():
    try:
        date = common.utc_today()
        resolved = {}   # series_name -> event（含 markets）
        skipped = []
        search_cache = {}
        for name, query, slug_re in SERIES:
            if query not in search_cache:
                search_cache[query] = search_events(query)
                time.sleep(0.3)
            hit = None
            for ev in search_cache[query]:
                if re.match(slug_re, ev.get("slug", "")) and not ev.get("closed"):
                    hit = ev
                    break
            if not hit:
                skipped.append(name)
                continue
            # 搜索结果的 markets 可能不全，按 id 拉完整事件
            full = common.http_json(f"{GAMMA}/events/{hit['id']}", timeout=30)
            resolved[name] = full
            time.sleep(0.3)

        if skipped:
            print(f"{SOURCE}: series not found this month, skipped: {', '.join(skipped)}")
        if not resolved:
            raise RuntimeError("no target series resolved")

        rows = []
        for name, ev in resolved.items():
            for m in ev.get("markets") or []:
                outcome = m.get("groupItemTitle") or m.get("question")
                if re.match(r"^Company [A-Z]$", outcome or ""):
                    continue  # 开放式占位槽位（无交易、恒定 50%），非真实候选
                try:
                    outcomes = json.loads(m.get("outcomes") or "[]")
                    prices = json.loads(m.get("outcomePrices") or "[]")
                    if "Yes" not in outcomes or not prices:
                        continue
                    prob = float(prices[outcomes.index("Yes")])
                except (ValueError, TypeError):
                    continue
                rows.append({
                    "date": date,
                    "market_slug": ev.get("slug"),
                    "series": name,
                    "outcome": outcome,
                    "probability": prob,
                    "volume": float(m["volume"]) if m.get("volume") else None,
                    "liquidity": float(m["liquidity"]) if m.get("liquidity") else None,
                    "end_date": str(ev.get("endDate", ""))[:10],
                })
        if not rows:
            raise RuntimeError("no outcome rows parsed")

        common.write_raw(SOURCE, {
            "fetched_at": common.utc_now_iso(),
            "month": MONTH, "year": YEAR,
            "resolved": {k: {"id": v.get("id"), "slug": v.get("slug"), "title": v.get("title"),
                             "endDate": v.get("endDate")} for k, v in resolved.items()},
            "skipped_series": skipped,
            "events": resolved,
        })
        added = common.append_series(SOURCE, rows, ["market_slug", "outcome"])
        common.write_health(SOURCE, len(rows))
        print(f"{SOURCE}: {len(rows)} rows from {len(resolved)} series, {added} new")
    except Exception as e:
        common.write_health(SOURCE, 0, status="error", error=str(e))
        print(f"{SOURCE} error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
