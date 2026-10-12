---
name: webtool
description: Agent 友好的免费网页搜索与内容获取 CLI。多引擎搜索（Bing/搜狗/百度/Google/Marginalia）+ 榜单聚合 rank（知乎/微博/抖音/B站/HN/GitHub Trending 等 19 源，-q 语义筛选）+ 20 站点站内搜索 site（GitHub/SO/HN/arXiv/CSDN/V2EX 等）+ RSS 订阅 feed（104 精选种子源 + RSSHub 路由库 radar 查询填参 + 增量/坏源登记）+ zen 免费层 LLM 对话（无需 key）+ 正文提取转 markdown/text/json。当用户提到「搜索网页 / 查资料 / 抓网页正文 / 热榜 / 榜单 / 订阅 / RSS / 站内搜索 / 问大模型 / webtool」时触发。
version: 1.8.0
---

# webtool

免费、免 key、零浏览器依赖。正文提取省 token（压缩到原文 ~2%）。

## 命令速查

```sh
webtool search "LLM leaderboard" -n 5       # 多引擎, 默认 bing,sogou,baidu
webtool search "query" -e marginalia         # 长尾独立索引 (小站/老网页)
webtool fetch <url> --max-chars 3000         # 正文提取 → markdown (-f text/json/html)
webtool rank                                 # 榜单清单 (19 源)
webtool rank zhihu weibo -q "汽车"           # BM25 语义筛选 + 跨源重排 (-t 0 只列清单)
webtool feed                                 # 源清单 (7 预设 + 种子/自定义)
webtool feed sspai ithome --new-only         # 抓 feed; --new-only 增量
webtool feed radar 36kr                      # 查 RSSHub 路由库 (站名/域名/路由/参数/分类)
webtool feed instances                       # 公共实例探活 (默认挑最快的可用实例)
webtool feed health                          # 坏源登记表 (失败自动记录, 恢复自动移除)
webtool site github fastapi                  # 站内搜索 (20 站点, site list 查全部)
webtool zen "问题"                           # OpenCode Zen 免费层对话 (无需 key)
webtool config set default_engines bing,sogou
```

## search：多引擎搜索

- 引擎：`bing`（HTML 主通道 + RSS 兜底，cn 直连）/ `sogou`（PC 优先 → 移动端兜底，直出真实 URL）/ `baidu`（TLS 指纹，需 `[full]` extra）/ `google`（**必须代理**，web 429 自动降级 news RSS，文章链还原真实 URL）/ `marginalia`（长尾独立索引）
- `-e` 逗号分隔组合；`--market zh-CN/en-US`；跳转链默认自动解码（`--no-resolve` 关）
- query 要精简：核心实体 + 意图词（`LLM 排行榜`、`fastapi 部署`）；**优先英文**；中文用引擎习惯叫法（`大模型` 而非 `大语言模型`）
- 低质量批带 `💡 quality_hint` 提示——按提示改词重搜，工具不改写 query
- 排序：引擎基础分 × 位置衰减 × 多引擎共识 × BM25 语义 × 实体命中 × 域名先验；广告 ×0.2；`-n` 是硬上限（首轮拉大池 → 过滤 → 不足翻页补拉 → 截质量最高 n 条）

## fetch：正文提取

- trafilatura 四级降级链，HTML → markdown/text/json/html；SPA 壳页自动收割内嵌 SSR state（RENDER_DATA / `__NEXT_DATA__` / `__NUXT__` 框架无关），拿不到时显式报错不吐假正文
- 按 UA 分流的站点拿不到数据：`--profile chrome131_android`（或 `safari18_4_ios`）切真移动 TLS 指纹重试
- `--url-file` 批量；`--raw` 跳过提取；`--with-metadata` 附标题/作者/日期

## rank：榜单聚合

19 源：zhihu / weibo / baidu / douyin / douyin_hot / toutiao / toutiao_hot / bili_hot / bili_rank / bili_word / tieba / sina_hot / douban_movie / netease_music / ithome / hn_official / github_trend / lobsters / reddit。
无参数 = 清单+用法；指定源按源分组**原序**输出（位次 = 真实热度）；`-q` 语义筛选（BM25 本地筛 + 跨源重排，条目带 `source`）；`-t` 阈值默认 0.15，`-t 0` 只列清单不重排。

## feed：RSS 订阅

- 任意 RSS/Atom URL 直接喂；`--add NAME URL [desc]` / `--del NAME` 管理（`~/.webtool/feeds.json`，预设不可删）
- **104 个精选种子源随包分发**（AI 专题/技术社区/大厂博客/前端/安全/学术/版本追踪等 14 类），安装时自动并入，只增不覆盖用户改动（`WEBTOOL_NO_SEED=1` 可关）
- `--new-only` 增量（状态存 `~/.webtool/feed_state.json`）；`-q/-t` 语义筛选同 rank
- **坏源登记**：失败自动入 `~/.webtool/feed_health.json`（403/timeout/shell/parse 分类）；`feed health` 查看；`--retest KEY|all` 复查（恢复即移除）；`--mark KEY [URL] "备注"` 人工登记
- **feed radar**：RSSHub 官方路由库查询（~2069 站 / ~3947 路由，缓存 TTL 7 天）
  ```sh
  webtool feed radar 36kr                       # 搜路由卡片 (含参数说明)
  webtool feed radar 36kr --pick 2 --param category=newsflashes   # 填参直接拉数据
  webtool feed radar 36kr --pick 2 --example    # 用官方示例路径 (免填参)
  webtool feed radar 36kr --pick 2 --top 2      # 用第 2 条真实样例填参
  webtool feed radar --from-url https://space.bilibili.com/946974   # 页面 URL 反推路由
  webtool feed radar 36kr --pick 2 --example --add r36kr           # 落地成订阅源
  ```
  填参只作用于 `--pick` 选中的那条；官网 feed 与 RSSHub 路由会交叉校验，官网 feed 含目标栏目时直接推荐官网（无限流）
- **feed instances**：公共实例探活（默认自动挑响应最快的可用实例；`--instance` 可指定）
- RSSHub 公共实例实测可用：rsshub.rssforever.com / hub.slarker.me / rss.wudifeixue.com / rsshub.isrss.com；429 时轮换实例前缀而非换源（详见 docs/feed-sources.md）

## site：站内搜索

20 站点：github / so / hn / wikipedia / arxiv / csdn / csdn_so / juejin / juejin2 / bilibili / bili2 / sspai / npm / npmjs_github / thepaper / eastmoney / sov2ex / douban / gh_search / v2ex。
`webtool site list` 查全部；`docs/custom-sites.md` 有 JSON 扩展格式（`~/.webtool/sites/*.json`，可覆盖内置）。

## zen：免费层 LLM 对话（无需 key）

OpenCode Zen 公开模式（`Authorization: Bearer public`），免费层有形状校验——默认只发 bash+read 两个空壳工具定义（请求体省 98%，分类器只认这两个工具名）。

```sh
webtool zen "你好"                          # 默认 big-pickle
webtool zen "问题" --model ling-3.1-flash-free
webtool zen --list-free                     # 实测免费模型清单 (不硬编码, 实时拉)
webtool zen --list-models --check           # 全量模型 + 逐个实发验证
webtool zen "问题" --system "只回 JSON" --tool-choice none
```

模型上下架频繁（3 周内 4 上 9 下），不要凭记忆报模型名，先 `--list-free`。

## 通用约定（v1.6.1 标准化）

- `-n` 条数 / `-f` 格式（`md`≡`markdown`、`txt`≡`text`，大小写不敏感）/ `-o` 落盘（按 `-f` 补扩展名，目录自动命名，`-o -` 强制 stdout）/ `--no-cache` / `--no-proxy` / `--proxy URL`
- 退出码：0 成功 / 2 用法错误（提示走 stderr，落盘文件只含数据）
- 缓存 TTL：search 60s / fetch 10s / 跳转解析 10min / zen 模型清单 1h（防重复查询暴露行为模式；命中标 `"cache"`，未命中 `fresh`）

## 反探测（v1.8.0 统一策略）

全部命令出网一律走 transport 浏览器指纹，无任何裸 UA：

- **cffi 通道**（主路径）：curl_cffi impersonate，UA/TLS/HTTP2/sec-ch-ua 由指纹库同源生成，调用方只补导航头，**不手写 UA**（会与 TLS 指纹错位）
- **urllib 兜底 / REST API**：显式套档案浏览器 UA + Accept-Language（Python-urllib 默认 UA 是一级机器人特征）
- 指纹轮换池 chrome131 win/mac/linux + safari18_4_ios；搜狗移动通道 chrome131_android；传输层直连优先、失败才探活代理重试
- zen 用 `opencode/...` 客户端 UA（免费层分类器认这个串）

## 连通与代理

- 传输层直连优先；失败且配置了代理 → 探活（HEAD bing generate_204）后代理重试
- `webtool proxy set http://127.0.0.1:2080` 配置；google / docs.rsshub.app 这类被墙源必须代理，未配置时立即说明不空等
- `webtool engines test` 实发体检各引擎；`webtool cache clear/info`；`webtool blocklist show/add/remove/reset`（23 内置黑名单）

## Agent 使用要点

1. 优先 fetch 而非啃原始 HTML——省 token 的核心
2. 报错自带处置建议（换引擎 / 切 `--profile` / 配代理 / 装 `[full]`），照做即可
3. google 结果 `channel: news` = 新闻通道，链接已还原原文 URL，直接 fetch
4. feed radar 拿到路由卡片后，`--example` 或 `--param` 填参可直接看数据再决定 `--add`
5. zen 报 403 FreeTierError = 模型已下架或免费层校验变化，`--list-free` 刷新
