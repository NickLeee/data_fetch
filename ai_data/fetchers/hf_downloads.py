#!/usr/bin/env python3
"""HuggingFace 核心开源模型下载量 → series hf_downloads.jsonl，日级。

走 hf-mirror.com（官方域名本机被墙，API 兼容；Actions 上同样直连可用）。
hf-mirror 偶发被 SNI 干扰（连接级 SSL 断，间歇性）——本地调试可设环境变量
HF_API_BASE=https://huggingface.co/api/models/ 走代理用官方域名验证逻辑，
线上默认行为不变。注意口径：HF 的 downloads 字段是「近 30 天下载量」（滚动窗口），
不是总量、也不是日增量。
"""

import os
import sys
import time

import common

SOURCE = "hf_downloads"
API = os.environ.get("HF_API_BASE", "https://hf-mirror.com/api/models/")

# 选型策略（2026-10-13 重排）：每家当红旗舰 + 上代存量主力 + 长青锚点。
# 老型号留在 series 历史里不删，只是不再增量。
MODELS = [
    # 长青锚点（基线参照）
    "meta-llama/Meta-Llama-3.1-8B-Instruct",
    "deepseek-ai/DeepSeek-R1",
    # DeepSeek：V4.1-Flash 当红，V4/V3.2 存量
    "deepseek-ai/DeepSeek-V4.1-Flash",
    "deepseek-ai/DeepSeek-V4-Flash-0731",
    "deepseek-ai/DeepSeek-V3.2",
    # Kimi：K3 当红（赞全场最高）
    "moonshotai/Kimi-K3",
    "moonshotai/Kimi-K2.6",
    # Qwen：3.8-27B 当红中尺寸，3.5-9B 上代存量
    "Qwen/Qwen3.8-27B",
    "Qwen/Qwen3.5-9B",
    # GLM：5.3-Flash 当红
    "zai-org/GLM-5.3-Flash",
    "zai-org/GLM-5.3",
    # Mistral：开源线收缩，留 7B 锚点 + Devstral 编码线
    "mistralai/Mistral-7B-Instruct-v0.3",
    "mistralai/Devstral-Small-2-24B-Instruct-2512",
    # Llama-4 线（观察 Llama 新品牵引力）
    "meta-llama/Llama-4-Scout-17B-16E-Instruct",
    # OpenAI 开源权重
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
    # MiniMax：H3 当红
    "MiniMaxAI/MiniMax-H3",
    "MiniMaxAI/MiniMax-M3",
]


def main():
    try:
        date = common.utc_today()
        raw = {}
        rows = []
        for m in MODELS:
            d = common.http_json(API + m, timeout=30)
            raw[m] = d
            if d.get("downloads") is None:
                raise RuntimeError(f"model {m}: no downloads field (renamed or removed?)")
            rows.append({
                "date": date,
                "model": m,
                "downloads": d["downloads"],
                "likes": d.get("likes"),
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
