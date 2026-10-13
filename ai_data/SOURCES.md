# AI 行业数据取数清单

> 每日抓取的 AI 相关量化数据源。筛选原则：接口稳定（官方 API 优先）、日级粒度、对早报有信息增量。
> 最后更新：2026-09-19

## 已在跑（存量）

| 源 | 内容 | 备注 |
|---|---|---|
| opencode.ai/data | 各模型 token 用量榜、日用量序列 | 存于 `state/usage_*.json` |
| OpenRouter | 各模型用量、token 定价、上下文长度 | 官方 API |

## 新增清单（10 项）

| # | 源 | 抓什么 | 接入方式 | 备注 |
|---|---|---|---|---|
| 2 | 算力价格 | GPU 时租价格日线，两层：市场报价 + 成交结算指数 | ① **Shadeform** 免 key API 聚合 19 家云厂商挂牌价（替代单独抓 Lambda/Crusoe/Nebius）② vast.ai / RunPod / TensorDock 免 key API（散户市场 min/median/max）③ **Ornn OCPI** 成交指数（api.ornnai.com 免 key 5 型号，彭博+ICE 基准） | 不抓：国内平台、AWS/Azure/GCP（二期月度快照）；参考实现 gpu-pricing-tracker |
| 3 | GitHub 日报 | ① 核心项目 star/fork 日增 ② 近期新项目（近 7 天创建、增速最快的 AI 仓库）③ anthropics/skills、openai/skills 官方仓库 | GitHub REST API | 配 token 更稳 |
| 4 | HuggingFace | ① 核心开源模型下载量（当红旗舰+上代存量+锚点，名单在 fetcher 里换季维护）② 社区热门改造 top 20（text-generation 下载榜剔除官方 org，动态换代） | hf-mirror.com（国内镜像，API 兼容） | 官方域名本机被墙 |
| 5 | 金融市场 | 股价+市值：NVDA / MSFT / GOOG / META / 阿里 / 百度；期货：纳指100(NQ)、标普500(ES)；国债：美债 10Y / 2Y | stooq 免费 CSV；FRED 官方 API（国债） | |
| 6 | Polymarket | ① 本月最大市值公司 ② 本年底最大市值公司 ③ 最强 AI 模型系列（月度+年度） | 官方 gamma API，需代理 | 市场名单执行时逐个确认 |
| 7 | Cloudflare Radar | AI 爬虫 UA 流量趋势、robots.txt 封锁率、AI 域名热度榜 | 官方 API（免费 token） | 用法待定，先抓存着；UA 口径注意仿冒噪音 |
| 8 | MCP 生态 | 官方 Registry 总量/日增/新上架名单 + Smithery 使用量榜 | registry.modelcontextprotocol.io 免 key API；Smithery 页面 | |
| 9 | skills.sh | skills 安装榜、anthropics/openai 官方 skill 安装量 | 公开 search API（免 key JSON） | |
| 10 | Meta 广告库 | AI 公司在投广告数、新素材、投放地区（EU 区有曝光量级） | 官方 Ad Library API（需开发者 token） | 盯 OpenAI/Anthropic/Google/Perplexity/Mistral/字节等广告主主页 |
| 11 | Ornn OTPI（token 价格指数） | 各厂商 token 每日成交结算价（$/M tokens，成交量加权）：OpenAI / Anthropic / Google / DeepSeek | api.ornnai.com/api/otpi 免 key（4 家厂商、近 1 个月窗口，自己每天攒历史） | 2026-06 才开始结算的新指数；与 OpenRouter 挂牌价互补（挂牌 vs 成交） |

## 已排除（明确不抓）

status page、HN、HF org 监控、npm/PyPI/Docker、Ollama、IDE 插件装机量、arXiv、App Store、Reddit、Civitai、Wikipedia、SEC EDGAR、Stack Overflow、CoinGecko、招聘监控、微博/知乎/B站、Artificial Analysis、LiveBench/SEAL、Google 广告透明中心（二期再说）、LMArena（2026-10-13 下线：arena.ai ToS 明文禁止自动抓榜 + Cloudflare 拦机房 IP；模型强弱口径由 Polymarket「最强模型」市场兜底）。

## 参考仓库（只参考实现，不作数据源）

- cherielilili/gpu-pricing-tracker — 6 家 GPU 供应商每日价格（CSV 历史）
- andreashen/openrouter-watch — OpenRouter 定价/排名历史快照
- leoncuhk/awesome-llm-bench — SWE-bench/Terminal-Bench 等榜单日更
- PurpleHaze2320/coding-agent-heat-index — AI 编程工具热度日榜
- Socialpranker/token-history — 模型实际 token 用量日史

## 网络可达性（本机实测 2026-09）

- 直连通：GitHub API、opencode.ai、OpenRouter、hf-mirror.com、registry.modelcontextprotocol.io、smithery.ai、skills.sh、api.ornnai.com（Ornn 指数）、console.vast.ai、api.runpod.io、console.tensordock.com、api.shadeform.ai
- 需代理：huggingface.co、Polymarket、Wikipedia、CoinGecko、Meta graph API、Google 广告透明中心、TikTok 广告库
- GitHub Actions（美国机房）以上全部直连，天然解决代理问题
