#!/usr/bin/env python3
"""HuggingFace 开源模型下载量（含分支 / 量化分支）→ 三个 series，日级。

为什么不再用一张固定名单（2026-11-01 重写）：
人工名单必然过期——新 checkpoint 常常发在另一个 repo（DeepSeek-V4.1-Flash-1017）、
量化分支散落在 unsloth / lmstudio-community / ISTA-DASLab 这些第三方 org 里。
名单一过期，看板上的「谁在涨」就是错的。所以改成：**抓取前先判断，名单自己长。**

每天四个动作：
1. 发现。官方 org（下载量 top-60 + 最近发布 20 条）× trending 兜底 × 量化榜
   （gguf/awq/gptq/mlx/fp8），三路都捞，捞到的进观察名单。
2. 判断。给每个 repo 算 variant（base / quant:* / precision:* / distill / merge /
   uncensored）、family（挂哪个基座，优先读 base_model tag，没有就剥后缀）、
   scope（是不是语言模型，剔除 embedding/rerank 这类下载榜噪音）。
3. 采集。观察名单逐条取数（按上次数据里的下载量排序，最多 320 条），
   新进的自动补进来，之后天天跟踪——覆盖只增不减。
4. 汇总。按 family 把「基座 + 所有分支」加总，得到真实用量。

口径（重要）：
- 每个 repo 的 `downloads` 是「近 30 天下载量」滚动窗口，不是累计、不是日增量；
  两个日期的差值是「下载速度的变化」。`downloads_alltime` 才是累计，2026-11-01 起记录。
- 分支与基座的下载量分别计数（下 GGUF 不会算成下基座），family 汇总可相加，
  含义是「这条家族总共被拉取多少次」，不是「多少人在用」。

走 hf-mirror.com（官方域名本机被墙，API 兼容；Actions 上同样直连可用）。
HF_API_BASE 环境变量可换官方域名调试。
"""

import json
import os
import re
import sys
import time
from collections import defaultdict

import common

SOURCE = "hf_downloads"
MIRROR = "https://hf-mirror.com/api/models"
API = os.environ.get("HF_API_BASE", MIRROR).rstrip("/")
EX_REPO = ("?expand[]=downloads&expand[]=downloadsAllTime&expand[]=likes"
           "&expand[]=createdAt&expand[]=tags")
EX_LIST = EX_REPO + "&expand[]=pipeline_tag"

WATCH_PATH = common.DATA_DIR / "watchlist" / "hf_models.json"

TODAY = common.utc_today()

# ---------- 抓取范围 ----------

# 官方 org（供给侧）：下载量 top-60 + 最近发布 20 条各扫一遍
SEED_ORGS = [
    "deepseek-ai", "Qwen", "moonshotai", "zai-org", "MiniMaxAI", "openai",
    "meta-llama", "mistralai", "google", "microsoft", "nvidia", "allenai",
    "tencent", "baidu", "stepfun-ai", "openbmb", "XiaomiMiMo", "inclusionAI",
    "ByteDance-Seed", "LiquidAI", "thinkingmachines", "arcee-ai", "nex-agi",
    "ibm-granite", "CohereLabs", "swiss-ai", "rednote-hilab", "LGAI-EXAONE",
]

# 发版最勤的几家，单独扫「最近发布」——新模型往往零下载发布，只靠下载榜会漏
ACTIVE_ORGS = {"deepseek-ai", "Qwen", "moonshotai", "zai-org", "MiniMaxAI", "openai",
               "meta-llama", "mistralai", "google", "nvidia", "thinkingmachines", "tencent"}

TRENDING_FILTERS = ["text-generation", "image-text-to-text"]
QUANT_FILTERS = ["gguf", "awq", "gptq", "mlx", "fp8"]

# 语言模型口径：embedding / rerank / asr / 图像分类在下载榜上体量极大，
# 但和「模型行业趋势」不是一回事——记录，但不进面板
LLM_PIPELINE = {"text-generation", "image-text-to-text", "any-to-any"}
NON_LLM_NAME = re.compile(
    r"(?i)(embedding|embed-|rerank|reranker|colbert|bge[-_]|gme[-_]|guard|"
    r"moderation|reward-model|classifier|sentence-|discriminator|"
    r"(?:^|[-_])(electra|bert|roberta|deberta|vit|clip|siglip|blip|florence|"
    r"whisper|wav2vec|hubert|musicgen|bark|tts|asr|audio|voice|speech|"
    r"music|song|sing|diffusion|flux|sdxl|sam)(?:$|[-_]))"
)

# 老名单（2026-11-01 之前手写的 18 个），保留是为了让既有 series 不断档
LEGACY_SEED = [
    "deepseek-ai/DeepSeek-V4.1-Flash", "moonshotai/Kimi-K3", "Qwen/Qwen3.8-27B",
    "zai-org/GLM-5.3-Flash", "zai-org/GLM-5.3", "MiniMaxAI/MiniMax-H3",
    "MiniMaxAI/MiniMax-M3", "openai/gpt-oss-120b", "openai/gpt-oss-20b",
    "meta-llama/Llama-4-Scout-17B-16E-Instruct",
    "mistralai/Devstral-Small-2-24B-Instruct-2512",
    "deepseek-ai/DeepSeek-V4-Flash-0731", "deepseek-ai/DeepSeek-V3.2",
    "moonshotai/Kimi-K2.6", "Qwen/Qwen3.5-9B",
    "meta-llama/Meta-Llama-3.1-8B-Instruct",
    "mistralai/Mistral-7B-Instruct-v0.3", "deepseek-ai/DeepSeek-R1",
]

QUANT_MARK = re.compile(
    r"(?i)[-_](gguf|awq|gptq|mlx|fp8|fp4|int4|int8|w4a16|w8a8|bnb|nvfp4|mxfp8|exl2|hqq)\b")
# 只放「出现即等于量化分支」的 tag。fp8 / int8 这种 tag 官方原版也打
# （DeepSeek、GLM 的原生权重就是 FP8），拿来判分支会把基座判成量化，
# 所以 fp8/fp4 只在仓库名后缀里生效（-FP8 / -FP4 才是重打包）。
QUANT_TAGS = {"gguf", "awq", "gptq", "mlx", "exl2", "hqq", "w4a16", "w8a8", "bnb"}
PRECISION_MARK = re.compile(r"(?i)[-_](bf16|fp16|fp32)\b")  # 全精度重打包，不算量化
DISTILL_MARK = re.compile(r"(?i)(distill|蒸馏)")
EDIT_MARK = re.compile(r"(?i)(uncensored|abliterated|obliterated)")
MERGE_MARK = re.compile(r"(?i)([-_]merge|merge[-_]|merged)")

NEW_DAYS = 90           # createdAt 在 90 天内算「新模型」
MIN_DOWNLOADS = 120_000  # 发现门槛：老 repo 低于这个量不值得天天抓
MIN_DOWNLOADS_NEW = 20_000  # 新发布（≤90 天）门槛放低，别漏首发
MAX_TRACK = int(os.environ.get("HF_MAX_TRACK", 1200))  # 每天跟踪多少条（按 owner 批量取，多跟踪几条几乎不加请求）
MAX_WATCH = 2_000       # 观察名单上限，超了按下载量裁掉尾部
THREADS = int(os.environ.get("HF_THREADS", 4))  # 并发数：官方 API 超过 4 就 429
BUDGET_SEC = int(os.environ.get("HF_BUDGET_SEC", 660))  # 取数预算，超了就用已抓到的收工
DISCOVER_BUDGET_SEC = int(os.environ.get("HF_DISCOVER_BUDGET_SEC", 240))  # 发现阶段预算
MIN_NEW_DOWNLOADS = 2_000


# ---------- 判断 ----------

def raw_tags(meta):
    return [str(t) for t in (meta.get("tags") or [])]


def base_model_of(tags):
    """tags 里的 base_model:xxx / base_model:quantized:xxx，优先前者。

    注意保留大小写：HF 的 base_model tag 里 repo id 大小写是准的，
    统一 lower 会把同一个家族拆成两个键。
    """
    plain = quant = None
    for t in tags:
        low = t.lower()
        if low.startswith("base_model:quantized:"):
            quant = t.split(":", 2)[2]
        elif low.startswith("base_model:finetune:"):
            continue
        elif low.startswith("base_model:"):
            plain = t.split(":", 1)[1]
    return plain or quant


def strip_suffix(name):
    """剥掉量化 / 精度 / 位宽后缀，得到家族名。"""
    out = name
    for _ in range(3):
        new = re.sub(r"(?i)[-_](gguf|awq|gptq|mlx|fp8|fp4|bf16|fp16|mxfp8|nvfp4|"
                     r"int4|int8|w4a16|w8a8|bnb|exl2|hqq|\d+bit)$", "", out)
        if new == out:
            break
        out = new
    return out


def variant_of(repo, tags):
    """变体分类。tag 匹配用小写，名字匹配靠正则的 (?i)。"""
    name = repo.split("/")[-1]
    ts = {t.lower() for t in tags}
    m = QUANT_MARK.search(name)
    if m:
        return "quant:" + m.group(1).lower()
    for t in sorted(QUANT_TAGS):
        if t in ts:
            return "quant:" + t
    m = PRECISION_MARK.search(name)
    if m:
        return "precision:" + m.group(1).lower()
    if DISTILL_MARK.search(name):
        return "distill"
    if MERGE_MARK.search(name):
        return "merge"
    if EDIT_MARK.search(name):
        return "uncensored"
    if any(t.startswith("base_model:finetune:") for t in ts):
        return "finetune"
    return "base"


def family_of(repo, tags):
    base = base_model_of(tags)
    if base and base != repo:
        return strip_suffix(base)
    return strip_suffix(repo)


AUDIO_TAGS = {"text-to-audio", "text-to-speech", "text-to-music", "music", "audio",
              "audio-to-audio", "automatic-speech-recognition", "voice-cloning"}
IMAGE_TAGS = {"text-to-image", "image-to-image", "text-to-video", "image-to-video",
              "image-classification", "object-detection", "image-segmentation",
              "depth-estimation", "image-feature-extraction"}


def scope_of(repo, tags, pipeline):
    """是不是语言模型。单条 repo 接口不给 pipeline_tag（常为 null），
    那种情况只靠名字排除，不能当成非语言模型——否则所有量化分支都会被漏掉。"""
    if NON_LLM_NAME.search(repo.split("/")[-1]):
        return "other"
    ts = {t.lower() for t in tags}
    if ts & (AUDIO_TAGS | IMAGE_TAGS):
        return "other"
    if pipeline:
        return "llm" if pipeline in LLM_PIPELINE else "other"
    return "llm"


def age_days(created):
    if not created or len(created) < 10:
        return 10_000
    try:
        from datetime import date
        y, m, d = (int(x) for x in created[:10].split("-"))
        return (date.fromisoformat(TODAY) - date(y, m, d)).days
    except Exception:
        return 10_000


# ---------- IO ----------

def load_watch():
    if WATCH_PATH.exists():
        try:
            return json.loads(WATCH_PATH.read_text(encoding="utf-8")).get("models", {})
        except Exception:
            return {}
    return {}


def save_watch(models):
    WATCH_PATH.parent.mkdir(parents=True, exist_ok=True)
    doc = {"updated_at": common.utc_now_iso(), "count": len(models), "models": models}
    WATCH_PATH.write_text(
        json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")


def last_known_downloads():
    """从 series 里读每个 repo 最近一次的下载量，用来决定今天先抓谁。

    放在 series 而不是观察名单里，是为了让观察名单的 diff 只有增删，
    不出现「一千行每天全变」的噪音。
    """
    path = common.DATA_DIR / "series" / f"{SOURCE}.jsonl"
    out = {}
    if not path.exists():
        return out
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                r = json.loads(line)
            except Exception:
                continue
            m, v = r.get("model"), r.get("downloads")
            if m and v is not None:
                out[m] = max(out.get(m, 0), v)
    return out


def _is_new(created):
    return bool(created) and age_days(created) <= NEW_DAYS


def drop_today(series):
    """清掉当天的行再重写：同一天重跑（补抓/改口径）以最后一次为准。

    否则 append_series 的幂等会把当天第一次跑的部分数据永久钉住。
    """
    path = common.DATA_DIR / "series" / f"{series}.jsonl"
    if not path.exists():
        return 0
    kept, dropped = [], 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except Exception:
            kept.append(line)
            continue
        if r.get("date") == TODAY:
            dropped += 1
        else:
            kept.append(line)
    if dropped:
        path.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
    return dropped


def list_models(query):
    try:
        return common.http_json(API + query + EX_LIST, timeout=60) or []
    except Exception as e:
        print(f"  list failed {query[:70]}: {e}", file=sys.stderr)
        return []


# ---------- 主流程 ----------

def main():
    global API
    try:
        # 官方域名在美国机房直连可用，本机被墙——不通就回落到镜像
        if API != MIRROR:
            try:
                common.http_json(f"{API}?limit=1", timeout=15, retries=1)
            except Exception:
                print(f"  ⚠ {API} 不通，回落 {MIRROR}", file=sys.stderr)
                API = MIRROR

        watch = load_watch()
        before = len(watch)
        routes = {}
        hint = {}  # 发现时看到的下载量：首轮还没有 series 时用它排序

        for repo in LEGACY_SEED:
            watch.setdefault(repo, {"added": TODAY, "why": "legacy", "variant": None,
                                    "family": None, "scope": None})

        def offer(m, why):
            rid = m.get("id")
            if not rid:
                return
            tags = raw_tags(m)
            var = variant_of(rid, tags)
            sc = scope_of(rid, tags, m.get("pipeline_tag"))
            if sc != "llm" and rid not in watch:
                return  # 非语言模型不进名单，避免 embedding 榜刷屏
            if rid not in watch:
                dl = m.get("downloads") or 0
                fresh = age_days(m.get("createdAt")) <= NEW_DAYS
                if dl < (MIN_DOWNLOADS_NEW if fresh else MIN_DOWNLOADS):
                    return
                watch[rid] = {"added": TODAY, "why": why}
            watch[rid].update({"variant": var, "family": family_of(rid, tags), "scope": sc})
            if m.get("createdAt"):
                watch[rid].setdefault("created", m["createdAt"][:10])
            if m.get("pipeline_tag"):
                watch[rid]["pipeline"] = m["pipeline_tag"]
            hint[rid] = m.get("downloads") or 0
            routes.setdefault(rid, set()).add(why)

        discover_deadline = time.time() + DISCOVER_BUDGET_SEC

        def out_of_time():
            return time.time() > discover_deadline

        org_cache = {}  # owner -> 该 owner 的下载榜，采集阶段直接复用

        # 1) 官方 org：下载量 top（全部）+ 最近发布（只看最活跃的几家）
        for org in SEED_ORGS:
            if out_of_time():
                print("  ⚠ 发现阶段预算用完，剩余 org 跳过", file=sys.stderr)
                break
            batch = list_models(f"?author={org}&sort=downloads&direction=-1&limit=60")
            org_cache[org] = batch
            for m in batch:
                offer(m, "org_top")
            if org in ACTIVE_ORGS:
                for m in list_models(f"?author={org}&sort=createdAt&direction=-1&limit=20"):
                    offer(m, "org_new")

        # 2) trending 兜底：不看体量，只看现在在涨
        for tag in TRENDING_FILTERS:
            if out_of_time():
                break
            for m in list_models(f"?filter={tag}&sort=trendingScore&direction=-1&limit=60"):
                offer(m, "trending")

        # 3) 量化榜：第三方量化分支主要从这儿进来
        for qf in QUANT_FILTERS:
            if out_of_time():
                break
            for m in list_models(f"?filter={qf}&sort=downloads&direction=-1&limit=50"):
                offer(m, f"quant_{qf}")

        # 4) 家族键归一：base_model tag 是别人写的，跟本仓里 repo id 的大小写
        #    不一定一致，按观察名单里的真实 id 校正一遍
        canon = {k.lower(): k for k in watch}
        fam_index = {}
        for k, meta in watch.items():
            f = meta.get("family") or ""
            if f:
                fam_index.setdefault(f.split("/")[-1].lower(), f)

        def resolve_family(fam):
            """先对齐真实 repo id，再按前缀挂回已知家族。

            量化仓库常把基座名塞进自己的名字（ISTA-DASLab/Qwen3.8-Flash-Next-GSQ-RCO-GGUF）
            却不打 base_model tag，不挂回去就会各家各算一个家族。
            """
            if fam.lower() in canon:
                return canon[fam.lower()]
            short = fam.split("/")[-1].lower()
            for k in range(len(short) - 1, 3, -1):
                hit = fam_index.get(short[:k])
                if hit:
                    return hit
            return fam

        for meta in watch.values():
            meta["family"] = resolve_family(meta.get("family") or "")

        # 5) 名单太长就裁尾部（按已知下载量），保证每天的抓取量可控
        if len(watch) > MAX_WATCH:
            known = last_known_downloads()
            keep = sorted(watch.items(),
                          key=lambda kv: -(known.get(kv[0], 0)))[:MAX_WATCH]
            watch = dict(keep)

        # 6) 采集：按「上次已知下载量」排序（没有记录的用发现时的量垫底），
        #    新发布的排在最前面——宁可多抓新模型，也不能漏
        known = last_known_downloads()
        ranked = sorted(watch.items(),
                        key=lambda kv: -(known.get(kv[0], hint.get(kv[0], 0)) or 0))
        picked = [r for r, _ in ranked[:MAX_TRACK]]
        fresh = [r for r, m in ranked
                 if _is_new(m.get("created"))][:40]
        picked = list(dict.fromkeys(picked + fresh))

        # 按 owner 批量取：一次 listing 拿 100 条，比逐条 GET 少 3~4 倍请求。
        # 逐条 GET 600 次会把官方 API 打到 429，反而丢数据。
        # 发现阶段已经拉过的 org 直接复用缓存，只有第三方量化 org 需要新拉。
        by_owner = defaultdict(list)
        for repo in picked:
            by_owner[repo.split("/")[0]].append(repo)

        deadline = time.time() + BUDGET_SEC
        timed_out, fetched = [], {}

        def fetch_owner(owner, repos):
            if time.time() > deadline:
                timed_out.extend(repos)
                return owner, {}
            batch = org_cache.get(owner)
            if batch is None:
                try:
                    batch = list_models(f"?author={owner}&sort=downloads&direction=-1&limit=100")
                except Exception as e:
                    print(f"  skip owner {owner}: {e}", file=sys.stderr)
                    return owner, {}
            want = set(repos)
            return owner, {m["id"]: m for m in batch if m.get("id") in want}

        from concurrent.futures import ThreadPoolExecutor, as_completed
        with ThreadPoolExecutor(max_workers=THREADS) as ex:
            futs = [ex.submit(fetch_owner, o, rs) for o, rs in by_owner.items()]
            for f in as_completed(futs):
                o, got = f.result()
                fetched.update(got)

        missing = [r for r in picked if r not in fetched]
        if missing:
            # 榜单只给前 100 条，个别老仓库会掉出去，逐条补
            def fetch_one(repo):
                if time.time() > deadline:
                    timed_out.append(repo)
                    return None
                try:
                    return repo, common.http_json(f"{API}/{repo}{EX_REPO}",
                                                  timeout=30, retries=2)
                except Exception as e:
                    print(f"  skip {repo}: {e}", file=sys.stderr)
                    return None

            with ThreadPoolExecutor(max_workers=2) as ex:
                for res in ex.map(fetch_one, missing[:200]):
                    if res:
                        fetched[res[0]] = res[1]

        skipped = len(picked) - len(fetched)
        if timed_out:
            print(f"  ⚠ 预算用完，{len(timed_out)} 条没抓到（次日按优先级补）", file=sys.stderr)
        if skipped:
            print(f"  ⚠ 跳过 {skipped}/{len(picked)} 条（接口没返回或取数失败）",
                  file=sys.stderr)

        raw, rows = {}, []
        for repo in picked:
            d = fetched.get(repo)
            if not d or d.get("downloads") is None:
                continue
            meta = watch[repo]
            tags = raw_tags(d)
            var = variant_of(repo, tags)
            fam = resolve_family(family_of(repo, tags))
            sc = scope_of(repo, tags, d.get("pipeline_tag") or meta.get("pipeline"))
            dl = d.get("downloads")
            meta.update({"variant": var, "family": fam, "scope": sc, "seen": TODAY,
                         "created": (d.get("createdAt") or "")[:10] or None})
            raw[repo] = {"downloads": dl, "alltime": d.get("downloadsAllTime"),
                         "created_at": d.get("createdAt"), "variant": var, "family": fam}
            rows.append({
                "date": TODAY,
                "model": repo,
                "owner": repo.split("/")[0],
                "family": fam,
                "variant": var,
                "role": "root" if var == "base" else "branch",
                "scope": sc,
                "downloads": dl,
                "downloads_alltime": d.get("downloadsAllTime"),
                "likes": d.get("likes"),
                "created_at": (d.get("createdAt") or "")[:10] or None,
                "discovered_by": meta.get("why"),
                "trending": "trending" in routes.get(repo, ()),
            })

        if not rows:
            raise RuntimeError("no rows")

        # 7) 家族汇总：基座 + 分支（量化 / 精度 / 微调）
        groups = {}
        for r in rows:
            if r["downloads"] is not None:
                groups.setdefault(r["family"], []).append(r)
        fam_rows = []
        for fam, rs in groups.items():
            roots = [r for r in rs if r["role"] == "root"]
            branches = [r for r in rs if r["role"] == "branch"]
            quant = [r for r in branches if (r["variant"] or "").startswith("quant")]
            top_b = max(branches, key=lambda r: r["downloads"] or 0) if branches else None
            fam_rows.append({
                "date": TODAY,
                "family": fam,
                "scope": rs[0]["scope"],
                "root": max(roots, key=lambda r: r["downloads"] or 0)["model"] if roots else None,
                "root_downloads": sum(r["downloads"] or 0 for r in roots),
                "branch_downloads": sum(r["downloads"] or 0 for r in branches),
                "quant_downloads": sum(r["downloads"] or 0 for r in quant),
                "n_branches": len(branches),
                "n_quant": len(quant),
                "top_branch": top_b["model"] if top_b else None,
                "top_branch_downloads": (top_b["downloads"] or 0) if top_b else 0,
                "newest": max((r["created_at"] or "") for r in rs) or None,
            })

        # 8) 新模型表
        new_rows = [{
            "date": TODAY, "model": r["model"], "owner": r["owner"],
            "created_at": r["created_at"], "family": r["family"],
            "variant": r["variant"], "downloads": r["downloads"],
            "downloads_alltime": r["downloads_alltime"],
            "trending": r["trending"],
        } for r in rows
            if r["scope"] == "llm" and age_days(r["created_at"]) <= NEW_DAYS
            and (r["downloads"] or 0) >= MIN_NEW_DOWNLOADS]

        common.write_raw(SOURCE, {
            "fetched_at": common.utc_now_iso(),
            "orgs": SEED_ORGS,
            "watchlist_size": len(watch),
            "ranked": len(ranked),
            "models": raw,
        })
        for s_ in (SOURCE, "hf_family", "hf_new_models"):
            d_ = drop_today(s_)
            if d_:
                print(f"  {s_}: 覆盖当天旧行 {d_}")
        a1 = common.append_series(SOURCE, rows, ["model"])
        a2 = common.append_series("hf_family", fam_rows, ["family"])
        a3 = common.append_series("hf_new_models", new_rows, ["model"])
        save_watch(watch)
        common.write_health(SOURCE, len(rows))
        print(f"{SOURCE}: {len(rows)} repos (watch {before}->{len(watch)}), "
              f"{len(fam_rows)} families, {len(new_rows)} new; series +{a1}/+{a2}/+{a3}")
    except Exception as e:
        common.write_health(SOURCE, 0, status="error", error=str(e))
        print(f"{SOURCE} error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
