#!/usr/bin/env python3
"""skills.sh 安装榜 → series skills_sh.jsonl，日级，免 key。

两部分合并到一个 series（键 date+skill，top 榜优先）：
1. 每日 top 榜快照：GET 首页，从 Next.js RSC payload（self.__next_f.push chunks）
   提取 initialSkills（All Time 榜），rank = 榜内名次（1 起）。
2. anthropics/openai 官方 skill 安装量：GET /api/search?q=<owner>&limit=200
   （免 key JSON；上限 200/页，官方 skill 数量在限内），不在 top 榜里的追加、rank=null。
"""

import re
import sys
import time
import urllib.request

import common

SOURCE = "skills_sh"
HOME = "https://www.skills.sh/"
SEARCH = "https://www.skills.sh/api/search?q={owner}&limit=200"
OFFICIAL_OWNERS = ["anthropics", "openai"]
UA = {"User-Agent": "Mozilla/5.0"}

TOP_RE = re.compile(
    r'\{"source":"(?P<source>[^"]+)","skillId":"(?P<skillId>[^"]+)","name":"(?P<name>[^"]*)",'
    r'"installs":(?P<installs>\d+)(?:,"weeklyInstalls":\[[0-9,]*\])?(?:,"isOfficial":(?P<official>true))?')


def parse_leaderboard(html):
    """从首页 RSC payload 提取 All Time 榜，按出现顺序排名，去重。"""
    dec = html.encode().decode("unicode_escape", errors="ignore")
    rows = []
    seen = set()
    for m in TOP_RE.finditer(dec):
        skill = f"{m.group('source')}/{m.group('skillId')}"
        if skill in seen:
            continue
        seen.add(skill)
        rows.append({
            "skill": skill,
            "installs": int(m.group("installs")),
            "official": bool(m.group("official")),
        })
    return rows


def fetch_official(owner):
    d = common.http_json(SEARCH.format(owner=owner), timeout=30)
    return [s for s in d.get("skills", []) if s.get("source", "").startswith(owner + "/")]


def main():
    try:
        date = common.utc_today()
        html = urllib.request.urlopen(
            urllib.request.Request(HOME, headers=UA), timeout=60).read().decode("utf-8", errors="replace")
        top = parse_leaderboard(html)
        if not top:
            raise RuntimeError("no leaderboard skills parsed from home RSC")

        rows = []
        seen = set()
        for i, s in enumerate(top):
            rows.append({"date": date, "skill": s["skill"], "installs": s["installs"],
                         "rank": i + 1, "official": s["official"]})
            seen.add(s["skill"])
        official_raw = {}
        for owner in OFFICIAL_OWNERS:
            skills = fetch_official(owner)
            official_raw[owner] = skills
            for s in skills:
                skill = f"{s['source']}/{s['skillId']}"
                if skill in seen:
                    continue
                seen.add(skill)
                rows.append({"date": date, "skill": skill, "installs": s.get("installs"),
                             "rank": None, "official": True})
            time.sleep(0.3)

        common.write_raw(SOURCE, {"fetched_at": common.utc_now_iso(),
                                  "leaderboard_count": len(top),
                                  "official_search": official_raw,
                                  "html_head": html[:2000]})
        added = common.append_series(SOURCE, rows, ["skill"])
        common.write_health(SOURCE, len(rows))
        print(f"{SOURCE}: {len(rows)} rows ({len(top)} leaderboard + official), {added} new")
    except Exception as e:
        common.write_health(SOURCE, 0, status="error", error=str(e))
        print(f"{SOURCE} error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
