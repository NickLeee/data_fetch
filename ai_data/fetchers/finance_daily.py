#!/usr/bin/env python3
"""金融市场日线 → series finance_daily.jsonl，日级，免 key。

- 股票（美股/ADR）：Yahoo Finance chart API（免 key JSON），
  NVDA/MSFT/GOOG/META/BABA/BIDU（阿里、百度用美股 ADR）。
- 期货：纳指100 = NQ=F、标普500 = ES=F（Yahoo 的 CME 连续期货合约口径，非指数现货）。
- 美债 10Y/2Y：FRED fredgraph.csv（DGS10/DGS2，免 key），值为 "." 的假日观测跳过。

数据源备注：任务原建议 stooq（/q/d/l/ CSV），但 2026-10 实测该 CSV 端点对数据中心
出口 IP 硬封锁（JS PoW 能过网页、CSV 仍 Access denied，裸连/代理同），故改用 Yahoo
chart API。stooq 的 PoW 通过器不在本文件保留；如未来要换回 stooq 需重新评估。

周末/假日无数据属正常：取最近一个交易日，date 用交易所本地交易日日期
（timestamp + meta.gmtoffset 换算），幂等键 date+symbol。注意盘中抓取时最后一根
bar 是未完成的当日 bar（价格随时间变，同日只写首次抓到的值）；早报 cron 在美股
开盘前跑时该 bar 即上一交易日收盘。
TODO: 市值——Yahoo chart meta 无市值字段（quoteSummary 端点需 crumb），暂未抓。
"""

import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

import common

SOURCE = "finance_daily"
# Yahoo 对 header 组合敏感：实测完整浏览器 UA + Accept:application/json 触发 429，
# 短 UA + Accept:*/* 稳定 200；而 FRED 反过来，短 Mozilla UA 会被挂起到读超时，
# curl UA 秒回（2026-10 本机实测）。两个站各用各的 UA。
UA = {"User-Agent": "Mozilla/5.0", "Accept": "*/*"}
FRED_UA = {"User-Agent": "curl/8.7.1", "Accept": "*/*"}

YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=5d&interval=1d"
STOCKS = ["NVDA", "MSFT", "GOOG", "META", "BABA", "BIDU"]
FUTURES = ["NQ=F", "ES=F"]  # CME 连续期货：纳指100、标普500
FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}"
FRED_SERIES = ["DGS10", "DGS2"]


def fetch_yahoo(symbol):
    """Yahoo chart：返回原始响应 dict。"""
    url = YAHOO_CHART.format(symbol=urllib.parse.quote(symbol))
    return common.http_json(url, headers=UA, timeout=30)


def last_bar(d, symbol):
    """从原始响应取最后一个 close 非空的日线 bar，返回 (交易日, close, volume)。"""
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
    for i in range(len(ts) - 1, -1, -1):
        if i < len(closes) and closes[i] is not None:
            day = datetime.fromtimestamp(ts[i] + gmtoff, tz=timezone.utc).strftime("%Y-%m-%d")
            vol = volumes[i] if i < len(volumes) else None
            return day, round(closes[i], 4), vol
    raise RuntimeError(f"yahoo {symbol}: no close value")


def last_fred(sid):
    """FRED CSV：返回 (原始文本, (date, value))，取最近一个非 '.' 观测。"""
    url = FRED_CSV.format(sid=sid)
    req = urllib.request.Request(url, headers=FRED_UA)
    text = urllib.request.urlopen(req, timeout=30).read().decode()
    for line in reversed(text.strip().splitlines()[1:]):
        parts = line.split(",")
        if len(parts) == 2 and parts[1] not in ("", "."):
            return text, (parts[0], float(parts[1]))
    raise RuntimeError(f"FRED {sid}: no observation")


def main():
    try:
        rows = []
        raw = {"fetched_at": common.utc_now_iso(), "yahoo": {}, "fred": {}}
        for sym in STOCKS + FUTURES:
            d = fetch_yahoo(sym)
            raw["yahoo"][sym] = d
            day, close, vol = last_bar(d, sym)
            rows.append({"date": day, "symbol": sym, "close": close, "volume": vol})
            time.sleep(1.2)  # Yahoo 对匿名限流敏感，慢点打
        for sid in FRED_SERIES:
            text, (day, val) = last_fred(sid)
            raw["fred"][sid] = text
            rows.append({"date": day, "symbol": sid, "close": val, "volume": None})
            time.sleep(0.3)
        if not rows:
            raise RuntimeError("no rows")
        common.write_raw(SOURCE, raw)
        added = common.append_series(SOURCE, rows, ["symbol"])
        common.write_health(SOURCE, len(rows))
        print(f"{SOURCE}: {len(rows)} rows, {added} new")
    except Exception as e:
        common.write_health(SOURCE, 0, status="error", error=str(e))
        print(f"{SOURCE} error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
