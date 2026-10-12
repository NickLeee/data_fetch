#!/usr/bin/env python3
"""Shadeform 聚合的 19 家云 GPU 挂牌价 → series gpu_shadeform.jsonl，日级，免 key。

注意：hourly_price 单位是美分且为整机价，换算成每卡 $/hr（/100/num_gpus）。
实际 gpu_type 拼写为 RTX4090/A100_80G/H100_nvl 等（无空格），映射到规范名。
"""

import sys

import common

SOURCE = "gpu_shadeform"
URL = "https://api.shadeform.ai/v1/instances/types"
# (cloud, gpu, num_gpus) 不是唯一键：同云同型号同卡数常有多个实例类型
# （裸金属/VM、NVLink 与否、不同区域）且价格不同，故 key 加 shade_instance_type
KEY_FIELDS = ["cloud", "gpu", "num_gpus", "instance"]

# 实际 gpu_type → 规范名；不在表内的型号跳过（当前数据无 GB200/MI300X）
GPU_MAP = {
    "H100": "H100",
    "H100_nvl": "H100_NVL",
    "H200": "H200",
    "B200": "B200",
    "GB200": "GB200",
    "A100": "A100",
    "A100_80G": "A100_80G",
    "RTX4090": "RTX_4090",
    "RTX5090": "RTX_5090",
    "MI300X": "MI300X",
    "L40S": "L40S",
}


def to_rows(payload, date):
    rows = []
    for inst in payload.get("instance_types") or []:
        gpu = GPU_MAP.get(inst.get("gpu_type"))
        if not gpu:
            continue
        n = inst.get("num_gpus")
        cents = inst.get("hourly_price")
        if not n or cents is None:
            continue
        rows.append({
            "date": date,
            "cloud": inst.get("cloud"),
            "gpu": gpu,
            "num_gpus": n,
            "instance": inst.get("shade_instance_type"),
            "usd_hr": round(cents / 100 / n, 4),
        })
    return rows


def main():
    try:
        payload = common.http_json(URL, timeout=90)
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
