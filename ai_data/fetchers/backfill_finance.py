#!/usr/bin/env python3
"""finance_daily 历史回填 —— 一次性脚本，手动或 backfill workflow 运行。

Yahoo chart API 用 period1/period2 拉全量日线（默认 2024-01-01 起，覆盖 AI 行情周期），
FRED fredgraph.csv 用 cosd 参数同起点。幂等：与日线 fetcher 共用 (date, symbol) 键，
重复跑无副作用。当日 bar 不写（可能盘中未完结；当日数据归 finance_daily 日常抓取管）。

raw 只写每个符号的覆盖摘要（首末日期、bar 数），不堆全量历史——历史明细本身就是 series。
"""

import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

import common
from finance_daily import FRED_SERIES, FRED_UA, FUTURES, STOCKS, UA

SOURCE = "finance_daily"
START = "2024-01-01"
YAHOO_RANGE = ("https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
               "?period1={p1}&period2={p2}&interval=1d")
FRED_CSV_RANGE = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}&cosd={start}"


def fetch_yahoo_history(symbol, p1, p2):
    url = YAHOO_RANGE.format(symbol=urllib.parse.quote(symbol), p1=p1, p2=p2)
    for attempt in range(3):
        try:
            return common.http_json(url, headers=UA, timeout=60, retries=1)
        except Exception as e:
            if "429" in str(e) and attempt < 2:
                time.sleep(15)
                continue
            raise


def iter_bars(d, symbol):
    """产出全部完整日线 bar：(交易日, close, volume)。跳过 close 为空的假日占位。"""
    res = (d.get("chart") or {}).get("result") or []
    if not res:
        err = (d.get("chart") or {}).get("error")
        raise RuntimeError(f"yahoo {symbol}: empty result ({err})")
    r0 = res[0]
    ts = r0.get("timestamp") or []
    quote = ((r0.get("indicators") or {}).get("quote") or [{}])[0]
    closes = quote.get("close") or []
    volumes = quote.get("volume") or []
    gmtoff = (r0.get("meta") or {}).get("gmtoffset", 0)
    for i in range(len(ts)):
        if i < len(closes) and closes[i] is not None:
            day = datetime.fromtimestamp(ts[i] + gmtoff, tz=timezone.utc).strftime("%Y-%m-%d")
            vol = volumes[i] if i < len(volumes) else None
            yield day, round(closes[i], 4), vol


def fetch_fred_history(sid):
    url = FRED_CSV_RANGE.format(sid=sid, start=START)
    req = urllib.request.Request(url, headers=FRED_UA)
    text = urllib.request.urlopen(req, timeout=60).read().decode()
    rows = []
    for line in text.strip().splitlines()[1:]:
        parts = line.split(",")
        if len(parts) == 2 and parts[1] not in ("", "."):
            rows.append((parts[0], float(parts[1])))
    return rows


def main():
    try:
        today = common.utc_today()
        p1 = int(datetime.fromisoformat(START).replace(tzinfo=timezone.utc).timestamp())
        p2 = int(time.time())
        rows = []
        summary = {}
        for sym in STOCKS + FUTURES:
            d = fetch_yahoo_history(sym, p1, p2)
            bars = [(day, c, v) for day, c, v in iter_bars(d, sym)
                    if START <= day < today]
            for day, close, vol in bars:
                rows.append({"date": day, "symbol": sym, "close": close, "volume": vol})
            summary[sym] = {"bars": len(bars),
                            "first": bars[0][0] if bars else None,
                            "last": bars[-1][0] if bars else None}
            time.sleep(1.2)  # Yahoo 对匿名限流敏感，慢点打
        for sid in FRED_SERIES:
            obs = [(day, v) for day, v in fetch_fred_history(sid) if day < today]
            for day, val in obs:
                rows.append({"date": day, "symbol": sid, "close": val, "volume": None})
            summary[sid] = {"bars": len(obs),
                            "first": obs[0][0] if obs else None,
                            "last": obs[-1][0] if obs else None}
            time.sleep(0.3)
        if not rows:
            raise RuntimeError("no rows")
        raw_dir = common.DATA_DIR / "raw" / SOURCE
        raw_dir.mkdir(parents=True, exist_ok=True)
        with open(raw_dir / "backfill-2024.json", "w", encoding="utf-8") as f:
            json.dump({"fetched_at": common.utc_now_iso(), "backfill_start": START,
                       "symbols": summary}, f, ensure_ascii=False, indent=2)
        added = common.append_series(SOURCE, rows, ["symbol"])
        print(f"{SOURCE} backfill: {len(rows)} rows since {START}, {added} new")
    except Exception as e:
        print(f"{SOURCE} backfill error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
