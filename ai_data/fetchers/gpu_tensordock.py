#!/usr/bin/env python3
"""TensorDock hostnode GPU 报价 → series gpu_tensordock.jsonl，日级，免 key。

实际响应结构（2026-09 实测）：{"hostnodes": {uuid: node}, "success": true}，
每个 node 的 specs.gpu 是 {slug: {"amount","price","vram","pcie","rtx","gtx"}} 字典，
price 即该节点该型号每卡 $/hr（如 geforcertx4090-pcie-24gb price=0.48）。
按规范型号聚合 min/median/max + 节点数；匹配不上的 slug 归入原始名。
"""

import statistics
import sys

import common

SOURCE = "gpu_tensordock"
URL = "https://console.tensordock.com/api/v0/client/deploy/hostnodes"
HEADERS = {"User-Agent": "Mozilla/5.0"}
KEY_FIELDS = ["gpu"]


def norm_gpu(slug):
    s = slug.lower()
    if "gb200" in s:
        return "GB200"
    if "b300" in s:
        return "B300"
    if "b200" in s:
        return "B200"
    if "h200" in s:
        return "H200"
    if "h100" in s:
        if "nvl" in s:
            return "H100_NVL"
        if "pcie" in s:
            return "H100_PCIE"
        if "sxm" in s:
            return "H100_SXM"
        return "H100"
    if "mi300" in s:
        return "MI300X"
    if "a100" in s:
        if "pcie" in s:
            return "A100_PCIE_80GB"
        if "sxm" in s:
            return "A100_SXM_80GB"
        return "A100"
    if "rtx4090" in s:
        return "RTX_4090"
    if "rtx5090" in s:
        return "RTX_5090"
    return slug  # 匹配不上归入原始名


def to_rows(payload, date):
    by_gpu = {}  # 规范名 -> 各节点每卡 $/hr
    for node in (payload.get("hostnodes") or {}).values():
        for slug, g in ((node.get("specs") or {}).get("gpu") or {}).items():
            price = g.get("price")
            if price is None:
                continue
            by_gpu.setdefault(norm_gpu(slug), []).append(price)
    rows = []
    for gpu, prices in sorted(by_gpu.items()):
        rows.append({
            "date": date,
            "gpu": gpu,
            "min_usd_hr": round(min(prices), 4),
            "median_usd_hr": round(statistics.median(prices), 4),
            "max_usd_hr": round(max(prices), 4),
            "nodes": len(prices),
        })
    return rows


def main():
    try:
        payload = common.http_json(URL, headers=HEADERS, timeout=90)
        rows = to_rows(payload, common.utc_today())
        if not rows:
            raise RuntimeError("no rows parsed (no hostnodes with GPUs)")
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
