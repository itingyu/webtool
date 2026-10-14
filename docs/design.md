# webtool 设计文档（V1）

> 目标：给 Agent 用的免费网页搜索 + 内容获取 CLI，输出 markdown/text/json，去广告留正文，省 token。
> 仓库：github.com/itingyu/webtool

## 0. 现行架构（2026-10）

V1 设计见下文第 1-4 节（历史决策记录）。当前代码结构以本节为准：

```
src/webtool/
├── cli/                 # typer 声明式 CLI (app/config/plugins); 命令函数填 SimpleNamespace 复用 do_*(args, cfg)
│   └── sitesearch / zen / zenproto   # 站内搜索调度 / LLM 对话编排 / OpenAI 兼容协议细节
├── feeds/               # RSS/Atom 订阅聚合
│   └── command / sources / parse / fetch / cards / feedhealth
├── radar/               # RSSHub 路由查询与参数填充 (按数据源切: routes/rules/instances/official/template/race)
├── pipeline/            # search 调度 / rank 榜单 / merge 排序去重 / topup 补量 / qhint 质量诊断 / query_ops
├── render/              # render 正文渲染 / hotrender 榜单分节 / output 落盘
├── filters/             # blocklist 站点黑名单 / adfilter 广告识别 (纯规则, 不出网)
├── net/                 # transport 指纹传输 / proxy / captcha 冷却 / spa 数据提取 / fetch 正文抓取
├── engines/             # 各站适配器函数 (由 plugins.json 的 module 字段指向) + extractors / customsites
├── core/                # L0 底座 + 通用工具类
│   ├── plugins.py       # Registry: 七类插件 engine/site/hot/extractor/resolver/filter/transformer 统一注册表 (懒解析 + 三层来源)
│   ├── config_data.py   # 配置合并: 包内 data/*.json + ~/.webtool/ 同名文件 (深合并/列表替换, 指纹判失效热生效)
│   ├── cache.py state.py http.py probe.py resilient.py
│   └── text.py urls.py jsonfmt.py   # 通用工具类: HTML 转纯文本 / URL 归一化 / JSON 原子读写
└── data/
    ├── plugins.json  # 引擎/榜单源/站点/提取器清单 (元数据 + 模块路径)
    ├── filters.json  # 广告特征词/落地域名/黑名单 (含 notes 说明背景)
    ├── instances.json / zen.json / feeds.seed.json
    └── 注: data/ 在包根, 不在 core/ 下 —— core.config_data.DATA_DIR 指向它
```


**扩展方式**：七类插件清单声明在 `data/plugins.json`，用户经 `~/.webtool/plugins.json` 覆盖或追加（改权重、加引擎/站点/提取器/解码器/过滤器），无需改代码；函数签名约定 `包路径:函数名`。详见 README「扩展」节。

**硬编码现状**：站点适配器函数体（URL 构造、解析逻辑）仍在 `engines/*.py` —— 那是抓取逻辑本身，属代码；所有**元数据与配置**（引擎权重、站点描述/代理偏好、榜单源描述、广告与黑名单规则）已外置到 JSON。

## 1. 业界调研结论（实测）

| 工具/服务 | 模式 | 费用 | 对 webtool 的借鉴 |
|---|---|---|---|
| Jina Reader (r.jina.ai) | URL 前缀即 API | 免费额度有限，无 key 401 | API 形态（x-respond-with、X-Token-Budget、X-Proxy-Url 均实测自文档）；沙盒内被墙，本机代理可通 |
| Exa / Tavily | 语义搜索 API | $5-8 / 千次 | 输出结构（title/url/snippet/content）；预算不是零，不采用 |
| Firecrawl | 爬取 SaaS + 开源自托管 | 免费 key 500 次 | .llms.txt 约定、scrape/crawl/search 三动词 |
| crawl4ai | 开源 Python 库 | 免费 | CLI `crwl`、fit_markdown（修剪噪声正文）、BM25 过滤、proxy 配置 |
| trafilatura | 开源 Python 库 | 免费 | **正文提取基准第一名**（F1 0.926，见官方 benchmark），自研 markdown 输出 |
| SearXNG | 自托管元搜索 | 免费 | 分桶缓存 TTL 思路（webtool 实配：结果 60s / 正文 10s / 跳转解析 10min，v1.5.6 收紧）、JSON API 需启用 format |
| curl-github 模式 | 命令行直用 | — | 子命令 + flag + 管道友好 |

关键实测数据（本沙盒）：
- ddgs 库 7 个后端全部超时/被墙（free 代理 IP 被 DDG 风控 202 anomaly 拦截，cookie/POST/完整浏览器头均绕不过）
- Google Web 搜索：需 JS 渲染（noscript 拦截壳页面），403/429 风控，纯 HTTP 不可行 → 降级 news RSS 通道
- **Bing HTML（cn.bing.com，chrome 指纹直连）：与浏览器主页排序一致，0.5s 间隔 5 连打零风控 → 主力；RSS 留作兜底**
- **搜狗 web：直连可解析（vr-title 节点 5-11 条/页），link 跳转链带 cookie+Referer 请求后 302→window.location.replace 拿真实 URL** → 中文补充引擎
- 百度：urllib 的 JA3 指纹必弹「百度安全验证」；curl_cffi impersonate=chrome 后 5/5 成功 → 需 `full` extra
- Qwant API：403 Cloudflare 盾 → 放弃
- 360 搜索：可抓但结构复杂，作为备选不进 V1

> 注：本文档为 V1 设计时的架构与决策记录，部分模块名（extract.py/fallback.py/output.py/duckduckgo/jina 引擎）在现行代码中已演进为 render.py/fetch.py 内置降级链/marginalia 引擎等，以 `src/webtool/` 实际结构为准。

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
├── cache.py        # 磁盘缓存, 分桶 TTL: 搜索60s/正文10s/跳转解析600s
└── output.py       # json / markdown / text 三格式渲染
```

依赖策略：
- 零硬依赖：stdlib (urllib/re/gzip/http.cookiejar) 完成搜索+HTTP
- 提取链分两层（清单见 `data/plugins.json` 的 `extractor` 段）：
  - **内容层**：trafilatura / boilerplate / readability-lxml —— 同层一起跑，按
    「碎片率 + 长度」择优（`extractors.pick_best`），**不是谁先谁后谁生效**。
    同一个页面 trafilatura 会把文章区的推广块一起收进来，readability 却切得干净，
    用"第一个非空的"就等于让注册顺序决定结果好坏；
  - **兜底层**：inscriptis / 零依赖剥标签 —— 整页纯文本，只在内容层全空时才跑，
    不参与择优（它永远非空，一竞争就用整页噪声盖掉正文）。
- `boilerplate` 是 readability 算法的纯标准库实现（`engines/boilerplate.py`，零关键词
  表）：按标签/隐藏样式清洗 → 段落打分并向上累积 → 定级（独占子节点下钻）→ 按
  「文气密度」清尾。lxml 装不上的平台（Termux/Android）靠它，不至于掉到整页 dump。
- 用哪个提取器可配：`--extract` / `config extract`，默认 `auto`（择优）。留 `auto`
  当默认是量出来的：14 个真实页面上 readability 中位碎片率 1% 但长文合集页丢六成正文，
  trafilatura 中位 6% 却在门户页带一堆推广块 —— 没有单一提取器能通吃，硬选一个就是拿
  一类页面换另一类。要可预期/要快就指定具名。
- 提取结果里 `extract` 字段说明这次是谁出的活；某层提取器因缺依赖被跳过时，
  stderr 提示一次（复用 `deps.install_hint` 的补依赖指引）。

### 2.4 省 token 设计（核心卖点）

1. 默认 `--format markdown`：正文提取后无广告/导航/脚本，比原 HTML 节省 90%+ token
2. `--max-chars N`：截断到指定字符数，Agent 可控上下文
3. `--format json`：结构化字段，Agent 直接解析不猜
4. 搜索结果默认只给 `title + url + snippet`（不含正文），Agent 需要再 fetch
5. 缓存命中不重复抓取：搜索 60s / 正文 10s / 跳转解析 10min
6. 输出去噪：连续空行合并、去 cookie 提示条、去 "扫码登录" 等中文站点常见噪声文本
7. `-f txt` 与 `-f markdown` 是两个真格式：`txt` 走 `core.text.md_to_text` 抹掉
   `##`/`**`/反引号/链接括号/表格竖线/markdown 转义，并去掉 YAML 元数据头
   （要元数据走 `-f json`），不给"说是 txt、拿到还是 markdown"的半吊子

### 2.5 代理设计

一条请求走直连还是代理，**只由规则表判一次**（`netx` 是唯一决策点），引擎、
端点、适配器都不自报线路。

```jsonc
// ~/.webtool/config.json
{
  "proxy": "http://127.0.0.1:2080",       // 全局默认线路 (空 = 直连)
  "fetch_proxy": "http://127.0.0.1:2080",  // fetch 动作专用覆盖 (可选)
  "timeout": 15,
  "ua": "auto",
  "cache_dir": "~/.webtool/cache"
}

// ~/.webtool/rules.json —— 线路的唯一决策源
{
  "default": "direct",          // 未命中时的动作 (缺省: 有全局 proxy 就用它)
  "priority": "direct",         // 命中冲突时 direct 压过 proxy
  "rules": [
    {"match": {"geosite": ["cn"]}, "action": "direct"},
    {"match": {"domain": ["google.com"]}, "action": "proxy"}
  ]
}
```

规则：
- `webtool proxy set http://...`：写 config.json 的 `proxy` 字段
- `webtool proxy rule add '{...}' direct|proxy|<代理名>`：加一条规则
- `webtool search --proxy http://...` / `--no-proxy`：单次临时覆盖
- 境内站想直连、境外站走代理：用 `geosite` 规则分流，不再靠引擎级配置
- 环境变量 `http_proxy`/`https_proxy` **不作为决策源**（在 opener 层已被堵死）
- socks5 支持用 pysocks（随包安装）

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
