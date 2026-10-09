---
name: webtool
description: Agent 友好的免费网页搜索与正文获取 CLI。多引擎搜索（Bing/搜狗/百度/Google News）+ 10 站点站内搜索（GitHub/SO/HN/arXiv 等）+ 正文提取转 markdown/text/json，去广告省 token 98%+，支持持久化配置。当用户提到「搜索网页 / 查资料 / 抓网页正文 / 网页转 markdown / 站内搜索 / webtool」时触发。
version: 1.2.0
---

# webtool

免费、免 key、零浏览器依赖（百度走 curl_cffi TLS 指纹）。结果为 LLM 优化格式，token 开销极低。

## 功能

| 命令 | 功能 |
|---|---|
| `webtool search <q>` | 多引擎搜索：Bing RSS/搜狗/百度/Google News；跨引擎去重、黑名单、广告过滤、语义加权排序 |
| `webtool fetch <url>` | 正文提取：HTML→纯净 markdown/text/json(/html)，去广告导航，`--max-chars` 截断，批量并发 |
| `webtool site <site> <q>` | 站内搜索（官方 API）：github/so/hn/wikipedia/arxiv/csdn/juejin/bilibili/sspai/npm；与 search 一样走去重/黑名单/权重过滤；JSON 配置可扩展 |
| `webtool config` | 持久化配置：默认引擎/格式/权重阈值/各过滤开关/单引擎代理 |
| `webtool proxy` | 代理配置；断线自动降级直连 |
| `webtool blocklist` | 黑名单管理（内置 21 个内容农场） |

## 常用示例

```sh
webtool search "fastapi 教程" -e bing,baidu -n 5     # 指定引擎+条数
webtool search "q" --min-weight 0.8                  # 权重阈值过滤
webtool fetch <url> -f json --with-metadata          # 带元数据 json
webtool site github fastapi                          # GitHub 仓库搜索
webtool config set default_engines bing,baidu        # 持久化默认引擎
webtool proxy set http://127.0.0.1:2080              # 配代理
```

## 关键参数

- **search / site**：`-e` 引擎(site 无) `-n` 条数 `-f json/text/markdown` `--min-weight` 权重阈值 `--no-blocklist` `--no-weight-filter` `--keep-ad`(仅search) `--no-dedupe` `--no-semantic` `--block/--allow` 临时黑白名单 `--no-proxy`
- **fetch**：`-f markdown/text/json/html` `--max-chars` `--raw` `--url-file` 批量
- **config**：`list` / `get <k>` / `set <k> <v>` / `unset <k>`，写 `~/.webtool/config.json`
  可配项：`proxy` `min_weight` `weight_filter` `blocklist` `ad_filter` `dedupe` `semantic` `default_engines` `default_format` `timeout` `cache` `engine_proxy.<engine>`
- **全局**：`--proxy` `--no-cache`（须放子命令前）

## 三格式说明

search/site 输出 json/text/markdown 三格式信息量对齐；过滤统计（广告/黑名单/权重/去重的剔除条数+撤销参数）三种格式都有：json 在 `filters_applied` 字段，text 在末尾 `—` 行，markdown 在结尾 `**过滤统计**` 块。

## 配置优先级

`config` 文件是默认值，命令行参数运行时临时覆盖。改过的配置立即写盘，下次调用生效。

## Agent 使用要点

1. 结果字段以实际输出为准：`weight`/`sem_score`/`filters_applied`/`errors`
2. 报错自带处置建议（如引擎冷却→换引擎、被风控→装 curl_cffi），照做即可，别硬重试
3. 优先 fetch 而非啃原始 HTML —— 这就是省 token 的核心（实测压缩到原文 1.6%）
4. 低质量结果太多 → 加 `--min-weight` 或 `blocklist add`；有 exa 等付费搜索时 webtool 作兜底
