---
name: webtool
description: Agent 友好的免费网页搜索与正文获取 CLI。多引擎搜索（Bing/搜狗/百度/Google News）+ 10 站点站内搜索（GitHub/SO/HN/arXiv 等）+ 正文提取转 markdown/json，去广告省 token 98%+。当用户提到「搜索网页 / 查资料 / 抓网页正文 / 网页转 markdown / 站内搜索 / webtool」时触发。
version: 1.1.0
---

# webtool

免费、免 key、零浏览器依赖。结果为 LLM 优化格式，token 开销极低。

## 功能

| 命令 | 功能 |
|---|---|
| `webtool search <q>` | 多引擎搜索：Bing RSS/搜狗/百度/Google News；自动去重、黑名单、广告过滤、语义加权排序 |
| `webtool fetch <url>` | 正文提取：HTML→纯净 markdown/text/json，去广告导航，`--max-chars` 截断，批量并发 |
| `webtool site <site> <q>` | 站内搜索（官方 API）：github/so/hn/wikipedia/arxiv/csdn/juejin/bilibili/sspai/npm，JSON 配置可扩展 |
| `webtool proxy` | 代理配置；断线自动降级直连 |
| `webtool blocklist` | 黑名单管理（内置 21 个内容农场） |

## 常用示例

```sh
webtool search "fastapi 教程" -e bing,baidu -n 5     # 指定引擎+条数
webtool search "q" --min-weight 0.8                  # 权重阈值过滤
webtool fetch <url> -f json --with-metadata          # 带元数据 json
webtool site github fastapi                          # GitHub 仓库搜索
webtool proxy set http://127.0.0.1:2080              # 配代理
```

## 关键参数

- **search**：`-e` 引擎(逗号分隔) `-n` 每引擎条数 `--min-weight` 权重阈值 `--no-blocklist` `--no-weight-filter` `--keep-ad` `--no-dedupe` `--no-semantic` `--no-proxy` `-f json/text`
- **fetch**：`-f markdown/text/json/html` `--max-chars` `--raw` `--url-file` 批量
- **全局**：`--proxy` `--no-cache`（须放子命令前）

## Agent 使用要点

1. 结果字段以实际输出为准：`weight`/`sem_score`/`filters_applied`/`errors`
2. 报错自带处置建议（如引擎冷却→换引擎），照做即可，别硬重试
3. 优先 fetch 而非啃原始 HTML —— 这就是省 token 的核心
4. 有 exa 等付费搜索时 webtool 作兜底；SPA 页 fetch 空会带 hint，此时换方案
