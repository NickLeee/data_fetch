# -*- coding: utf-8 -*-
"""H100/H200/B200 趋势 + 供应商对比图：读 data/series/*.jsonl 出 PNG。"""
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime

ROOT = Path(__file__).resolve().parent.parent
SERIES = ROOT / "data" / "series"
OUT = ROOT.parent / "media" / "2026-09-21-compute-trends"
OUT.mkdir(parents=True, exist_ok=True)

GPUS = ["H100", "H200", "B200"]
# 各源的型号命名
NAME = {
    "ornn": {"H100": "H100 SXM", "H200": "H200", "B200": "B200"},
    "vast": {"H100": "H100_SXM", "H200": "H200", "B200": "B200"},
    "runpod": {"H100": "H100_SXM", "H200": "H200", "B200": "B200"},
    "shadeform": {"H100": "H100", "H200": "H200", "B200": "B200"},
}


def load(name):
    return [json.loads(l) for l in open(SERIES / f"{name}.jsonl")]


def xy(rows, value):
    rs = sorted((r for r in rows if r.get(value) is not None), key=lambda r: r["date"])
    return [datetime.fromisoformat(r["date"]) for r in rs], [r[value] for r in rs]


ocpi, otpi_done = load("ornn_ocpi"), None
vast, runpod, shade = load("gpu_vast"), load("gpu_runpod"), load("gpu_shadeform")

# ---------- 图 1：三卡趋势 ----------
fig, axes = plt.subplots(1, 3, figsize=(18, 5), sharex=False)
fig.suptitle("H100 / H200 / B200 price trends across sources ($/GPU-hr)", fontsize=14, fontweight="bold")
for ax, gpu in zip(axes, GPUS):
    x, y = xy([r for r in ocpi if r["gpu"] == NAME["ornn"][gpu]], "usd_per_hr")
    ax.plot(x, y, label="Ornn index (settled)", color="#111111", lw=2)
    x, y = xy([r for r in runpod if r["gpu"] == NAME["runpod"][gpu]], "secure_usd_hr")
    ax.plot(x, y, label="RunPod secure", color="#1f77b4", lw=1.2)
    x, y = xy([r for r in runpod if r["gpu"] == NAME["runpod"][gpu]], "community_spot_usd_hr")
    ax.plot(x, y, label="RunPod community spot", color="#1f77b4", lw=1.2, ls=":")
    x, y = xy([r for r in vast if r["gpu"] == NAME["vast"][gpu] and r["rental_type"] == "on_demand"], "median_usd_hr")
    ax.plot(x, y, label="vast on-demand median", color="#2ca02c", lw=1.2)
    x, y = xy([r for r in vast if r["gpu"] == NAME["vast"][gpu] and r["rental_type"] == "spot"], "median_usd_hr")
    ax.plot(x, y, label="vast spot median", color="#2ca02c", lw=1.2, ls=":")
    ax.set_title(gpu, fontsize=13, fontweight="bold")
    ax.grid(alpha=0.3); ax.legend(fontsize=8)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))
    ax.tick_params(axis="x", labelsize=8, rotation=30)
fig.tight_layout(rect=[0, 0, 1, 0.94])
p1 = OUT / "h100_h200_b200_trends.png"
fig.savefig(p1, dpi=150); plt.close(fig)

# ---------- 图 2：今日供应商对比（横向条形，每卡一张） ----------
latest_shade_date = max(r["date"] for r in shade)
latest_vast_date = max(r["date"] for r in vast)
latest_rp_date = max(r["date"] for r in runpod)
latest_ornn_date = max(r["date"] for r in ocpi)

fig, axes = plt.subplots(1, 3, figsize=(18, 7))
fig.suptitle(f"Supplier comparison — latest prices ($/GPU-hr)   "
             f"(shadeform/vast/runpod {latest_shade_date}, Ornn settled {latest_ornn_date})",
             fontsize=13, fontweight="bold")
for ax, gpu in zip(axes, GPUS):
    bars = []  # (label, price, color)
    # shadeform：每云最便宜档
    per_cloud = {}
    for r in shade:
        if r["date"] == latest_shade_date and r["gpu"] == NAME["shadeform"][gpu]:
            per_cloud[r["cloud"]] = min(per_cloud.get(r["cloud"], 9e9), r["usd_hr"])
    for cloud, price in per_cloud.items():
        bars.append((cloud, price, "#1f77b4"))
    # vast on-demand 当日 min
    v = [r for r in vast if r["date"] == latest_vast_date and r["gpu"] == NAME["vast"][gpu] and r["rental_type"] == "on_demand"]
    if v: bars.append(("vast.ai (mkt min)", v[0]["min_usd_hr"], "#2ca02c"))
    # runpod secure
    rp = [r for r in runpod if r["date"] == latest_rp_date and r["gpu"] == NAME["runpod"][gpu]]
    if rp and rp[0]["secure_usd_hr"]: bars.append(("RunPod secure", rp[0]["secure_usd_hr"], "#9467bd"))
    bars.sort(key=lambda b: b[1])
    labels = [b[0] for b in bars]; prices = [b[1] for b in bars]; colors = [b[2] for b in bars]
    ax.barh(labels, prices, color=colors)
    for i, p in enumerate(prices):
        ax.text(p + max(prices) * 0.01, i, f"${p:.2f}", va="center", fontsize=8)
    # Ornn 指数参考线
    o = [r for r in ocpi if r["date"] == latest_ornn_date and r["gpu"] == NAME["ornn"][gpu]]
    if o:
        ax.axvline(o[0]["usd_per_hr"], color="#d62728", ls="--", lw=1.5)
        ax.text(o[0]["usd_per_hr"], len(bars) - 0.3, f" Ornn ${o[0]['usd_per_hr']:.2f}", color="#d62728", fontsize=8)
    ax.set_title(gpu, fontsize=13, fontweight="bold")
    ax.tick_params(labelsize=8); ax.grid(axis="x", alpha=0.3)
    ax.set_xlim(0, max(prices) * 1.15)
fig.tight_layout(rect=[0, 0, 1, 0.94])
p2 = OUT / "h100_h200_b200_suppliers.png"
fig.savefig(p2, dpi=150); plt.close(fig)
print(p1); print(p2)
