---
name: webtool
description: Agent 友好的免费网页搜索与正文获取 CLI。多引擎搜索（Bing/搜狗/百度/Google News）+ 10 站点站内搜索（GitHub/SO/HN/arXiv 等）+ 正文提取转 markdown/text/json，去广告省 token 98%+，支持持久化配置。当用户提到「搜索网页 / 查资料 / 抓网页正文 / 网页转 markdown / 站内搜索 / webtool」时触发。
version: 1.3.0
---

# webtool

免费、免 key、零浏览器依赖（百度走 curl_cffi TLS 指纹）。结果为 LLM 优化格式，token 开销极低。

## 功能

| 命令 | 功能 |
|---|---|
| `webtool search <q>` | 多引擎搜索：Bing RSS/搜狗/百度/Google News；跨引擎去重、黑名单、广告过滤、实体加权语义排序 |
| `webtool fetch <url>` | 正文提取：HTML→纯净 markdown/text/json(/html)，去广告导航，`--max-chars` 截断，批量并发 |
| `webtool site <site> <q>` | 站内搜索（官方 API）：github/so/hn/wikipedia/arxiv/csdn/juejin/bilibili/sspai/npm；JSON 配置可扩展 |
| `webtool config` | 持久化配置：默认引擎/格式/权重阈值/各过滤开关/单引擎代理 |
| `webtool proxy` | 代理配置；断线自动降级直连 |
| `webtool blocklist` | 黑名单管理（内置 21 个内容农场） |

## 常用示例

```sh
webtool search "LLM 排行榜" -e bing,sogou -n 5      # 精简 query 优先!
webtool search "大模型 排行榜" --min-weight 0.3      # 显式提阈值
webtool fetch <url> -f json --with-metadata          # 带元数据 json
webtool site github fastapi                          # GitHub 仓库搜索
webtool config set default_engines bing,sogou        # 持久化默认引擎
```

## 关键参数

- **search / site**：`-e` 引擎(site 无) `-n` 条数 `-f json/text/markdown` `--min-weight` 权重阈值 `--no-blocklist` `--no-weight-filter` `--no-retry`(关质量提示) `--keep-ad`(仅search) `--no-dedupe` `--no-semantic` `--block/--allow` 临时黑白名单 `--no-proxy`
- **fetch**：`-f markdown/text/json/html` `--max-chars` `--raw` `--url-file` 批量
- **config**：`list` / `get <k>` / `set <k> <v>` / `unset <k>`，写 `~/.webtool/config.json`
  可配项：`proxy` `min_weight` `weight_filter` `blocklist` `ad_filter` `dedupe` `semantic` `default_engines` `default_format` `timeout` `cache` `engine_proxy.<engine>`
- **全局**：`--proxy` `--no-cache`（须放子命令前）

## 权重与过滤 (v1.3)

每条结果：`weight = 引擎基础分 × 名次衰减 × 多引擎共识 × 语义乘区 × 实体命中 × 域名先验`，字段 `weight`/`sem_score`(0-1 余弦)/`quality`(good/fair/poor)。

| 过滤层 | 默认 | 关闭 |
|---|---|---|
| 广告 | 剔除 | `--keep-ad` 只标记 |
| 黑名单 | 21 内容农场 | `--no-blocklist` |
| 权重 | **剔 quality=poor**（断层自适应：与批内头部断层即判噪声，至少留 1 条；全剔时退回权重最高 1 条） | `--no-weight-filter`；`--min-weight N` 改按 sem 绝对阈值 |

低质量召回（全体 sem 偏低）不自动改写 query——改写可能引歧义；输出 `quality_hint` 字段 + `💡` 行提醒优化 query 词。

## Agent 使用要点

1. **query 用精简写法**：「核心实体 + 意图词」，如 `LLM 排行榜`、`fastapi 部署`；别堆「2026年最新最强」修饰词——中文引擎分词会被带偏，召回词典/百科噪声
2. **搜索词优先用英文**：`LLM leaderboard`、`FastAPI deployment`——英文按空格分词无歧义；中文技术词退而求其次用引擎习惯叫法：`大模型` 而非 `大语言模型`（bing 对后者整串分词失败）
3. 输出看 `quality_hint`：有提示就按建议改词重搜，别硬解析 poor 结果
4. 字段以实际输出为准：`weight`/`sem_score`/`quality`/`filters_applied`/`errors`
5. 报错自带处置建议（如引擎冷却→换引擎、被风控→装 curl_cffi），照做即可
6. 优先 fetch 而非啃原始 HTML——省 token 的核心（实测压缩到原文 1.6%）
