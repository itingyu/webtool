# webtool 设计文档（V1）

> 目标：给 Agent 用的免费网页搜索 + 内容获取 CLI，输出 markdown/text/json，去广告留正文，省 token。
> 仓库：github.com/itingyu/webtool（已克隆到 ~/webtool）

## 1. 业界调研结论（实测）

| 工具/服务 | 模式 | 费用 | 对 webtool 的借鉴 |
|---|---|---|---|
| Jina Reader (r.jina.ai) | URL 前缀即 API | 免费额度有限，无 key 401 | API 形态（x-respond-with、X-Token-Budget、X-Proxy-Url 均实测自文档）；沙盒内被墙，本机代理可通 |
| Exa / Tavily | 语义搜索 API | $5-8 / 千次 | 输出结构（title/url/snippet/content）；预算不是零，不采用 |
| Firecrawl | 爬取 SaaS + 开源自托管 | 免费 key 500 次 | .llms.txt 约定、scrape/crawl/search 三动词 |
| crawl4ai | 开源 Python 库 | 免费 | CLI `crwl`、fit_markdown（修剪噪声正文）、BM25 过滤、proxy 配置 |
| trafilatura | 开源 Python 库 | 免费 | **正文提取基准第一名**（F1 0.926，见官方 benchmark），自研 markdown 输出 |
| SearXNG | 自托管元搜索 | 免费 | 分桶缓存 TTL（结果 1800s / 内容 1d / 前缀 7d）、JSON API 需启用 format |
| curl-github 模式 | 命令行直用 | — | 子命令 + flag + 管道友好 |

关键实测数据（本沙盒）：
- ddgs 库 7 个后端全部超时/被墙（free 代理 IP 被 DDG 风控 202 anomaly 拦截，cookie/POST/完整浏览器头均绕不过）
- Google Web 搜索：需 JS 渲染（noscript 拦截壳页面），403/429 风控，纯 HTTP 不可行 → 降级用 Jina/AI 前缀引擎
- **Bing RSS 接口（format=rss）：免费、免 key、免 JS、国内外直连、支持 setmkt/setlang/翻页（first=）、可解析 10 条/页** → 主力引擎
- **搜狗 web：直连可解析（vr-title 节点 5-11 条/页），link 跳转链带 cookie+Referer 请求后 302→window.location.replace 拿真实 URL** → 中文补充引擎
- 百度：PC/移动 UA 均直接弹「百度安全验证」且无 JS 可算 → 放弃
- Qwant API：403 Cloudflare 盾 → 放弃
- 360 搜索：可抓但结构复杂，作为备选不进 V1

## 2. webtool 设计

### 2.1 定位
单二进制 CLI（Python 实现，pipx/uv 安装），面向 Agent 的两大动作：
- `search`：多引擎搜索 → 结构化结果（标题/URL/摘要）
- `fetch`：URL → 纯净内容（markdown/text/json/html），自动去广告/导航/页头页尾

### 2.2 命令行接口

```bash
webtool search "trafilatura 教程" --engine bing,sogou --max 8 --format json
webtool fetch https://example.com/article --format markdown --max-chars 4000
webtool fetch --url-file urls.txt --format json --extract metadata
webtool proxy set http://127.0.0.1:2080      # 持久化到 ~/.webtool/config.json
webtool proxy get|unset|test
webtool engines                              # 列出可用引擎及健康状态
```

### 2.3 架构

```
webtool/
├── cli.py          # argparse 入口, 3 个子命令 + config
├── search.py       # 多引擎调度
│   ├── engines/bing.py      # RSS 接口 (主力, 国内外通吃, 免 key)
│   ├── engines/sogou.py     # HTML 解析 + link 跳转解析 (中文)
│   ├── engines/duckduckgo.py # (可选) ddgs 库, 需代理可用
│   ├── engines/jina.py      # (可选) r.jina.ai 前缀, 需代理
│   └── engines/google.py    # (可选) 走 r.jina.ai/https://www.google.com/search?q=... 曲线
├── fetch.py        # 抓取 + 提取
│   ├── http.py     # urllib + ProxyHandler + gzip + UA 轮换
│   ├── extract.py  # trafilatura 正文提取, markdown/text/json 三格式
│   └── fallback.py # readability-lxml + html2text + inscriptis 三级兜底
├── proxy.py        # 代理配置 ~/.webtool/config.json
├── cache.py        # 磁盘缓存, 分桶 TTL: 搜索1800s/正文86400s/跳转解析604800s
└── output.py       # json / markdown / text 三格式渲染
```

依赖策略：
- 零硬依赖：stdlib (urllib/re/gzip/http.cookiejar) 完成搜索+HTTP
- 可选依赖：trafilatura(首选提取) → readability-lxml(兜底) → html2text(再兜底) → inscriptis(纯文本保底)
- 无 trafilatura 时自动降级到 readability-lxml，再无则 html2text

### 2.4 省 token 设计（核心卖点）

1. 默认 `--format markdown`：正文提取后无广告/导航/脚本，比原 HTML 节省 90%+ token
2. `--max-chars N`：截断到指定字符数，Agent 可控上下文
3. `--format json`：结构化字段，Agent 直接解析不猜
4. 搜索结果默认只给 `title + url + snippet`（不含正文），Agent 需要再 fetch
5. 缓存命中不重复抓取：搜索 30min / 正文 24h / 跳转解析 7d
6. 输出去噪：连续空行合并、去 cookie 提示条、去 "扫码登录" 等中文站点常见噪声文本

### 2.5 代理设计

```jsonc
// ~/.webtool/config.json
{
  "proxy": "http://127.0.0.1:2080",       // 全局默认
  "engine_proxy": {                        // 每引擎覆盖
    "bing": null,                          // 国内直连
    "sogou": null,
    "duckduckgo": "http://127.0.0.1:2080", // 需代理
    "google": "http://127.0.0.1:2080"
  },
  "fetch_proxy": "http://127.0.0.1:2080",  // fetch 动作默认
  "timeout": 15,
  "ua": "auto",                            // auto | 指定 UA 字符串
  "cache_dir": "~/.webtool/cache"
}
```

规则：
- `webtool proxy set http://...`：写 config.json 的 `proxy` 字段
- `webtool search --proxy http://...`：临时覆盖
- `webtool fetch --proxy socks5://...`：临时覆盖（支持 http/https/socks5）
- 域名分流域（v1 简化）：`engine_proxy` 让 bing/sogou 直连（国内快），ddg/google 走代理
- socks5 支持用 pysocks（可选依赖，无则提示）

### 2.6 输出格式

`search --format json`：
```json
{"query":"...", "engine":"bing", "took_ms":1100, "results":[
  {"rank":1, "title":"...", "url":"https://...", "snippet":"..."}]}
```

`fetch --format markdown`：正文 markdown（默认，title 作为 H1）
`fetch --format text`：纯文本
`fetch --format json`：
```json
{"url":"...", "status":200, "title":"...", "content":"...", "metadata":{"author":"...","date":"...","sitename":"..."}, "took_ms":2300}
```
错误统一：`{"error":"...", "url":"...", "hint":"建议: --engine sogou 或 --proxy ..."}`

### 2.7 V1 范围（不做的事）

- 不做：JS 渲染（playwright）、截图、PDF 转换（V2 加 docling）、API server、爬站（crawl）
- 搜狗 link 跳转解析带 cookie 状态机：第一次搜索结果里的 /link?url=xxx 统一在输出前批量 resolve（并发 5），失败则保留原跳转链并在 json 标注 `resolved:false`

## 3. 实测数据（本沙盒 2026-10-09）

| 测试 | 结果 |
|---|---|
| Bing RSS `trafilatura 教程` | 10 条 / 1.1s，中英文均正常 |
| Bing RSS `AI agent` setmkt=en-US（代理）| 11 条，英文结果正常 |
| Bing RSS 翻页 first=11 | 正常 |
| 搜狗 `trafilatura` | 4-5 条 / 1.8-2.8s，link 页带 cookie 302 解析成功 |
| 搜狗 `python 爬虫` | 11 条 / 直连 |
| Google Web 搜索（代理+移动 UA） | 200 但返回 enablejs 壳页，纯 HTTP 无结果 → 走 Jina 曲线 |
| Google gbv=1 基础版 | 同上，JS 强制 |
| DDG html/lite（代理） | 202 anomaly 人机验证，POST/cookie/完整头均无效 |
| 百度 PC/移动 | 302 → 百度安全验证，无法绕过 |
| trafilatura 提取 github README | 344KB HTML → 7533 字符 markdown，3.1s |
| trafilatura 提取 HN 页面 | 4976B → 1159 字符，1.7s |
| 知乎专栏/问题页 | 403（需登录态，V2 用 cookie 池或放弃） |

## 4. 实施步骤

1. `cli.py` + `proxy.py` + `config.json` 读写（先打通参数骨架）
2. `engines/bing.py`（RSS）+ `engines/sogou.py`（HTML+link 解析）
3. `http.py`（代理/gzip/UA/超时）+ `cache.py`
4. `extract.py`（trafilatura 主 + readability/html2text 兜底）
5. `output.py`（json/markdown/text）+ CLI 打磨（--max-chars/--format/--engine）
6. 实测 5+ 个中文/英文站点调优，写 README + 发布 v0.1.0 tag
```
