"""data/ 健康检查：各源今日是否出数、行数为零、环比暴跌 >90%。

规则见 ai_data/AGENTS.md「监控」。供 Actions 的 health-check job 使用，
本地也可跑（AI_DATA_DIR 环境变量可改数据目录）。
任一检查失败 → 打印全部失败项并非零退出。

口径说明：
- 「今日出数」看 health 文件的 last_success（要求 36h 内有成功运行），
  不看 series 日期——ornn 的 series 日期是指数日（T+1 结算），
  finance 的是最近交易日，天然落后于运行日。
- 「暴跌」比较 series 最新两个日期的行数，前一日行数 <10 时跳过（小样本噪音）。
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ["AI_DATA_DIR"]) if os.environ.get("AI_DATA_DIR") else ROOT / "data"

STALE_HOURS = 36
DROP_RATIO = 0.1
DROP_MIN_PREV = 10


def check_health_files(failures):
    health_dir = DATA / "health"
    if not health_dir.is_dir():
        failures.append("无 health 目录")
        return
    now = datetime.now(timezone.utc)
    for hf in sorted(health_dir.glob("*.json")):
        h = json.loads(hf.read_text(encoding="utf-8"))
        src = h.get("source", hf.stem)
        if h.get("status") != "ok":
            failures.append(f"{src}: status={h.get('status')} error={h.get('error')}")
            continue
        ls = h.get("last_success")
        if not ls:
            failures.append(f"{src}: 缺 last_success")
            continue
        age_h = (now - datetime.fromisoformat(ls)).total_seconds() / 3600
        if age_h > STALE_HOURS:
            failures.append(f"{src}: 距上次成功 {age_h:.1f}h")
        if not h.get("rows"):
            failures.append(f"{src}: rows=0")


def check_series_drops(failures):
    series_dir = DATA / "series"
    if not series_dir.is_dir():
        return
    for sf in sorted(series_dir.glob("*.jsonl")):
        counts = {}
        for line in sf.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            d = json.loads(line).get("date")
            if d:
                counts[d] = counts.get(d, 0) + 1
        if len(counts) < 2:
            continue
        days = sorted(counts)
        prev, latest = counts[days[-2]], counts[days[-1]]
        if prev >= DROP_MIN_PREV and latest < prev * DROP_RATIO:
            failures.append(f"{sf.stem}: 行数暴跌 {days[-2]}={prev} → {days[-1]}={latest}")


def main():
    failures = []
    check_health_files(failures)
    check_series_drops(failures)
    if failures:
        print("健康检查失败：")
        for f in failures:
            print(" -", f)
        sys.exit(1)
    print("健康检查通过")


if __name__ == "__main__":
    main()
