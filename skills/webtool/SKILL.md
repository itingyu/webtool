---
name: webtool
description: 网页搜索、抓正文、看热榜、订阅 RSS、站内搜索、爬取文档站。触发：搜网页/查资料、抓页面、读 PDF、下文件、看热榜、订阅 RSS、站内搜索、爬文档站、webtool。
version: 0.0.2
---
# webtool

`webtool <命令>`。最终口径看 `webtool -h` 和 `webtool <命令> -h`；这里只讲怎么选、怎么用。

## 选命令

| 想做的事 | 命令 |
|---|---|
| 全网搜 | `webtool search "词"` |
| 搜某个站内部 | `webtool site <站点> "词"` |
| 读一个网页 / PDF | `webtool fetch <url>` |
| 把文档站读下来 | `webtool crawl <url>` |
| 看热榜 | `webtool rank [源...]` |
| 订阅/抓 RSS | `webtool feed [源]` |
| 代理/分流/证书 | `webtool proxy ...` |

## search：全网搜索

```bash
webtool search "关键词" -n 5            # 默认 zh 组合，近 15 天
webtool search "关键词" -A              # 不限时间
webtool search "关键词" -S 7d -U 2026-10-01
webtool search "词" -s bing,sogou       # -s 只接引擎名
webtool search "词" -p en               # 预设 zh|en|direct（plugins engines presets）
webtool search "词" --fallback          # 结果不足才补跑免 key 语义引擎，默认关
webtool search -l                       # 列 9 个引擎（站点清单用 webtool site）
```

- 默认引擎 `bing,sogou,baidu,so360`；Google 必须走代理。
- `-n` 每引擎条数；`-j` 并发 1–16（默认按源数，上限 4）；`-b a.com,!b.com|off` 黑名单。
- `-O passthrough|strip|strict` 控制 `site:`、`intitle:`、`-词` 等操作符透传。
- `search -s github` 必错：站点是独立链路，会提示改用 `site`。

## site：站内搜索

```bash
webtool site                     # 列 20 个站点
webtool site github "fastapi"
webtool site juejin "Python" -n 5
webtool site wikipedia 量子计算 -L en
webtool site sspai "效率" -S 90d  # 默认不限时间，给了才筛
```

## fetch：正文/文件/PDF

```bash
webtool fetch <url> -f markdown      # 默认 text；markdown 最适合喂模型
webtool fetch <url> -R               # 原始 HTML
webtool fetch <url> -S               # 附带 JSON-LD/OG 结构化字段
webtool fetch <url> -F name,offers.price,availability
webtool fetch <url> -L               # 抽站内链接，供 crawl 用
webtool fetch <url> -M               # 正文加不可信边界，防提示注入
webtool fetch <url.pdf> -g 1-5       # 本地 PDF 抽文本，选页
webtool fetch <url> -s 目录/          # 存盘：网页存 HTML，二进制存原文件
```

- 批量：`-u urls.txt` 或 `cat urls.txt | webtool fetch -`；`-r` 断点续跑；`-j 4` 分片下载。
- `-x auto|trafilatura|readability|boilerplate|inscriptis` 换提取器。
- `-v local|auto|parallel|exa|firecrawl` 换取正文通道（local 免配额）。
- `-p auto|direct|代理名|完整URL` 单次线路；`-P` 单次直连；`-M` 给正文加不可信边界。
- 区别：`-s` 存源文件，`-o` 存解析结果；`-o -` 强制 stdout。

## rank：热榜

```bash
webtool rank                         # 只列 19 个源（默认 5 源带 *）
webtool rank zhihu weibo douyin -n 5 # 显式给源才拉榜
webtool rank -q "AI"                 # 不给源时跑默认 5 源，本地筛+跨源重排
webtool rank -q "芯片" --cluster      # 同一事件跨平台合并
webtool rank zhihu --no-url          # 清掉链接
```

- `-n` 每源条数（默认 20）；`-t` 阈值（默认 0.15；rank 的 `-t 0` 只列清单，不筛不重排）；`github_trend` / `reddit` 的 `-q` 直接站内搜。
- text/markdown 默认带发布时间；`--meta` 再加作者、分类。

## feed：RSS / 订阅

```bash
webtool feed 少数派 --new-only       # 只出上次之后的新条目
webtool feed zhihu_daily -n 5
webtool feed get <key|任意RSS URL> -p category=news   # 带参路由填值
webtool feed get 36kr -e             # 用路由示例路径，免填参
webtool feed radar find 少数派        # RSSHub 路由库里找 feed 地址
webtool feed radar url <网页URL>      # 由网页反推 feed
webtool feed sources find 36kr       # 搜本地已订阅源
webtool feed sources add myblog <URL> "描述"   # 加自定义源
webtool feed sources del myblog      # 删自定义源
webtool feed sources mark <key> <URL> "原因"   # 登记坏源/改地址
webtool feed sources retest all      # 复查坏源
webtool feed sources list            # 管理：add/del/mark/sync/retest
webtool feed health                  # 官方坏源登记表
```

- text/markdown 默认带东八区发布时间；`--meta` 再加作者、分类。
- JSON 始终含 `date`（+08:00）、`author`、`categories`、`guid`、`updated`、`date_raw`；支持 RSS 2.0 / RSS 1.0 / Atom。

## crawl：爬文档站

```bash
webtool crawl <url> -d 1 -m 10       # 深度 1、最多 10 页
webtool crawl <url> -d 0             # 只抓这一页
webtool crawl <url> -i '/docs/' -X '\.zip$' -a
```

- 默认同 host、遵守 robots、页间隔 0.5s；默认存 `~/.webtool/crawl/<站点>-<时间>/`，`--no-save` 关闭，`-s` 换目录。
- `-d` 是深度，不是全局 debug；调试写 `webtool -d crawl ...`。

## 代理与透传

```bash
webtool proxy set http://127.0.0.1:7890    # 先确认客户端监听端口
webtool proxy test
webtool proxy rules <URL>                  # 试算这条 URL 走哪条线
webtool proxy noproxy                      # 预演常见站点分流
webtool proxy named hk http://127.0.0.1:2081
webtool proxy rule add '{"domain":["example.com"]}' proxy:hk
webtool proxy setpass <用户名>              # 密码不明文写进配置
webtool pkg npm install lodash             # 子进程按规则表走代理
webtool pkg -P pip install <包>            # 选项放命令名前
```

- `proxy cert sync`、`geo/geoip/geosite/asn` 管站点证书与分流数据；`proxy tidy --apply` 去重规则。
- 任何命令的 `-P` 都是本次直连；`-p` 在各命令含义不同（fetch=线路，search=预设，feed=路由参数）。

## 通用

- 输出格式 `-f text|json|markdown`（默认 text；json 给程序，markdown 给模型）；`-o 文件|目录`，`-o -` 强制 stdout。
- 管道：`cat urls.txt | webtool fetch -`、`echo 词 | webtool search -`；多数数据命令无参且 stdin 是管道时会自动读。
- 全局调试 `webtool -d ...`（`-dd` 含三方库，`WEBTOOL_DEBUG=1` 等效）；`webtool --version`。
- 退出码：0 成功 / 1 取数失败 / 2 用法错误 / 130 中断。
- 缓存 TTL：search 60s、fetch 10s、rank 120s；`-N` 跳过缓存。
- 时间统一按东八区（`+08:00`）输出；`feed`/`rank` 的 text/markdown 默认带发布时间，`--meta` 再加作者、分类。
- `webtool config list|get|set` 改默认（`default_engines`、`extract`、`cache`、`timeout`）；`plugins doctor` 体检插件/引擎。
- `webtool mcp list|probe|call <端点|别名> ...` 调 MCP；`intercept-log` 查拦截日志。
