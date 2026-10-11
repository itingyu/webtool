---
name: webtool
description: Agent 友好的免费网页搜索与正文获取 CLI。多引擎搜索（Bing/搜狗/百度/Google/Marginalia）+ 榜单聚合 rank（知乎/微博/抖音/B站/HN/GitHub Trending 等 18 源，-q 语义筛选）+ 18 站点站内搜索 site（GitHub/SO/HN/arXiv/V2EX/CSDN 等）+ RSS 订阅 feed（任意源 + RSSHub 路由 + feed radar 规则库查询 + 增量/坏源登记）+ 正文提取转 markdown/text/json。当用户提到「搜索网页 / 查资料 / 抓网页正文 / 热榜 / 榜单 / 订阅 / RSS / 站内搜索 / webtool」时触发。
version: 1.8.0
---

# webtool

免费、免 key、零浏览器依赖。正文提取省 token（压缩到原文 ~2%）。

## 命令

```sh
webtool search "LLM leaderboard" -n 5      # 多引擎搜索, 默认 bing,sogou,baidu
webtool search "query" -e marginalia        # 长尾独立索引 (小站/老网页, 中文覆盖弱)
webtool search "AI 新闻" -e google          # 加 google (必须代理, 429 自动降级新闻)
webtool fetch <url>                         # 正文提取 → markdown (-f text/json/html)
webtool fetch <url> --max-chars 3000        # 截断; --url-file 批量
webtool rank                                # 榜单清单+用法 (18 源)
webtool rank zhihu weibo -q "汽车"          # 语义筛选: 纯榜源 BM25 本地筛 + 跨源重排; -t 0 只列清单不重排
webtool feed                                # RSS 清单+用法 (7 预设 + 103 随包精选源; 支持任意 feed URL)
webtool feed sspai ithome --new-only        # 抓 feed; --new-only 增量只看新条目
webtool feed radar 36kr                     # 查 RSSHub 官方路由库(2069站/3947路由): 参数说明+示例+真实样例+填参出订阅URL
webtool feed radar 36kr --pick 2 --param category=newsflashes   # 选定路由+填占位符, 直接拉数据输出
webtool feed radar --from-url https://space.bilibili.com/946974   # 用 radar.source 反推路由
webtool feed instances                       # 公共实例探活(哪几个今天还活着)
webtool feed health                         # 坏源登记表 (失败自动记录, 恢复自动移除)
webtool site github fastapi                 # 站内搜索: github/so/hn/arxiv/wikipedia/csdn/juejin/bilibili/sspai/npm/thepaper/eastmoney/v2ex...
webtool config set default_engines bing,sogou   # 持久化配置
```

## rank / feed / site 分工

- **rank**：榜单/趋势型源（18 源：zhihu/weibo/baidu/tieba/douyin×2/toutiao/bili×3/sina_hot/douban_movie/netease_music/ithome/hn_official/github_trend/lobsters/reddit）。无参数/`list` = 清单+用法；指定源按源分组**原序**输出（位次=真实热度）；`-q` 语义筛选：支持搜索的源透传站内过滤，纯榜源拉榜后 BM25 阈值筛选（`-t` 默认 0.15）+ 跨源重排；每条带 `source` 字段
- **feed**：RSS/Atom 时序订阅。7 预设官方 feed + 103 随包精选源（`src/webtool/data/feeds.seed.json`，安装时自动并入 `~/.webtool/feeds.json`，只增不覆盖本地改动）+ 任意 URL；`--add NAME URL [desc]` / `--del NAME` 自定义管理（~/.webtool/feeds.json，预设不可删）；`--new-only` 增量（状态 ~/.webtool/feed_state.json）；`-q/-t` 语义筛选同 rank。**坏源登记**：失败自动入 `~/.webtool/feed_health.json`；`feed health` 查看（403/timeout/shell/parse 分类）；`--retest KEY|all` 复查（恢复即移除）；`--mark KEY [URL] "备注"` 人工登记
- **feed radar**：RSSHub **官方路由目录** docs.rsshub.app/routes.json（2069 站 / 3947 路由，缓存 ~/.webtool/cache/rsshub_routes.json TTL 7 天）。每张卡片给：**官网栏目页 + 官方 feed + 覆盖判定**（`官网` 是把 RSSHub 路径的"实例/<namespace>/"换成官网域名得到的栏目页，如 `/36kr/newsflashes` → `https://www.36kr.com/newsflashes`，**是 HTML 栏目页不是 feed**，别混为一谈）、**官方 feed + 覆盖判定**（探测 /feed /rss/atom.xml 等 8 条路径，www 与裸域都试——实测 36kr.com/feed 是 HTML 而 www.36kr.com/feed 才是 feed；7 天缓存。判据不是"有没有 feed"而是**含不含目标栏目**：统计官网 feed 条目链接的栏目分布，与路由 topFeeds[].siteUrl 的路径前缀对照，输出 `✓ 官网已含该栏目 /xxx (N 条)` / `✗ 官网不含该栏目 —— 需 RSSHub 路由` / `~ 全站流，无该栏目自己的排序`。实测 36氪官网 feed 含 /newsflashes 20 条，与 RSSHub 路由同源，借实例是白付可用性风险）、路由模板、**参数必填/选填 + 参数说明**（取自 parameters 字段，2681 条带枚举表）、**官方 example 路径**、**topFeeds 真实样例**（2314 条，带标题+源页面 URL）、features 踩坑标记（⚠反爬 333 / 需Puppeteer 85 / 需配置 125，默认跳过需必填配置的）。搜索面：站名/域名/路由名/模板/参数名/参数说明/分类。**两段式**：`webtool feed radar <kw>` 纯搜索，列卡片（序号 + 模板 + 参数必填选填 + 官方 example + topFeeds 真实样例 + URL 模板形态与直连形态），模板行**始终原样**；`--pick <序号|模板子串>` 选定**一条**（不给则取 heat 最高并提示其余序号），`--param` 只灌进选中那条，**不改写模板**，随后**交叉校验**：官网 feed 与 RSSHub 路由并发各拉一遍（RSSHub 侧多实例并发取先到的），比条目 URL 集合的重叠率，判定"官网给不给得了这个栏目"，再据此决定取数源（一致率 ≥60% 且含该栏目 → 用官网 feed，否则用 RSSHub）；`--no-xcheck` 跳过。取数数据按 `-f/-n` 输出（失败会依次换可用公共实例）。填参三种方式：`--param K=V`（可重复，缺必填参数明确报错）、`--example`（借官方示例）、`--top N`（借第 N 条真实样例，直接抄现成参数）；`--from-url <网页URL>` 用 radar.source 模式反推（无规则时自动降级为按域名搜）；`--cat <分类>` 按分类过滤；`--instance` 指定实例前缀（默认自动探活挑延迟最低的）。`--add NAME` 直接把填好的 URL 落进 feeds.json
- **feed instances**：公共实例探活（探测 /36kr/newsflashes，缓存 1h）。公共实例可用性逐日变化，别信文档信探活
- **feed radar（Radar 规则库降级路径）**：（1310 站点 / 5284 条可订阅路由，缓存 ~/.webtool/cache/radar_rules.json TTL 7 天）。`feed radar <关键词>` 按域名/站名/路由标题模糊匹配，输出 `[域名] 站名 | 标题` + target 路由模板（如 `/36kr/hot-list/:category`）；实例前缀 + target 填实参 = 订阅 URL，配 `--add` 落源
- **RSSHub 兼容**：路由就是普通 URL，直接喂或 `--add`。可用公共实例实测 4 个（rsshub.rssforever.com / hub.slarker.me / rss.wudifeixue.com / rsshub.isrss.com，详见 docs/feed-sources.md）；429 时轮换实例前缀而非换源；官方 rsshub.app 有 CF 挑战不可直用
- **site**：关键词站内搜索型源，见 `webtool site list`
- 连通策略（rank/feed）：能直连直连；直连失败且配置了全局代理 → 自动探活代理（HEAD bing generate_204），可用则代理重试

## 反探测（v1.8.0 统一策略）

全部命令出网一律走 transport 浏览器指纹，无任何裸 UA：

- **cffi 通道**（search/fetch/rank/feed/site 主路径）：curl_cffi impersonate，UA/TLS/HTTP2/sec-ch-ua 全部由指纹库同源生成；调用方只补 sec-fetch/referer 等导航头，**不手写 UA**（手写会与 TLS 指纹错位）
- **urllib 兜底 / REST API**（github/so/hn/sov2ex 等）：显式套指纹档案浏览器 UA + Accept-Language —— Python-urllib 默认 UA 是一级机器人特征
- 指纹轮换池：chrome131 win/mac/linux + safari18_4_ios，同引擎同进程固定；搜狗移动通道 chrome131_android（TLS+UA 全 Android）
- 意义：所有命令的请求在服务端看来与真人浏览器一致，降低 403/429/限速

## 关键参数（v1.6.1 标准化）

- 通用（全子命令统一）：`-n` 条数 `-f` 格式（`md`/`txt` 别名，值大小写不敏感）`-o` 输出文件（按 `-f` 补扩展名；目录自动命名；`-o -` 强制 stdout）`--no-cache` `--no-proxy` `--proxy URL`
- search：`-e` 引擎（逗号分隔）`--market` `--keep-ad` `--no-resolve`（关跳转链解码，默认开）`--no-dedupe` `--no-semantic` `--no-blocklist` `--block/--allow` 临时黑白名单（可多次）
- fetch：`--profile chrome131_android` 切真移动 TLS 指纹（移动站/按 UA 分流站点拿不到数据时用）`--max-chars` `--raw` `--with-metadata` `--url-file` 批量
- rank：`-q` 语义筛选 `-t` 阈值（默认 0.15；`-t 0` = 只列清单不过滤不重排）
- feed：`--new-only` 增量 `--add/--del` 源管理 `health/--retest/--mark` 坏源登记 `radar <kw>` 规则库查询
- config：`list/get/set/unset`，可配 `proxy` `default_engines` `default_format` `timeout` `engine_proxy.<engine>` 等

## SPA 站点（fetch 增强）

壳页不等于没数据：头条 RENDER_DATA、Next.js `__NEXT_DATA__`、Nuxt `__NUXT__` 等 SSR 内嵌 state 会被自动收割（框架无关），解出正文或内容列表——json 模式带 `extract: embedded-state` 与 `spa_note` 标注。收割没拿到时再试 `--profile chrome131_android` 换移动指纹。

## 引擎与代理

| 引擎 | 通道 | 代理 |
|---|---|---|
| bing | RSS 优先（cn 直连）→ HTML 自动降级 | 直连 |
| sogou | 网页 HTML，会话预热 | 直连 |
| baidu | curl_cffi TLS 指纹 | 直连，需 `full` extra |
| google | Web → 429 自动降级 news RSS | **必须**：未配置或探活失败（1.5s TCP）即静默跳过 |

## 缓存 TTL

search 60s / fetch 10s / resolve 10min / feed 热数据——防短窗口重复查询暴露行为模式。命中标注 `"cache": "<engine>"`，未命中 `fresh`。

## 排序与补量

- **排序**：`weight = 引擎基础分(google .95/bing .90/baidu .80/sogou .75) × 位置分(RRG) × 多引擎共识(×1.35) × BM25 语义分 × 实体命中 × 词典域名先验`，广告 ×0.2。BM25 本地分词（英文按词、中文 2-gram），无外部 API。`quality: good/fair/poor` 按批内断层自适应
- **返回条数**：`-n` 是硬上限。引擎首轮拉 max(n,15) 进大池 → 去重/黑名单 → 不足翻页补拉（每引擎最多 2 页）→ 排序后截取质量最高的 n 条

## Agent 使用要点

1. **query 精简**：核心实体 + 意图词（`LLM 排行榜`、`fastapi 部署`），别堆修饰词
2. **优先英文**：`LLM leaderboard`；中文用引擎习惯叫法（`大模型` 而非 `大语言模型`）
3. 低质量批会带 `💡` 提示（`quality_hint` 字段）——按建议改词重搜，别硬解析 poor 结果
4. google 结果带 `channel: news` 时是新闻，跳转链已默认解成原文 URL，直接 fetch 正文
5. 报错自带处置建议（换引擎、切 `--profile` 指纹、补装 `[full]` extra），照做即可
6. 优先 fetch 而非啃原始 HTML——这是省 token 的核心
