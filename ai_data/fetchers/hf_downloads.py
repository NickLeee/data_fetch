#!/usr/bin/env python3
"""HuggingFace 核心开源模型下载量 → series hf_downloads.jsonl，日级。

走 hf-mirror.com（官方域名本机被墙，API 兼容；Actions 上同样直连可用）。
hf-mirror 偶发被 SNI 干扰（连接级 SSL 断，间歇性）——本地调试可设环境变量
HF_API_BASE=https://huggingface.co/api/models/ 走代理用官方域名验证逻辑，
线上默认行为不变。

口径（重要）：
- `downloads` 是「近 30 天下载量」的滚动窗口，不是总量、也不是日增量；
  两个日期的差值是「下载速度的变化」，不是「这段时间新增了多少下载」。
- `downloadsAllTime` 才是累计下载量。从 2026-11-01 起同时记录它，
  攒够两天就能算真实日增量 = allTime(t) - allTime(t-1)。
  历史行没有这个字段，图表要能容忍 null。
"""

import os
import sys
import time

import common

SOURCE = "hf_downloads"
API = os.environ.get("HF_API_BASE", "https://hf-mirror.com/api/models/")
EXPAND = "?expand[]=downloads&expand[]=downloadsAllTime&expand[]=likes"

# 选型策略（2026-11-01 重排）：每家当红旗舰 + 上代存量 + 长青锚点，
# 用 role 标出来，出图时只取 flagship；存量与锚点只做历史对照。
# 老型号留在 series 历史里不删，只是不再增量。
MODELS = {
    # 当红旗舰
    "deepseek-ai/DeepSeek-V4.1-Flash": "flagship",
    "moonshotai/Kimi-K3": "flagship",
    "Qwen/Qwen3.8-27B": "flagship",
    "zai-org/GLM-5.3-Flash": "flagship",
    "zai-org/GLM-5.3": "flagship",
    "MiniMaxAI/MiniMax-H3": "flagship",
    "MiniMaxAI/MiniMax-M3": "flagship",
    "openai/gpt-oss-120b": "flagship",
    "openai/gpt-oss-20b": "flagship",
    "meta-llama/Llama-4-Scout-17B-16E-Instruct": "flagship",
    "mistralai/Devstral-Small-2-24B-Instruct-2512": "flagship",
    # 上代存量（看换代速度）
    "deepseek-ai/DeepSeek-V4-Flash-0731": "legacy",
    "deepseek-ai/DeepSeek-V3.2": "legacy",
    "moonshotai/Kimi-K2.6": "legacy",
    "Qwen/Qwen3.5-9B": "legacy",
    # 长青锚点（基线参照，几乎不动）
    "meta-llama/Meta-Llama-3.1-8B-Instruct": "anchor",
    "mistralai/Mistral-7B-Instruct-v0.3": "anchor",
    "deepseek-ai/DeepSeek-R1": "anchor",
}


def main():
    try:
        date = common.utc_today()
        raw = {}
        rows = []
        for model, role in MODELS.items():
            d = common.http_json(API + model + EXPAND, timeout=30)
            raw[model] = d
            if d.get("downloads") is None:
                raise RuntimeError(f"model {model}: no downloads field (renamed or removed?)")
            rows.append({
                "date": date,
                "model": model,
                "downloads": d["downloads"],
                "downloads_alltime": d.get("downloadsAllTime"),
                "likes": d.get("likes"),
                "role": role,
            })
            time.sleep(0.2)
        if not rows:
            raise RuntimeError("no rows")
        common.write_raw(SOURCE, {"fetched_at": common.utc_now_iso(), "models": raw})
        added = common.append_series(SOURCE, rows, ["model"])
        common.write_health(SOURCE, len(rows))
        print(f"{SOURCE}: {len(rows)} rows, {added} new")
    except Exception as e:
        common.write_health(SOURCE, 0, status="error", error=str(e))
        print(f"{SOURCE} error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
