---
name: webtool
description: Agent 友好的免费网页搜索与正文获取 CLI。多引擎搜索（Bing/搜狗/百度/Google/Marginalia）+ 10 站点站内搜索（GitHub/SO/HN/arXiv 等）+ 正文提取转 markdown/text/json。当用户提到「搜索网页 / 查资料 / 抓网页正文 / 网页转 markdown / 站内搜索 / webtool」时触发。
version: 1.5.6
---

# webtool

免费、免 key、零浏览器依赖。正文提取省 token（压缩到原文 ~2%）。

## 命令

```sh
webtool search "LLM leaderboard" -n 5      # 多引擎搜索, 默认 bing,sogou,baidu
webtool search "query" -e marginalia        # 长尾独立索引 (小站/老网页, 中文覆盖弱)
webtool search "AI 新闻" -e google          # 加 google (必须代理, 可能降级新闻)
webtool fetch <url>                         # 正文提取 → markdown (-f text/json/html)
webtool fetch <url> --max-chars 3000        # 截断; --url-file 批量
webtool site github fastapi                 # 站内搜索: github/so/hn/arxiv/wikipedia/csdn/juejin/bilibili/sspai/npm
webtool config set default_engines bing,sogou   # 持久化配置
```

## 关键参数

- 通用：`-n` 条数 `-f json/text/markdown` `--no-cache`（放子命令前）`--no-proxy` `--proxy URL`
- search：`-e` 引擎 `--keep-ad` `--no-resolve`（关跳转链解码，默认开）`--no-dedupe` `--no-semantic` `--no-blocklist`
- config：`list/get/set/unset`，可配 `proxy` `default_engines` `default_format` `timeout` `engine_proxy.<engine>` 等

## 引擎与代理

| 引擎 | 通道 | 代理 |
|---|---|---|
| bing | HTML（cn 直连，浏览器一致排序）→ RSS 降级 | 直连 |
| sogou | 网页 HTML，会话预热 | 直连 |
| baidu | curl_cffi TLS 指纹 | 直连，需 `full` extra |
| google | Web → 429 自动降级 news RSS | **必须**：未配置或探活失败（1.5s TCP）即静默跳过 |

## 缓存 TTL（v1.5.6 起收紧）

search 60s / fetch 10s / resolve 10min——防短窗口重复查询暴露行为模式，数据新鲜度优先。缓存命中标注 `"cache": "<engine>"`，未命中为 `fresh`。重复搜同一词 60s 内直接秒回；跨任务重抓会真实请求。

## 排序与补量（v1.5.6）

- **排序**：`weight = 引擎基础分(google .95/bing .90/baidu .80/sogou .75) × 位置分(RRG) × 多引擎共识(×1.35/额外引擎) × BM25 语义分 × 实体命中 × 词典域名先验`，广告 ×0.2。BM25 本地分词（英文按词、中文 2-gram），无外部 API。`quality: good/fair/poor` 按批内断层自适应（poor = sem < max(0.12, top×0.35)）
- **返回条数**：`-n` 是硬上限。引擎首轮拉 max(n,15) 进大池 → 去重/黑名单过滤 → 不足翻页补拉（每引擎最多 2 页）→ 排序后截取**质量最高的 n 条**
- 补量触发时输出 `topup: {fetched}`（json）/ "翻页补拉 X 条"（text/md）；补不足则诚实短返回，不硬凑

## Agent 使用要点

1. **query 精简**：核心实体 + 意图词（`LLM 排行榜`、`fastapi 部署`），别堆修饰词
2. **优先英文**：`LLM leaderboard`；中文用引擎习惯叫法（`大模型` 而非 `大语言模型`）
3. 低质量批会带 `💡` 提示（`quality_hint` 字段，json 模式同样输出）——按建议改词重搜，别硬解析 poor 结果
4. google 结果带 `channel: news` 时是新闻，news.google.com 跳转链已默认解成原文 URL，直接 fetch 正文
5. 报错自带处置建议（换引擎、补装 `[full]` extra），照做即可
6. 优先 fetch 而非啃原始 HTML——这是省 token 的核心
