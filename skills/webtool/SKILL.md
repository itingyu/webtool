---
name: webtool
description: 网页搜索与内容获取 CLI。多引擎搜索 + 榜单聚合 rank（知乎/微博/抖音/B站/HN/GitHub Trending 等 19 源）+ 20 站点站内搜索 site + RSS 订阅 feed（RSSHub 路由库 radar 查询填参、增量、坏源登记）+ zen 免费层 LLM 对话 + 正文提取转 markdown/text/json。当用户提到「搜索网页 / 查资料 / 抓网页正文 / 热榜 / 榜单 / 订阅 / RSS / 站内搜索 / 问大模型 / webtool」时触发。
version: 1.8.0
---

# webtool

## 命令速查

```sh
webtool search "LLM leaderboard" -n 5       # 多引擎, 默认 bing,sogou,baidu
webtool search "query" -e marginalia         # 长尾独立索引 (小站/老网页)
webtool fetch <url> --max-chars 3000         # 正文提取 → markdown (-f text/json/html)
webtool rank                                 # 榜单清单 (19 源)
webtool rank zhihu weibo -q "汽车"           # 语义筛选 + 跨源重排 (-t 0 只列清单)
webtool feed                                 # 源清单 (7 预设 + 种子/自定义)
webtool feed sspai ithome --new-only         # 抓 feed; --new-only 增量
webtool feed radar 36kr                      # 查 RSSHub 路由库
webtool feed instances                       # 公共实例探活
webtool feed health                          # 坏源登记表
webtool site github fastapi                  # 站内搜索 (20 站点, site list 查全部)
webtool zen "问题"                           # 免费层 LLM 对话, 无需 key
webtool config set default_engines bing,sogou
```

## search

- 引擎：bing（直连）/ sogou（直连）/ baidu（需 `[full]` extra）/ google（**必须代理**，429 自动降级 news RSS，结果 `channel: news` 且链接已还原原文 URL，直接 fetch）/ marginalia
- `-e` 逗号分隔组合；跳转链默认自动解码（`--no-resolve` 关）
- query 精简：核心实体 + 意图词；优先英文；中文用引擎习惯叫法（`大模型` 而非 `大语言模型`）
- 低质量批带 `💡 quality_hint`，按提示改词重搜

## fetch

- HTML → markdown/text/json/html；SPA 壳页自动收割内嵌 SSR state，拿不到时显式报错
- 按 UA 分流的站点：`--profile chrome131_android`（或 `safari18_4_ios`）切移动指纹重试
- `--url-file` 批量；`--raw` 跳过提取；`--with-metadata` 附标题/作者/日期

## rank

19 源：zhihu / weibo / baidu / douyin / douyin_hot / toutiao / toutiao_hot / bili_hot / bili_rank / bili_word / tieba / sina_hot / douban_movie / netease_music / ithome / hn_official / github_trend / lobsters / reddit。
无参数 = 清单+用法；指定源按源分组原序输出；`-q` 语义筛选（BM25 + 跨源重排，条目带 `source`）；`-t` 默认 0.15，`-t 0` 只列清单不重排。

## feed

- 任意 RSS/Atom URL 直接喂；`--add NAME URL [desc]` / `--del NAME`（`~/.webtool/feeds.json`，预设不可删）
- 104 个种子源随包分发（安装时自动并入，只增不覆盖；`WEBTOOL_NO_SEED=1` 关）
- `--new-only` 增量；`-q/-t` 同 rank
- 坏源失败自动登记：`feed health` 查看；`--retest KEY|all` 复查（恢复即移除）；`--mark KEY [URL] "备注"` 人工登记
- feed radar（RSSHub 官方路由库，缓存 7 天）：
  ```sh
  webtool feed radar 36kr                       # 搜路由卡片
  webtool feed radar 36kr --pick 2 --param category=newsflashes   # 填参直接拉数据
  webtool feed radar 36kr --pick 2 --example    # 官方示例路径 (免填参)
  webtool feed radar 36kr --pick 2 --top 2      # 用第 2 条真实样例填参
  webtool feed radar --from-url <页面URL>        # 反推路由
  webtool feed radar 36kr --pick 2 --example --add r36kr   # 落地成订阅源
  ```
  填参只作用于 `--pick` 选中的那条；官网 feed 含目标栏目时优先推荐官网
- feed instances：实例探活，默认自动挑最快的
- 公共实例可用：rsshub.rssforever.com / hub.slarker.me / rss.wudifeixue.com / rsshub.isrss.com；429 时轮换实例前缀

## site

20 站点：github / so / hn / wikipedia / arxiv / csdn / csdn_so / juejin / juejin2 / bilibili / bili2 / sspai / npm / npmjs_github / thepaper / eastmoney / sov2ex / douban / gh_search / v2ex。
JSON 扩展格式见 `docs/custom-sites.md`（`~/.webtool/sites/*.json`，可覆盖内置）。

## zen

```sh
webtool zen "你好"                    # 默认 big-pickle
webtool zen "问题" --model ling-3.1-flash-free
webtool zen --list-free               # 免费模型清单 (实时拉, 不硬编码)
webtool zen "问题" --system "只回 JSON" --tool-choice none
```

模型上下架频繁，别凭记忆报模型名，先 `--list-free`。报 403 FreeTierError = 模型已下架，刷新清单。

## 通用约定

- `-n` 条数 / `-f` 格式（`md`≡`markdown`、`txt`≡`text`，大小写不敏感）/ `-o` 落盘（按 `-f` 补扩展名，目录自动命名，`-o -` 强制 stdout）/ `--no-cache` / `--no-proxy` / `--proxy URL`
- 退出码：0 成功 / 2 用法错误（提示走 stderr）
- 缓存 TTL：search 60s / fetch 10s / 跳转解析 10min / zen 模型清单 1h

## 注意

- 出网全走浏览器指纹（UA/TLS 由 impersonate 同源生成），传输层直连优先、失败才探活代理重试
- google / docs.rsshub.app 被墙，必须代理：`webtool proxy set http://127.0.0.1:2080`；未配置时相关命令立即说明不空等
- 报错自带处置建议（换引擎 / 切 `--profile` / 配代理 / 装 `[full]`），照做即可
- 优先 fetch 而非啃原始 HTML
