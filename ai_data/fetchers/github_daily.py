#!/usr/bin/env python3
"""GitHub 日报 → series github_daily.jsonl（核心仓库 star/fork）+ github_new_repos.jsonl（近 7 天新建热门 AI 仓库），日级。

匿名 60 req/h（本文件 18 仓库 + 1 次 search，够用）；环境变量 GITHUB_TOKEN 存在时带
Authorization header（Actions 上建议配，更稳）。search API 单独限额 10 次/分。
"""

import os
import sys
import time
import urllib.parse
from datetime import datetime, timedelta, timezone

import common

SOURCE = "github_daily"
API = "https://api.github.com"

# 核心 AI 仓库：推理引擎 / 框架 / 应用 / 编程代理 + MCP、skills 官方仓库
# （2026-10 核名：ComfyUI 已迁 Comfy-Org、opencode 已迁 anomalyco、OpenHands 已迁 OpenHands org）
REPOS = [
    "ollama/ollama",
    "vllm-project/vllm",
    "ggml-org/llama.cpp",
    "huggingface/transformers",
    "langchain-ai/langchain",
    "open-webui/open-webui",
    "Comfy-Org/ComfyUI",
    "openai/codex",
    "anthropics/claude-code",
    "anomalyco/opencode",
    "cline/cline",
    "continuedev/continue",
    "Aider-AI/aider",
    "OpenHands/OpenHands",
    "crewAIInc/crewAI",
    "modelcontextprotocol/servers",
    "anthropics/skills",
    "openai/skills",
]

NEW_REPO_DAYS = 7
NEW_REPO_TOP_N = 15


def gh_headers():
    h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    tok = os.environ.get("GITHUB_TOKEN")
    if tok:
        h["Authorization"] = f"Bearer {tok}"
    return h


def main():
    try:
        date = common.utc_today()
        headers = gh_headers()
        raw_repos = {}
        rows = []
        for repo in REPOS:
            d = common.http_json(f"{API}/repos/{repo}", headers=headers, timeout=30)
            raw_repos[repo] = d
            if "stargazers_count" not in d:
                raise RuntimeError(f"repo {repo}: unexpected payload (rate limited or renamed?)")
            rows.append({
                "date": date,
                "repo": d.get("full_name", repo),
                "stars": d["stargazers_count"],
                "forks": d.get("forks_count"),
            })
            time.sleep(0.2)

        # 近 7 天新建、按 star 排序的 AI 相关热门仓库
        since = (datetime.now(timezone.utc) - timedelta(days=NEW_REPO_DAYS)).strftime("%Y-%m-%d")
        q = urllib.parse.quote(f"AI created:>{since}")
        search = common.http_json(
            f"{API}/search/repositories?q={q}&sort=stars&order=desc&per_page={NEW_REPO_TOP_N}",
            headers=headers, timeout=30)
        new_rows = [{
            "date": date,
            "repo": it["full_name"],
            "stars": it.get("stargazers_count"),
            "description": (it.get("description") or "")[:200],
            "url": it.get("html_url"),
        } for it in search.get("items", [])]

        if not rows:
            raise RuntimeError("no repo rows")
        common.write_raw(SOURCE, {
            "fetched_at": common.utc_now_iso(),
            "repos": raw_repos,
            "new_repo_search": search,
        })
        added = common.append_series(SOURCE, rows, ["repo"])
        added_new = common.append_series("github_new_repos", new_rows, ["repo"])
        common.write_health(SOURCE, len(rows) + len(new_rows))
        print(f"{SOURCE}: {len(rows)} repo rows ({added} new), "
              f"{len(new_rows)} new-repo rows ({added_new} new)")
    except Exception as e:
        common.write_health(SOURCE, 0, status="error", error=str(e))
        print(f"{SOURCE} error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
