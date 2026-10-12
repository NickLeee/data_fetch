#!/usr/bin/env python3
"""一次性历史回填脚本 —— 手动运行，不进 Actions matrix。

三个任务（各自独立，失败互不影响，任一失败则整体非零退出）：
1. Ornn OCPI 历史：GET /api/gpu/<gpu>/index-history（免费层约 3 个月），
   5 个免费型号逐日 append 到 ornn_ocpi.jsonl（与线上抓取同格式，自动幂等）。
2. Ornn OTPI 历史：GET /api/otpi?startDate=30天前&endDate=昨天 + 无参数最新值，
   合并 append 到 ornn_otpi.jsonl。
3. vast.ai / RunPod 历史种子：下载 cherielilili/gpu-pricing-tracker 的
   observations.csv（2026-02 起每日抓取），映射到我们的 series schema，
   行内加 "via":"gpu-pricing-tracker" 标明出处。

种子 CSV 口径（读其源码 scripts/vast_fetcher.py / runpod_fetcher.py 确认）：
- vast regional 时期（source=console.vast.ai API，2026-05-08 起）：已是每卡 $/hr
  （dph_total/num_gpus；spot 用 min_bid/num_gpus，与我们线上 spot 用 dph_total 略有差异）。
- vast global 时期（source=getdeploying.com，~05-08 前）：整机价，需除以 gpu_count。
- runpod：region=secure+on_demand → securePrice；community+spot → communitySpotPrice；
  region=any 是合成的最低价行，跳过；global（getdeploying，~05-08 前）为每卡挂牌价，
  on_demand→secure_usd_hr、spot→community_spot_usd_hr 作为早期近似。
- lambda/crusoe/nebius/sfcompute 等其他 provider 不导入（已被 Shadeform 覆盖）。
"""

import csv
import io
import json
import statistics
import sys
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import common

TODAY = common.utc_today()
YESTERDAY = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
START_30D = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")

OCPI_GPUS = ["H100 SXM", "H200", "B200", "A100 SXM4", "RTX 5090"]
OCPI_HIST_URL = "https://api.ornnai.com/api/gpu/{gpu}/index-history"
OTPI_URL = "https://api.ornnai.com/api/otpi"
SEED_CSV_URL = ("https://raw.githubusercontent.com/cherielilili/"
                "gpu-pricing-tracker/main/data/observations.csv")
SEED_VIA = "gpu-pricing-tracker"
GETDEPLOYING = "https://getdeploying.com"

# 与线上 fetcher 一致的型号集合（CSV 的 gpu_model 已是同一套规范名，直接过滤）
VAST_GPUS = {"H100_SXM", "H100_PCIE", "H100_NVL", "H200", "B200", "GB200",
             "A100_SXM_80GB", "A100_PCIE_80GB", "RTX_4090", "RTX_5090", "MI300X"}
RUNPOD_GPUS = VAST_GPUS | {"B300"}


def write_raw_named(source, filename, payload, raw=False):
    """写 data/raw/<source>/<filename>（自定义文件名，区别于 write_raw 的当日日期名）。"""
    d = common.DATA_DIR / "raw" / source
    d.mkdir(parents=True, exist_ok=True)
    path = d / filename
    if raw:
        with open(path, "wb") as f:
            f.write(payload)
    else:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    return path


def backfill_ornn_ocpi():
    responses = {}
    rows = []
    for gpu in OCPI_GPUS:
        url = OCPI_HIST_URL.format(gpu=urllib.parse.quote(gpu))
        payload = common.http_json(url)
        responses[gpu] = payload
        data = payload.get("data") or []
        if not data:
            raise RuntimeError(f"OCPI index-history empty for {gpu!r}")
        for item in data:
            date = str(item.get("timestamp", ""))[:10]
            if date:
                rows.append({"date": date, "gpu": gpu,
                             "usd_per_hr": item.get("index_value")})
        time.sleep(0.3)
    write_raw_named("ornn_ocpi", f"{TODAY}-history.json",
                    {"fetched_at": common.utc_now_iso(), "gpus": responses})
    added = common.append_series("ornn_ocpi", rows, ["gpu"])
    print(f"ornn_ocpi backfill: {len(rows)} rows parsed, {added} new")


def backfill_ornn_otpi():
    hist = common.http_json(f"{OTPI_URL}?startDate={START_30D}&endDate={YESTERDAY}")
    latest = common.http_json(OTPI_URL)
    rows = []
    for payload in (hist, latest):
        for item in payload.get("data") or []:
            date = str(item.get("date", ""))[:10]
            lab = item.get("lab")
            if date and lab:
                rows.append({"date": date, "lab": lab,
                             "usd_per_mtok": item.get("indexPerMtok")})
    if not rows:
        raise RuntimeError("OTPI history empty")
    write_raw_named("ornn_otpi", f"{TODAY}-history.json",
                    {"fetched_at": common.utc_now_iso(), "history": hist, "latest": latest})
    added = common.append_series("ornn_otpi", rows, ["lab"])
    print(f"ornn_otpi backfill: {len(rows)} rows parsed, {added} new")


def backfill_seed_csv():
    req = urllib.request.Request(SEED_CSV_URL,
                                 headers={"User-Agent": "ai_data-backfill (contact: local)"})
    with urllib.request.urlopen(req, timeout=180) as resp:
        content = resp.read()
    write_raw_named("gpu_vast", "seed-gpu-pricing-tracker.csv", content, raw=True)

    vast_rows = seed_vast(csv.DictReader(io.StringIO(content.decode("utf-8"))))
    added_v = common.append_series("gpu_vast", vast_rows, ["gpu", "rental_type"])
    print(f"gpu_vast seed: {len(vast_rows)} rows parsed, {added_v} new")

    rp_rows = seed_runpod(csv.DictReader(io.StringIO(content.decode("utf-8"))))
    added_r = common.append_series("gpu_runpod", rp_rows, ["gpu"])
    print(f"gpu_runpod seed: {len(rp_rows)} rows parsed, {added_r} new")


def seed_vast(reader):
    # (date, gpu, rental_type) -> 跨 region/gpu_count 聚合
    groups = defaultdict(lambda: {"mins": [], "medians": [], "maxs": [], "offers": 0})
    for r in reader:
        if r["provider"] != "vast.ai" or r["gpu_model"] not in VAST_GPUS:
            continue
        gc = int(r["gpu_count"]) or 1
        # getdeploying 时期是整机价 → 除以卡数；vast API 时期已是每卡价
        div = gc if r["source_url"] == GETDEPLOYING else 1
        g = groups[(r["date"], r["gpu_model"], r["rental_type"])]
        g["mins"].append(float(r["price_min_usd"]) / div)
        g["medians"].append(float(r["price_median_usd"]) / div)
        g["maxs"].append(float(r["price_max_usd"]) / div)
        g["offers"] += int(r["n_offers"])
    rows = []
    for (date, gpu, rental_type), g in sorted(groups.items()):
        rows.append({
            "date": date, "gpu": gpu, "rental_type": rental_type,
            "min_usd_hr": round(min(g["mins"]), 4),
            "median_usd_hr": round(statistics.median(g["medians"]), 4),
            "max_usd_hr": round(max(g["maxs"]), 4),
            "offers": g["offers"],
            "via": SEED_VIA,
        })
    return rows


def seed_runpod(reader):
    # (date, gpu) -> {"secure": [...], "community": [...]}；region=any 跳过
    groups = defaultdict(lambda: {"secure": [], "community": []})
    for r in reader:
        if r["provider"] != "runpod" or r["gpu_model"] not in RUNPOD_GPUS:
            continue
        side = None
        if r["rental_type"] == "on_demand" and r["region"] in ("secure", "global"):
            side = "secure"   # global 时期（getdeploying 每卡挂牌价）作早期近似
        elif r["rental_type"] == "spot" and r["region"] in ("community", "global"):
            side = "community"
        if side:
            groups[(r["date"], r["gpu_model"])][side].append(float(r["price_median_usd"]))
    rows = []
    for (date, gpu), g in sorted(groups.items()):
        # GraphQL（secure/community）与 getdeploying（global）同一天都有时，价格一致，
        # 直接对各自 side 的全部值取中位数即可
        secure = round(statistics.median(g["secure"]), 4) if g["secure"] else None
        community = round(statistics.median(g["community"]), 4) if g["community"] else None
        rows.append({
            "date": date, "gpu": gpu,
            "secure_usd_hr": secure,
            "community_spot_usd_hr": community,
            "secure_available": secure is not None,
            "via": SEED_VIA,
        })
    return rows


TASKS = [
    ("ornn_ocpi", backfill_ornn_ocpi),
    ("ornn_otpi", backfill_ornn_otpi),
    ("seed_csv", backfill_seed_csv),
]


def main():
    failures = []
    for name, fn in TASKS:
        try:
            fn()
        except Exception as e:
            failures.append(name)
            print(f"{name} backfill error: {e}", file=sys.stderr)
    if failures:
        print(f"backfill failed for: {', '.join(failures)}", file=sys.stderr)
        sys.exit(1)
    print("backfill complete")


if __name__ == "__main__":
    main()
