#!/usr/bin/env python3
"""RunPod GPU 挂牌价（secure）与 spot 价 → series gpu_runpod.jsonl，日级，免 key GraphQL。"""

import sys

import common

SOURCE = "gpu_runpod"
URL = "https://api.runpod.io/graphql"
KEY_FIELDS = ["gpu"]

QUERY = "query { gpuTypes { displayName memoryInGb securePrice communitySpotPrice } }"

# displayName → 规范名（只保留这些型号；API 当前无 GB200，缺型号自动跳过）
GPU_MAP = {
    "H100 SXM": "H100_SXM",
    "H100 PCIe": "H100_PCIE",
    "H100 NVL": "H100_NVL",
    "H200 SXM": "H200",
    "B200": "B200",
    "B300": "B300",
    "GB200": "GB200",
    "A100 SXM": "A100_SXM_80GB",
    "A100 PCIe": "A100_PCIE_80GB",
    "RTX 4090": "RTX_4090",
    "RTX 5090": "RTX_5090",
    "MI300X": "MI300X",
}


def to_rows(payload, date):
    rows = []
    for item in (payload.get("data") or {}).get("gpuTypes") or []:
        gpu = GPU_MAP.get(item.get("displayName"))
        if not gpu:
            continue
        secure = item.get("securePrice")
        rows.append({
            "date": date,
            "gpu": gpu,
            "secure_usd_hr": secure,
            "community_spot_usd_hr": item.get("communitySpotPrice"),
            "secure_available": bool(secure),  # securePrice=0 表示无货
        })
    return rows


def main():
    try:
        payload = common.http_json(URL, method="POST", payload={"query": QUERY})
        rows = to_rows(payload, common.utc_today())
        if not rows:
            raise RuntimeError("no rows parsed")
        common.write_raw(SOURCE, payload)
        added = common.append_series(SOURCE, rows, KEY_FIELDS)
        common.write_health(SOURCE, len(rows))
        print(f"{SOURCE}: {len(rows)} rows, {added} new")
    except Exception as e:
        common.write_health(SOURCE, 0, status="error", error=str(e))
        print(f"{SOURCE} error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
