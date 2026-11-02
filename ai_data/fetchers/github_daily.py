#!/usr/bin/env python3
"""GitHub 日报 → series github_daily.jsonl（核心仓库 star/fork）+ github_new_repos.jsonl（新项目增速榜），日级。

两个产物解决两个问题：
- github_daily：18 个底座项目的 star/fork 存量，只做长期基线（同比/换代），
  单日增量意义不大——这些仓库体量太大，一天涨几百星说明不了什么。
- github_new_repos：**看板真正要的东西**——近 30 天新建、按「每天涨多少星」
  （stars / 建仓天数）排序的 AI 项目。绝对星数会被建仓时间带偏：同样 5 千星，
  10 天攒出来的和 300 天攒出来的不是一回事。同时记 created_at / forks / language，
  才能判断是真项目还是内容站。

匿名 60 req/h（18 仓库 + 4 次 search，够用）；环境变量 GITHUB_TOKEN 存在时带
Authorization header（Actions 上建议配，更稳）。search API 单独限额 10 次/分，
所以搜索词控制在 4 个以内。
"""

import os
import sys
import time
import re
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

NEW_REPO_DAYS = 30      # 窗口：近 30 天新建才算「新项目」
NEW_REPO_SCAN = 60      # 每路搜索取多少条（合并后再筛）
NEW_REPO_KEEP = 20      # 最终写入多少条
MIN_AGE_DAYS = 2        # 建仓不到两天的，涨星再快也是噪声
QUERIES = ["ai", "llm", "agent", "inference"]

# 内容型仓库（图库、合集、教程）不是「项目」，涨星再快也不进榜。
# 只看描述：真项目的描述通常在讲它做什么，内容站在讲它收录了什么。
CONTENT_RE = re.compile(
    r"(?i)(图库|图集|壁纸|合集|资源|模板|教程|指南|大全|精选|素材|"
    r"awesome|curated|collection|wallpaper|playbook|cheat|roadmap|"
    r"interview|course|book|notes|prompt\s*list)")


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

        # 新项目增速榜：多路搜索合并去重，按 stars/天 排序
        since_dt = datetime.now(timezone.utc) - timedelta(days=NEW_REPO_DAYS)
        since = since_dt.strftime("%Y-%m-%d")
        today = datetime.now(timezone.utc)
        cand = {}
        for q_ in QUERIES:
            q = urllib.parse.quote(f"{q_} created:>{since}")
            res = common.http_json(
                f"{API}/search/repositories?q={q}&sort=stars&order=desc"
                f"&per_page={NEW_REPO_SCAN}",
                headers=headers, timeout=30)
            for it in res.get("items", []):
                cand[it["full_name"]] = it
            time.sleep(1.0)  # search API 单独限流，别贴脸

        new_rows = []
        for it in cand.values():
            created = (it.get("created_at") or "")[:10]
            desc = it.get("description") or ""
            if not created or not desc or CONTENT_RE.search(desc):
                continue
            try:
                age = max((today - datetime.fromisoformat(created + "T00:00:00+00:00")).days, 1)
            except Exception:
                continue
            if age < MIN_AGE_DAYS:
                continue
            stars = it.get("stargazers_count") or 0
            new_rows.append({
                "date": date,
                "repo": it["full_name"],
                "stars": stars,
                "stars_per_day": round(stars / age, 1),
                "created_at": created,
                "age_days": age,
                "forks": it.get("forks_count"),
                "language": it.get("language"),
                "topics": (it.get("topics") or [])[:6],
                "description": desc[:200],
                "url": it.get("html_url"),
            })
        new_rows.sort(key=lambda r: -r["stars_per_day"])
        new_rows = new_rows[:NEW_REPO_KEEP]

        if not rows:
            raise RuntimeError("no repo rows")
        common.write_raw(SOURCE, {
            "fetched_at": common.utc_now_iso(),
            "repos": raw_repos,
            "new_repo_candidates": len(cand),
            "new_repo_top": [{k: r[k] for k in ("repo", "stars", "stars_per_day", "age_days")}
                             for r in new_rows],
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
