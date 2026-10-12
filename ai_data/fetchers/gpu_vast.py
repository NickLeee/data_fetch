#!/usr/bin/env python3
"""vast.ai 散户市场 GPU 报价（on-demand + spot，min/median/max 每卡 $/hr）
→ series gpu_vast.jsonl，日级，免 key。每型号查两遍，某型号 0 offer 跳过（不算失败）。"""

import json
import statistics
import sys
import time
import urllib.parse

import common

SOURCE = "gpu_vast"
BASE = "https://console.vast.ai/api/v0/bundles/?q="
HEADERS = {"User-Agent": "gpu-tracker (contact: local)", "Accept": "application/json"}
KEY_FIELDS = ["gpu", "rental_type"]

# vast 写法 → 规范名
GPU_MAP = {
    "H100 SXM": "H100_SXM",
    "H100 PCIe": "H100_PCIE",
    "H100 NVL": "H100_NVL",
    "H200": "H200",
    "B200": "B200",
    "GB200": "GB200",
    "A100 SXM4": "A100_SXM_80GB",
    "A100 PCIE": "A100_PCIE_80GB",
    "RTX 4090": "RTX_4090",
    "RTX 5090": "RTX_5090",
    "MI300X": "MI300X",
}
RENTAL_TYPES = {"on-demand": "on_demand", "bid": "spot"}


def query(vast_name, qtype):
    q = {
        "verified": {"eq": True},
        "rentable": {"eq": True},
        "gpu_name": {"eq": vast_name},
        "type": qtype,
        "order": [["dph_total", "asc"]],
        "limit": 2000,
    }
    url = BASE + urllib.parse.quote(json.dumps(q))
    return common.http_json(url, headers=HEADERS, timeout=90)


def main():
    try:
        date = common.utc_today()
        raw_results = []
        rows = []
        for vast_name, gpu in GPU_MAP.items():
            for qtype, rental_type in RENTAL_TYPES.items():
                resp = query(vast_name, qtype)
                offers = resp.get("offers") or []
                raw_results.append({
                    "gpu": gpu, "vast_gpu_name": vast_name,
                    "rental_type": rental_type, "offer_count": len(offers),
                    "offers": offers,
                })
                prices = []
                for o in offers:
                    n = o.get("num_gpus")
                    total = o.get("dph_total")
                    if n and total is not None:
                        prices.append(total / n)
                if not prices:
                    continue  # 该型号无 offer，跳过
                rows.append({
                    "date": date,
                    "gpu": gpu,
                    "rental_type": rental_type,
                    "min_usd_hr": round(min(prices), 4),
                    "median_usd_hr": round(statistics.median(prices), 4),
                    "max_usd_hr": round(max(prices), 4),
                    "offers": len(prices),
                })
                time.sleep(0.5)
        if not rows:
            raise RuntimeError("0 rows across all GPUs (all models have no offers)")
        common.write_raw(SOURCE, {"date": date, "results": raw_results})
        added = common.append_series(SOURCE, rows, KEY_FIELDS)
        common.write_health(SOURCE, len(rows))
        print(f"{SOURCE}: {len(rows)} rows, {added} new")
    except Exception as e:
        common.write_health(SOURCE, 0, status="error", error=str(e))
        print(f"{SOURCE} error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
