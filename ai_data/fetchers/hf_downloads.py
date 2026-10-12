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

# DeepSeek / Qwen / GLM(zai-org) / Llama(meta-llama) / Mistral 主力模型
MODELS = [
    "deepseek-ai/DeepSeek-V3.2-Exp",
    "deepseek-ai/DeepSeek-R1",
    "Qwen/Qwen3-235B-A22B-Instruct-2507",
    "Qwen/Qwen3-Next-80B-A3B-Instruct",
    "Qwen/Qwen3-32B",
    "Qwen/Qwen2.5-72B-Instruct",
    "zai-org/GLM-4.6",
    "zai-org/GLM-4.5",
    "meta-llama/Llama-3.3-70B-Instruct",
    "meta-llama/Llama-4-Scout-17B-16E-Instruct",
    "meta-llama/Meta-Llama-3.1-8B-Instruct",
    "mistralai/Mistral-Small-3.2-24B-Instruct-2506",
    "mistralai/Magistral-Small-2509",
    "mistralai/Mistral-7B-Instruct-v0.3",
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
