# -*- coding: utf-8 -*-
"""算力价格趋势图（一次性查看用）：读取 data/series/*.jsonl 出 PNG。"""
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


def load(name):
    return [json.loads(l) for l in open(SERIES / f"{name}.jsonl")]


def xy(rows, value, group_key=None, group_val=None):
    rs = [r for r in rows if r.get(value) is not None
          and (group_key is None or r.get(group_key) == group_val)]
    rs.sort(key=lambda r: r["date"])
    return [datetime.fromisoformat(r["date"]) for r in rs], [r[value] for r in rs]


fig, axes = plt.subplots(2, 2, figsize=(14, 9))
fig.suptitle("AI Compute Market Trends (ai_data first pull)", fontsize=14, fontweight="bold")

# 1. Ornn OCPI
ax = axes[0][0]
ocpi = load("ornn_ocpi")
for gpu, color in [("B200", "#d62728"), ("H200", "#ff7f0e"), ("H100 SXM", "#1f77b4"),
                   ("A100 SXM4", "#2ca02c"), ("RTX 5090", "#9467bd")]:
    x, y = xy(ocpi, "usd_per_hr", "gpu", gpu)
    ax.plot(x, y, label=gpu, color=color, lw=1.4)
ax.set_title("Ornn OCPI — settled GPU index ($/GPU-hr, 3mo)")
ax.legend(fontsize=8); ax.grid(alpha=0.3)

# 2. Ornn OTPI
ax = axes[0][1]
otpi = load("ornn_otpi")
for lab, color in [("anthropic", "#d62728"), ("google", "#1f77b4"),
                   ("openai", "#2ca02c"), ("deepseek", "#9467bd")]:
    x, y = xy(otpi, "usd_per_mtok", "lab", lab)
    ax.plot(x, y, label=lab, color=color, lw=1.4, marker=".", ms=3)
ax.set_yscale("log")
ax.set_title("Ornn OTPI — settled token price ($/M tok, log)")
ax.legend(fontsize=8); ax.grid(alpha=0.3, which="both")

# 3. vast.ai consumer + H100
ax = axes[1][0]
vast = load("gpu_vast")
for gpu, rt, color, ls in [("RTX_4090", "spot", "#1f77b4", "-"), ("RTX_5090", "spot", "#9467bd", "-"),
                            ("H100_SXM", "spot", "#d62728", "-"), ("H100_SXM", "on_demand", "#d62728", "--")]:
    rs = [r for r in vast if r["gpu"] == gpu and r["rental_type"] == rt]
    x, y = xy(rs, "median_usd_hr")
    ax.plot(x, y, label=f"{gpu} {rt}", color=color, ls=ls, lw=1.2)
ax.set_title("vast.ai marketplace — median $/GPU-hr (since Feb)")
ax.legend(fontsize=8); ax.grid(alpha=0.3)

# 4. RunPod H100
ax = axes[1][1]
rp = load("gpu_runpod")
h100 = [r for r in rp if r["gpu"] == "H100_SXM"]
x, y = xy(h100, "secure_usd_hr")
ax.plot(x, y, label="secure on-demand", color="#1f77b4", lw=1.4)
x, y = xy(h100, "community_spot_usd_hr")
ax.plot(x, y, label="community spot", color="#d62728", lw=1.4)
ax.set_title("RunPod H100 SXM — secure vs community spot ($/GPU-hr)")
ax.legend(fontsize=8); ax.grid(alpha=0.3)

for a in axes.flat:
    a.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))
    a.tick_params(axis="x", labelsize=8, rotation=30)

fig.tight_layout(rect=[0, 0, 1, 0.96])
out = OUT / "compute_trends.png"
fig.savefig(out, dpi=150)
print(out)
