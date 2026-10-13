#!/usr/bin/env python3
"""HuggingFace 社区热门改造模型榜 → series hf_community.jsonl，日级。

口径：text-generation 按近 30 天下载量取 top 100，剔除官方 org（基座模型的
"供给侧"）后剩下的就是社区改造（GGUF 量化 / uncensored / 微调 merge 等），取 top 20。
动态榜：不维护名单，社区口味变了榜自动变。

走 hf-mirror.com（同 hf_downloads.py；HF_API_BASE 环境变量可换官方域名调试）。
"""

import os
import sys
import time

import common

SOURCE = "hf_community"
API_BASE = os.environ.get("HF_API_BASE", "https://hf-mirror.com/api/models")
TOP_N = 20

# 官方 org（基座模型供给侧，剔除后剩下社区改造）。口味漂移时补这个集合即可。
OFFICIAL_ORGS = {
    "Qwen", "meta-llama", "deepseek-ai", "zai-org", "mistralai", "openai",
    "moonshotai", "MiniMaxAI", "google", "microsoft", "nvidia", "apple",
    "facebook", "openai-community", "EleutherAI", "bigscience", "tiiuae",
    "01-ai", "baichuan-inc", "THUDM", "internlm", "stepfun-ai", "allenai",
    "openbmb", "HuggingFaceTB", "distilbert",
    # CI/测试夹具 repo，下载量是管道噪音
    "trl-internal-testing", "sshleifer",
}


def main():
    try:
        url = (f"{API_BASE}?pipeline_tag=text-generation&sort=downloads"
               f"&direction=-1&limit=100&full=false")
        models = common.http_json(url, timeout=60)
        if not models:
            raise RuntimeError("empty model list")
        community = [m for m in models
                     if (m.get("id") or "").split("/")[0] not in OFFICIAL_ORGS]
        top = community[:TOP_N]
        today = common.utc_today()
        rows = [{"date": today, "model": m["id"], "downloads": m.get("downloads"),
                 "likes": m.get("likes"), "rank": i + 1}
                for i, m in enumerate(top)]
        common.write_raw(SOURCE, {"fetched_at": common.utc_now_iso(),
                                  "community_top100": [
                                      {"id": m["id"], "downloads": m.get("downloads"),
                                       "likes": m.get("likes")} for m in community]})
        added = common.append_series(SOURCE, rows, ["model"])
        common.write_health(SOURCE, len(rows))
        print(f"{SOURCE}: {len(rows)} rows, {added} new")
    except Exception as e:
        common.write_health(SOURCE, 0, status="error", error=str(e))
        print(f"{SOURCE} error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
