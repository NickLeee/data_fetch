#!/usr/bin/env python3
"""Ornn OCPI 算力成交结算指数（5 个 GPU 型号）→ series ornn_ocpi.jsonl，日级，免 key。"""

import sys

import common

SOURCE = "ornn_ocpi"
URL = "https://api.ornnai.com/api/daily-index/all"
KEY_FIELDS = ["gpu"]


def to_rows(payload):
    rows = []
    for item in payload.get("data") or []:
        rows.append({
            "date": str(item.get("date", ""))[:10],
            "gpu": item.get("gpu_type"),
            "usd_per_hr": item.get("index_value"),
        })
    return [r for r in rows if r["date"] and r["gpu"]]


def main():
    try:
        payload = common.http_json(URL)
        rows = to_rows(payload)
        if not rows:
            raise RuntimeError(f"no rows parsed, success={payload.get('success')}")
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
