#!/usr/bin/env python3
"""GitHub 日更 → series github_daily.jsonl（宇宙 star 快照）+ github_growth.jsonl（增速榜）。

**榜按「单位时间涨星」排，不按建仓时间筛。** 建仓时间只影响窗口：
过去 7 天涨了多少星 / 7 = 日均增速；建仓不满 7 天的，窗口就是它的全部寿命。
这样「三年老项目突然爆」和「三天新仓库从零起」在同一根轴上可比。

三路信号合并，每行都带 window_days，口径写在数据里：

1. 自有快照（signal=snapshot）：同一批仓库每天快照一次，7 天后就有精确的
   自有增量。这是主力——趋势榜漏掉的、中文/小众项目都能测到。
   宇宙 = 18 个底座 + watchlist 累积 + 趋势榜 + 新仓库候选，上限 UNIVERSE_CAP。
   用 GraphQL 批量查（100 个/次），几百个仓库只要 2~4 个请求。
2. 趋势榜（signal=trending_week / trending_day）：github.com/trending 自己给的
   「N stars this week/today」，任何年龄的仓库都能立刻进榜——冷启动和补漏靠它。
   只收 AI 相关的（AI_RE 过滤），否则终端、游戏之类的会盖掉 AI。
3. 新建仓库（signal=new）：search created:>30d，抓从零爆发、还没进趋势榜的小仓库。

匿名 REST 也能跑（只有 18 个底座），GraphQL 与 search 需要 GITHUB_TOKEN
（Actions 里用 secrets.GITHUB_TOKEN）。

内容型仓库（图库、合集、教程）不是「项目」，涨星再快也不进榜，见 CONTENT_RE。
"""

import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import common

SOURCE = "github_daily"
GROWTH_SERIES = "github_growth"
API = "https://api.github.com"
GRAPHQL = "https://api.github.com/graphql"

# 底座项目：推理引擎 / 框架 / 应用 / 编程代理 + MCP、skills 官方仓库
# （2026-10 核名：ComfyUI 已迁 Comfy-Org、opencode 已迁 anomalyco、OpenHands 已迁 OpenHands org）
CORE_REPOS = [
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

WINDOW_DAYS = 7         # 增速窗口：过去 7 天
NEW_REPO_DAYS = 30      # 新仓库搜索窗口
NEW_REPO_SCAN = 60      # 每路搜索取多少条
UNIVERSE_CAP = 600      # 每天快照的仓库上限（GraphQL 100/次）
BOARD_KEEP = 25         # 增速榜保留多少条
MIN_WINDOW = 2          # 窗口至少 2 天：1 天的突增波动太大，只当注脚不进榜
MIN_GAIN = 200          # 窗口内至少涨这么多星才进榜
MIN_PER_DAY = 40        # 日均涨星下限
QUERIES = ["ai", "llm", "agent", "inference"]      # 新仓库发现
# 长青名单：按 star 排的 AI 主题头部仓库。不手写名单——每周自动重取，
# 让「三年老项目突然爆」有底账可比（趋势榜只给 25 个位置，靠不住）
SEED_QUERIES = ["topic:llm", "topic:ai-agents", "topic:llm-inference", "topic:generative-ai"]
SEED_SCAN = 100

# AI 相关判定：趋势榜里混着终端、编辑器、游戏，靠描述筛一道
AI_RE = re.compile(
    r"(?i)(\bai\b|\bllms?\b|\bagents?\b|\bmodel|\binference|\bgpt|claude|gemini|"
    r"llama|qwen|deepseek|kimi|glm|minimax|diffusion|transformer|\bmcp\b|skill|"
    r"embedding|\brag\b|fine-?tun|prompt|robot|machine.learn|neural|\bgpu|cuda|vllm|"
    r"ollama|langchain|openai|anthropic|vision|speech|\btts\b|\basr\b|copilot|"
    r"vibe|swarm|vector|retrieval|token|chatbot|\bml\b)")

# 内容型仓库（图库、合集、教程）不是「项目」，涨星再快也不进榜。
CONTENT_RE = re.compile(
    r"(?i)(图库|图集|壁纸|合集|资源|模板|教程|指南|大全|精选|素材|"
    r"awesome|curated|collection|wallpaper|playbook|cheat|roadmap|"
    r"interview|course|book|notes|prompt\s*list)")


# ---------------- HTTP ----------------

def gh_headers():
    h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    tok = os.environ.get("GITHUB_TOKEN")
    if tok:
        h["Authorization"] = f"Bearer {tok}"
    return h


def http_text(url, timeout=30, retries=2):
    """抓 HTML（趋势榜没有 API，只能解析页面）。"""
    err = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (compatible; ai-data-fetcher)",
                "Accept": "text/html",
            })
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", "replace")
        except Exception as e:
            err = e
            if attempt < retries:
                time.sleep(2 + attempt * 3)
    raise err


# ---------------- 趋势榜 ----------------

def parse_trending(html, window_days):
    """解析 github.com/trending 的 article 块。"""
    out = []
    for art in re.findall(r'<article class="Box-row">(.*?)</article>', html, re.S):
        head = re.search(r'<h2[^>]*>(.*?)</h2>', art, re.S)
        if not head:
            continue
        m = re.search(r'href="/([^"/\s]+/[^"/\s]+)"', head.group(1))
        if not m:
            continue
        repo = m.group(1)
        desc = re.search(r'<p class="col-9[^"]*"[^>]*>\s*(.*?)\s*</p>', art, re.S)
        desc = re.sub(r"<[^>]+>", "", desc.group(1)).strip() if desc else ""
        lang = re.search(r'itemprop="programmingLanguage">([^<]+)<', art)
        total = re.search(r'/stargazers"[^>]*>(?:\s*<svg.*?</svg>)?\s*([\d,]+)', art, re.S)
        gain = re.search(r'([\d,]+)\s*stars?\s*(today|this week)', art)
        if not gain:
            continue
        out.append({
            "repo": repo,
            "gain": int(gain.group(1).replace(",", "")),
            "window_days": window_days,
            "stars": int(total.group(1).replace(",", "")) if total else None,
            "language": lang.group(1) if lang else None,
            "description": desc[:200],
        })
    return out


def fetch_trending():
    """日榜 + 周榜一次抓完。周榜增量用来排名（窗口 7 天，稳），
    日榜增量只当注脚（同一天的一次快照，波动大，不参与排名）。"""
    got = {}
    for window_days, since in ((WINDOW_DAYS, "weekly"), (1, "daily")):
        try:
            html = http_text(f"https://github.com/trending?since={since}")
        except Exception as e:
            print(f"trending {since} failed: {e}", file=sys.stderr)
            continue
        for r in parse_trending(html, window_days):
            e = got.setdefault(r["repo"], {"repo": r["repo"], "stars": r["stars"],
                                           "language": r["language"],
                                           "description": r["description"],
                                           "gain_7d": None, "gain_1d": None})
            e["gain_7d" if window_days == WINDOW_DAYS else "gain_1d"] = r["gain"]
            e["stars"] = e["stars"] or r["stars"]
            e["description"] = e["description"] or r["description"]
    return got


# ---------------- 快照 ----------------

def graphql_snapshot(repos):
    """GraphQL 批量取 star 存量，100 个/次。没有 token 或失败返回 {}。"""
    tok = os.environ.get("GITHUB_TOKEN")
    if not tok:
        return {}
    out = {}
    for i in range(0, len(repos), 100):
        chunk = [r for r in repos[i:i + 100] if "/" in r]
        if not chunk:
            continue
        fields = " ".join(
            f'r{j}: repository(owner:{json.dumps(r.split("/")[0])}, '
            f'name:{json.dumps(r.split("/")[1])}) {{ nameWithOwner stargazerCount forkCount '
            f'createdAt primaryLanguage {{ name }} }}'
            for j, r in enumerate(chunk))
        try:
            d = common.http_json(GRAPHQL, method="POST", payload={"query": f"query {{ {fields} }}"},
                                 headers={"Authorization": f"Bearer {tok}"}, timeout=45)
        except Exception as e:
            print(f"graphql batch failed ({len(chunk)} repos): {e}", file=sys.stderr)
            continue
        data = d.get("data") or {}
        for j in range(len(chunk)):
            node = data.get(f"r{j}")
            if not node or not node.get("stargazerCount"):
                continue
            out[node["nameWithOwner"]] = {
                "stars": node["stargazerCount"],
                "forks": node.get("forkCount"),
                "created_at": (node.get("createdAt") or "")[:10],
                "language": ((node.get("primaryLanguage") or {}).get("name")),
            }
        time.sleep(0.3)
    return out


def rest_snapshot(repos, headers):
    """匿名兜底：逐个 REST 查（60 req/h，只覆盖底座）。"""
    out = {}
    for repo in repos:
        try:
            d = common.http_json(f"{API}/repos/{repo}", headers=headers, timeout=30)
        except Exception as e:
            print(f"rest {repo} failed: {e}", file=sys.stderr)
            continue
        if not d.get("stargazers_count"):
            continue
        out[d.get("full_name", repo)] = {
            "stars": d["stargazers_count"],
            "forks": d.get("forks_count"),
            "created_at": (d.get("created_at") or "")[:10],
            "language": d.get("language"),
        }
        time.sleep(0.2)
    return out


# ---------------- 历史增量 ----------------

def load_series(name):
    path = common.DATA_DIR / "series" / f"{name}.jsonl"
    rows = []
    if not path.exists():
        return rows
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except Exception:
                    pass
    return rows


def window_gain(hist, today, target_days=WINDOW_DAYS):
    """从自有快照取「target_days 天前」的存量，返回 {repo: (gain, window_days)}。

    基准日取最接近 target、且落在 [today-9, today-3] 的一天；找不到就跳过，
    绝不用 1 天的增量冒充 7 天。
    """
    today = datetime.fromisoformat(today) if isinstance(today, str) else today
    by = defaultdict(dict)
    for r in hist:
        if r.get("stars"):
            by[r["repo"]][r["date"]] = r["stars"]
    lo = (today - timedelta(days=target_days + 2)).strftime("%Y-%m-%d")
    hi = (today - timedelta(days=target_days - 2)).strftime("%Y-%m-%d")
    target = today - timedelta(days=target_days)
    out = {}
    tkey = today.strftime("%Y-%m-%d")
    for repo, days in by.items():
        if tkey not in days:
            continue
        cands = [(d, s) for d, s in days.items() if lo <= d <= hi and d < tkey]
        if not cands:
            continue
        d0, s0 = min(cands, key=lambda x: abs(
            (datetime.fromisoformat(x[0]) - target).days))
        wd = (today - datetime.fromisoformat(d0)).days
        if wd < 3:
            continue
        out[repo] = (days[tkey] - s0, wd)
    return out


# ---------------- watchlist ----------------

def read_watchlist():
    path = common.DATA_DIR / "watchlist" / "github_repos.json"
    if not path.exists():
        return []
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        return [r for r in doc.get("repos", []) if "/" in r]
    except Exception:
        return []


def write_watchlist(repos):
    path = common.DATA_DIR / "watchlist" / "github_repos.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"updated_at": common.utc_now_iso(),
                                "repos": list(repos)[:UNIVERSE_CAP]},
                               ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------- 主流程 ----------------

def main():
    try:
        date = common.utc_today()
        today_dt = datetime.fromisoformat(date)
        headers = gh_headers()

        # ---- 1. 三路候选 ----
        trend = {k: v for k, v in fetch_trending().items()
                 if AI_RE.search(v.get("description") or "") or not v.get("description")}
        print(f"trending: {len(trend)} AI repos")

        since = (datetime.now(timezone.utc) - timedelta(days=NEW_REPO_DAYS)).strftime("%Y-%m-%d")
        new_cands = {}
        for q_ in QUERIES:
            q = urllib.parse.quote(f"{q_} created:>{since} stars:>100")
            try:
                res = common.http_json(
                    f"{API}/search/repositories?q={q}&sort=stars&order=desc&per_page={NEW_REPO_SCAN}",
                    headers=headers, timeout=30)
            except Exception as e:
                print(f"search {q_} failed: {e}", file=sys.stderr)
                continue
            for it in res.get("items", []):
                desc = it.get("description") or ""
                if not desc or CONTENT_RE.search(desc):
                    continue
                new_cands[it["full_name"]] = it
            time.sleep(1.0)
        print(f"new repos: {len(new_cands)}")

        seeds = set(CORE_REPOS)
        for q_ in SEED_QUERIES:
            try:
                res = common.http_json(
                    f"{API}/search/repositories?q={urllib.parse.quote(q_)}"
                    f"&sort=stars&order=desc&per_page={SEED_SCAN}",
                    headers=headers, timeout=30)
            except Exception as e:
                print(f"seed {q_} failed: {e}", file=sys.stderr)
                continue
            seeds.update(it["full_name"] for it in res.get("items", []))
            time.sleep(1.0)
        print(f"seed universe: {len(seeds)}")

        # ---- 2. 快照宇宙 ----
        universe = list(dict.fromkeys(
            CORE_REPOS + sorted(seeds) + read_watchlist()
            + list(trend) + list(new_cands)))[:UNIVERSE_CAP]
        snap = graphql_snapshot(universe)
        if not snap:
            print("graphql unavailable, REST fallback (core only)", file=sys.stderr)
            snap = rest_snapshot(CORE_REPOS, headers)

        rows = []
        for repo, s in snap.items():
            row = {"date": date, "repo": repo, "stars": s["stars"], "forks": s.get("forks")}
            if s.get("created_at"):
                row["created_at"] = s["created_at"]
            rows.append(row)
        if not rows:
            raise RuntimeError("no repo snapshot rows")

        # ---- 3. 增量 ----
        gains = window_gain(load_series(SOURCE), date)
        print(f"snapshot: {len(rows)} repos, {len(gains)} with history")

        cands = {}
        for repo, s in snap.items():
            created = s.get("created_at") or ""
            age = max((today_dt - datetime.fromisoformat(created)).days, 0) if created else None
            e = {"repo": repo, "stars": s["stars"], "created_at": created or None,
                 "language": s.get("language"), "age_days": age}
            if age is not None and age <= WINDOW_DAYS:
                e.update(gain=s["stars"], window_days=max(age, 1), signal="new")   # 窗口=全部寿命
            elif repo in gains:
                e.update(gain=gains[repo][0], window_days=gains[repo][1], signal="snapshot")
            elif (trend.get(repo) or {}).get("gain_7d"):
                e.update(gain=trend[repo]["gain_7d"], window_days=WINDOW_DAYS, signal="trending")
            cands[repo] = e

        # 趋势榜里没快照到的（GraphQL 挂了或超上限）：用 GitHub 报的 7 天增量
        for repo, t in trend.items():
            if repo in cands or not t.get("gain_7d"):
                continue
            cands[repo] = {"repo": repo, "stars": t.get("stars"), "created_at": None,
                           "language": t.get("language"), "age_days": None,
                           "gain": t["gain_7d"], "window_days": WINDOW_DAYS,
                           "signal": "trending"}
        # 新建仓库：快照没覆盖的，用建仓以来全部星数当增量
        for repo, it in new_cands.items():
            if repo in cands:
                continue
            created = (it.get("created_at") or "")[:10]
            if not created:
                continue
            age = max((today_dt - datetime.fromisoformat(created)).days, 1)
            if age > NEW_REPO_DAYS:
                continue
            cands[repo] = {"repo": repo, "stars": it.get("stargazers_count"),
                           "created_at": created, "language": it.get("language"), "age_days": age,
                           "gain": it.get("stargazers_count") or 0, "window_days": age,
                           "signal": "new"}

        # ---- 4. 排序 + 写盘 ----
        board = []
        for c in cands.values():
            gain, wd = c.get("gain") or 0, c.get("window_days") or 0
            if wd < MIN_WINDOW or gain < MIN_GAIN or gain / wd < MIN_PER_DAY:
                continue
            desc = (new_cands.get(c["repo"]) or {}).get("description") or ""
            board.append({
                "date": date, "repo": c["repo"], "stars": c.get("stars"),
                "gain": gain, "window_days": wd,
                "gain_1d": (trend.get(c["repo"]) or {}).get("gain_1d"),
                "stars_per_day": round(gain / wd, 1),
                "age_days": c.get("age_days"), "created_at": c.get("created_at"),
                "language": c.get("language"), "signal": c["signal"],
                "description": desc[:160],
            })
        board.sort(key=lambda r: -r["stars_per_day"])
        board = board[:BOARD_KEEP]

        write_watchlist(sorted({r["repo"] for r in rows} | set(trend) | set(new_cands) | seeds))

        common.write_raw(SOURCE, {
            "fetched_at": common.utc_now_iso(),
            "universe": len(universe), "snapshot": len(rows),
            "trending": len(trend), "new_candidates": len(new_cands),
            "growth_top": [{k: r[k] for k in ("repo", "gain", "window_days", "stars_per_day",
                                             "age_days", "signal")} for r in board[:15]],
        })
        added = common.append_series(SOURCE, rows, ["repo"])
        added_g = common.append_series(GROWTH_SERIES, board, ["repo"])
        common.write_health(SOURCE, len(rows) + len(board))
        print(f"{SOURCE}: {len(rows)} snapshot rows ({added} new), "
              f"{len(board)} growth rows ({added_g} new)")
        for r in board[:8]:
            print(f"  {r['stars_per_day']:>7.0f}/d  {r['gain']:>6} in {r['window_days']}d  "
                  f"{r['repo']} ({r['signal']})")
    except Exception as e:
        common.write_health(SOURCE, 0, status="error", error=str(e))
        print(f"{SOURCE} error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
