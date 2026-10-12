# ai_data 项目规则

每日 AI 行业量化数据取数系统。数据清单见 [SOURCES.md](SOURCES.md)。
最终消费者是本地的早报 agent：每天读 `data/series/` 写日报、出图表。

## 架构（已定，勿偏离）

- **抓取**：一个源一个独立 Python 文件（`fetchers/<source>.py`），无抽象层、无框架。依赖只用标准库 + requests
- **存储**：两层
  - `data/raw/<source>/<YYYY-MM-DD>.json` — 原始快照，只增不改（审计底账、重解析依据）
  - `data/series/<source>.jsonl` — 时间序列，每天 append 一行（日报/图表只读这里）
  - `data/health/<source>.json` — 每源健康状态：`{"source","last_success","rows","status"}`
- **调度**：GitHub Actions cron（美国机房，被墙源直连）。matrix 每源一个 job，`fail-fast: false`；保留 `workflow_dispatch` 手动补抓；每个 job 设 `timeout-minutes`
- **监控**：workflow 末尾 health-check job（今日有无数据、行数为零、环比暴跌 >90% → 失败）；Actions 失败邮件；早报 agent 读数时自查 freshness
- **密钥**：GitHub Secrets，绝不入库

## 抓取器契约

1. 无参数运行：`python fetchers/<source>.py`
2. 写三个产物：raw 快照、series 追加一行、health 文件
3. 失败时非零退出 + 打印错误摘要；不允许"抓到空数据但正常退出"
4. series 行必须含 `date` 字段（`YYYY-MM-DD`），字段命名 snake_case
5. 每个源有频率声明（目前全部日级）

## 本地/云端分工

- 云端（Actions）：抓数、写 data/、commit
- 本地：只 `git pull` 后消费，**不在本地写 data/**，避免合并冲突
- 本地调试抓取器时输出到临时目录，不提交

## 网络注意

- 本机被墙的源见 SOURCES.md 网络可达性表；本地调试走代理，Actions 上直连
- HuggingFace 一律走 hf-mirror.com

## 什么时候升级架构（迁移触发器，勿提前优化）

出现以下情况之一再考虑换基础设施（抓取器代码和数据契约不变，原样迁移）：
- 出现分钟级频率需求 → 高频部分迁常驻 worker
- 单日 raw 超几十 MB → raw 层迁对象存储
- 消费方变多/要跨源 JOIN → series 灌 DuckDB/Postgres
- 缺一天数据有实际损失 → 引入 Dagster/Prefect 级编排
