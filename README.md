# webtool

网页搜索与内容获取 CLI。输出 markdown/text/json。

## 安装

```bash
pip install 'git+https://github.com/itingyu/webtool'
# 依赖含 trafilatura / curl_cffi / pysocks 等, 随安装自动装
```

代码按分层分包（`cli` → `feeds`/`radar`/`zen` → `pipeline`/`render` → `net`/`engines` → `core`），只允许向下依赖。改代码前先读 [docs/coding-standard.md](docs/coding-standard.md)，整体设计见 [docs/design.md](docs/design.md)。

## 命令

```bash
webtool search "LLM 排行榜" -n 5              # 多引擎: bing,sogou,baidu (默认) / google / marginalia
webtool fetch <url> --max-chars 4000          # 正文提取 → markdown (text/json/html)
webtool rank                                  # 榜单清单 (19 源热榜)
webtool rank zhihu weibo -q "汽车"            # 语义筛选 + 跨源重排
webtool feed                                  # 源清单 (7 预设 + 104 种子)
webtool feed sspai ithome --new-only          # 抓 feed, 增量模式
webtool feed radar 36kr --pick 1 --example    # 查 RSSHub 路由库 → 填参 → 拉数据
webtool feed instances                        # 公共实例探活
webtool feed health                           # 坏源登记表
webtool site github fastapi                   # 站内搜索 (18 站点)
webtool zen "问题"                            # OpenCode Zen 免费层对话, 无需 key
webtool proxy set http://127.0.0.1:2080       # 代理 (google 等被墙源必须)
webtool search "LLM 榜单" -e exa                # Exa 语义搜索 (MCP, 免 key)
webtool mcp list exa                            # 列 MCP 端点的工具
webtool stock quote 600519 创业板指              # 实时行情 (桥接 stock-master + stock MCP)
webtool stock analyze 600519                    # 单股深度 (技术面+100分制评分+决策信号)
webtool stock pool --only-buy                   # 涨停池 (只留可买板块)
webtool stock screen --min-score 70             # 短线选股 (含剔除清单)
webtool stock flow --scope industry             # 资金流榜单
webtool stock tools                             # stock MCP 24 个工具清单
webtool stock health                            # 两侧桥接探活
```

## 功能

### search
- 引擎：bing（直连）/ sogou（直连）/ baidu（直连）/ so360（直连）/ google（必须代理，429 降级 news RSS，链接已还原原文 URL）/ marginalia（直连）/ exa（MCP 语义搜索，免 key，**默认不开**）/ parallel（MCP 语义搜索，**匿名免 key**，**默认不开**）/ firecrawl（MCP 搜索，**匿名免 key**，**默认不开**）
  - `exa` 走 Exa MCP 的 `web_search_exa`，强制直连（免 key 配额按出口 IP 计，走代理必 429），不进默认组合，按需 `-e exa` 或加进 preset。
  - `parallel` 走 Parallel Search MCP 的 `web_search`，**匿名免 key 可用**（fast 模式），注册后每月 $5 循环额度（$1/1000 请求 ≈ 5000 次/月），配 `PARALLEL_API_KEY` 自动生效。返回 JSON 含 `publish_date`，比 exa 的纯文本更好解析，实测也更快（1.4–2.0s vs 2.6s）。
  - `firecrawl` 走 Firecrawl MCP 的 `firecrawl_search`，**匿名免 key 可用**，免费层 500 次/月 search 或 1000 页 scrape，配 `FIRECRAWL_API_KEY` 自动生效。它的 `firecrawl_scrape` 能过 JS 渲染页，是 `fetch --via` 的最佳兜底通道。
  - 三者召回都是**语义**而非关键词，与 bing/sogou 重叠少，作为长尾与英文技术内容的补充源最划算。实测召回各有胜负（同一查询 exa 条数更多、parallel 更快且带日期），按需挑或并用。
- `-e` 组合引擎；跳转链默认自动解码；query 精简（核心实体 + 意图词，优先英文）
- 结果按 `prior × √(pos×base_avg) × sem` 加权排序，尾部低质由 `weight_floor` 挡掉；`-f json` 看 `weight` 与 `engines`（交叉验证数）
- `--preset <组>` 用引擎组合预设，省得手拼 `-e`。优先级 `--engine` > `--preset` > `config.default_engines` > 清单里默认开启的引擎

  ```bash
  webtool engines presets                         # 列预设
  webtool search "查询词" --preset zh              # bing,sogou,baidu,so360（全部免代理）
  webtool search "query" --preset en              # bing,google,marginalia（含需代理的 google）
  webtool search "查询词" --preset direct          # 全部免代理，代理挂了也能用
  ```

  预设定义在 `plugins.json` 的 `presets` 段（`{"zh": {"desc": "...", "engines": [...]}}`），用户可在 `~/.webtool/plugins.json` 同构增删。用了 `--preset` 时 `-f json` 会回写 `preset` 与 `engines_used`，便于复现"这批跑的是哪组"；未知 preset 直接退 2 并列出可用名，**不静默回退**（否则用户以为跑了 A 组其实跑了默认组）

### fetch
- HTML → markdown/text/json/html；SPA 壳页收割内嵌 SSR state，拿不到时显式报错
- 按 UA 分流的站点：`--profile chrome131_android` 切移动指纹重试
- `--url-file` 批量；`--raw`；`--with-metadata`
- `--via <通道>` 选取正文的来源：
  | 通道 | 行为 |
  |---|---|
  | `local`（默认） | 只走本地提取链，**不消耗任何端点配额** |
  | `auto` | 本地链先跑；仅当确定性硬失败（JS 渲染壳 / 导航壳 / 空正文）才兜底调远程 reader |
  | `parallel` \| `exa` \| `firecrawl` | 直接走对应 MCP 的 `web_fetch`/`scrape`，跳过本地链 |

  远程 reader 用浏览器集群取页，能过 JS 渲染与大部分反爬，但每次调用消耗端点额度，故默认不启用、也不自动触发。`--via auto` 成功兜底时会在结果里带 `via_local_error` 说明本地为什么失败。

### rank
19 源：zhihu / weibo / baidu / douyin / douyin_hot / toutiao / toutiao_hot / bili_hot / bili_rank / bili_word / tieba / sina_hot / douban_movie / netease_music / ithome / hn_official / github_trend / lobsters / reddit。
无参数 = 清单；指定源按源分组原序输出；`-q` BM25 语义筛选 + 跨源重排；`-t` 默认 0.15，`-t 0` 只列清单。

### feed
- 任意 RSS/Atom URL 直接喂；`--add NAME URL [desc]` / `--del NAME`（`~/.webtool/feeds.json`，预设不可删）
- 104 个种子源随包分发，安装时自动并入（只增不覆盖；`WEBTOOL_NO_SEED=1` 关）
- `--new-only` 增量；`-q/-t` 同 rank
- 坏源失败自动登记：`feed health` / `--retest KEY|all` / `--mark KEY [URL] "备注"`
- feed radar：RSSHub 官方路由库查询（缓存 7 天）
  ```bash
  webtool feed radar 36kr                       # 搜路由卡片
  webtool feed radar 36kr --pick 2 --param category=newsflashes   # 填参拉数据
  webtool feed radar 36kr --pick 2 --example    # 官方示例路径 (免填参)
  webtool feed radar --from-url <页面URL>        # 反推路由
  webtool feed radar 36kr --pick 2 --example --add r36kr   # 落地订阅源
  ```
- feed instances：实例探活，默认挑最快的
- 公共实例：rsshub.rssforever.com / hub.slarker.me / rss.wudifeixue.com / rsshub.isrss.com；429 时轮换前缀

### site
18 站点：github / gh_search / so / hn / wikipedia / arxiv / csdn / csdn_so / juejin / juejin2 / bilibili / bili2 / sspai / npm / thepaper / eastmoney / sov2ex / douban。
JSON 扩展见 `docs/custom-sites.md`（`~/.webtool/sites/*.json`）。

### zen
```bash
webtool zen "你好"                    # 默认 big-pickle
webtool zen "问题" --model ling-3.1-flash-free
webtool zen --list-free               # 免费模型清单 (实时拉)
webtool zen "问题" --system "只回 JSON" --tool-choice none
webtool zen "问题" --no-stream         # 一次性返回 (默认 SSE 流式)
webtool zen "问题" --show-body        # 只打请求体, 不出网 (排查用)
```

模型上下架频繁，先 `--list-free` 再用；403 FreeTierError = 模型已下架。

- JSON 里的 `usage_available` = 上游是否返回用量；`false` 且 `ok: true` 是「调用成功但端点不给统计」，不是故障
- 换端点改 `~/.webtool/zen.json` 的 `chat_url` / `models_url`（mtime 热生效），协议固定 OpenAI 形状

### mcp
通用 MCP（Model Context Protocol）客户端，**不绑死任何 server**——JSON-RPC 2.0 over Streamable HTTP，纯 stdlib 实现，不引 SDK。

```bash
webtool search "LLM 榜单" -e exa -n 3           # Exa 走 search 引擎池 (见 search 段)
webtool fetch https://a.com https://b.com       # 抓正文 (等价于原 exa fetch)
webtool mcp probe exa                           # 端点通不通体检
webtool mcp list exa                             # 列工具 (name/描述/必填/可选参数)
webtool mcp call exa web_search_exa --arg query="..." --arg numResults=3
webtool mcp call https://my.site/mcp my_tool '{}' # 任意 URL 直接传
```

**Exa、Parallel、Firecrawl 都已并入 `search` 引擎池**（`webtool search -e exa` / `-e parallel` / `-e firecrawl`），不再有独立的 `webtool exa` 命令 —— 原 `exa search` 用引擎替代，`exa fetch` / `exa list` 分别由 `webtool fetch` 与 `webtool mcp list exa` 覆盖。端点声明（url / verbs / proxy / api_key_env）在 `data/mcp.json`，三个 `engines/*.py` 与 `webtool mcp`、`webtool fetch --via` 共用同一份数据。三者均匿名免 key：Exa 撞限额返回 429 并提示配 `EXA_API_KEY`；Parallel 注册后每月 $5 额度，配 `PARALLEL_API_KEY` 生效；Firecrawl 免费层 500 次/月 search 或 1000 页 scrape，配 `FIRECRAWL_API_KEY` 生效。

- 端点别名在 `src/webtool/data/mcp.json`，用户可建 `~/.webtool/mcp.json` 同构覆盖：`{"mcp":{"my_srv":{"url":"...","api_key_env":"MY_KEY","verbs":{"search":"..."}}}}`
- **代理策略**：端点可声明 `"proxy":"direct"` 强制直连（同 site 插件的 `proxy_hint` 约定）。exa 免 key 配额按**出口 IP** 计，走全局代理等于蹭别人的配额池——实测同一命令带代理必 429、直连稳定通过，故端点表已声明 `direct`。其余端点缺省跟随全局配置，`--no-proxy` 可临时覆盖
- key 一律经**环境变量名**映射，配置文件不存明文；免 key 服务不发认证头
- **传参两条通道，可并存**：`--arg k=v`（可多次；值按 JSON 字面量猜 `int`/`bool`/`null`/数组，含空格/中文/URL 的原样保留）或位置 JSON `'{"k":"v"}'`；两者同时给时 `--arg` 覆盖同名键
- `--tools a,b` 下发工具白名单（`?tools=`），缩小 Agent 选择面
- **先 `probe` / `list` 再 `call`**：免 key 与带 key 暴露的工具集可能不同（实测 exa 免 key 只有 `web_search_exa` + `web_fetch_exa`，带过滤的 `web_search_advanced_exa` 需 key）
- 失败走 stderr 并返回退出码 1，错误体原样带出（如 429 限额提示会告诉你 key 怎么配）
- 内核在 `net/mcpclient.py`，已抽出 `parse_response` / `parse_sse_message` 两个纯函数，可被其他 MCP 源直接复用

### stock
把**股票能力**收进 webtool，两座桥：

- **stock-master 桥**（进程内 import）：行情 / 涨停池 / 可买性 / 交易日历 / 资金流 / 单股深度 / 选股池 / 风险核查。数据源与口径仍由 stock-master 维护（腾讯/东财/雪球/同花顺多源 fallback）
- **stock MCP 桥**（进程内直调服务端模块）：公告 / 财务三表 / 股东 / K线 / IPO / 分红 / 两融 / 指数成分 等 24 个工具

**全链路纯进程内，不起子进程**：stock MCP 直接 import 服务端模块调 `_call_tool`；stock-master 自己的两个子进程出口（`minis-mcp-cli` 与 `webtool search`）在运行时被注入成进程内实现。实测单次调用 0.1-2s，相比原先每次起子进程（2.5-2.9s）省一个数量级。

```bash
webtool stock quote 600519 600036 创业板指       # 行情 (指数别名可用)
webtool stock pool --date last --only-buy       # 涨停池, 只留可买板块
webtool stock check 600519 300913               # 可买性核查 (创业板/科创板会标不可买)
webtool stock calendar --n 5                    # 交易日历
webtool stock flow --scope north                # 北向 (industry/individual/north)
webtool stock news 600519 -n 5                  # 个股新闻
webtool stock announcement 600519               # 公告
webtool stock financials 600519                 # 核心财务指标
webtool stock analyze 600519                    # 单股深度
webtool stock screen --pool short --min-score 70  # short(1-5日)/mid(3-6月)/long(6-18月)
webtool stock risk 600623                       # 风险核查 (重组/减持/立案/预亏)
webtool stock mcp --tool stock_kline --arg symbol=600519 --arg period=day
webtool stock tools                             # 24 工具清单
webtool stock health                            # 两侧探活
```

- **两侧都不复制业务逻辑**，只是进程内 import；skill 未装时 `stock health` 报 unavailable，不拖垮 webtool 其他命令。路径可用 `STOCK_MASTER_HOME` / `STOCK_MCP_HOME` 覆盖
- **工具清单读服务端 `TOOLS` 注册表**，服务端增删工具 webtool 自动跟上；本地表只在服务端 import 不了时兜底
- **口径纪律照搬 stock-master**：涨停池输出必带真实数据日（该接口对无效日期会静默回旧数据）；北向 `status=3` 或接口回填额度上限一律标 ⚠「未取得」，**禁止当 0**；MCP 回了原始 HTML 未解析出条目时显式标注，不把 100KB 噪声当结果
- `--arg` 的值猜类型时**纯数字一律留字符串**（600519 是代码不是整数），与 `webtool mcp` 的口径不同
- `screen` 的 text 输出必含**剔除清单与闸门原因** —— 只给通过名单会让调用方以为没被选中的票不存在
- 退出码：0 成功 / 1 数据动作失败 / 2 用法错误

## 通用约定

- `-n` 条数 / `-f` 格式（`md`≡`markdown`、`txt`≡`text`，大小写不敏感）/ `-o` 落盘（按 `-f` 补扩展名）/ `--no-cache` / `--no-proxy`
- 退出码：0 成功 / 2 用法错误（提示走 stderr）
- 缓存 TTL：search 60s / fetch 10s / 跳转解析 10min（`config set cache_ttl.<桶>=<秒>` 覆盖）
- 出网全走浏览器指纹，直连优先、失败才探活代理重试；google / docs.rsshub.app 必须代理
- 报错自带处置建议，照做即可

## 扩展

七类插件：搜索引擎（`engine`）、榜单源（`hot`）、站内站点（`site`）、正文提取器（`extractor`）、跳转链解码器（`resolver`）、结果过滤器（`filter`）、结果改写（`transformer`）。清单在 `src/webtool/data/plugins.json`，用户在 `~/.webtool/plugins.json` 可覆盖或追加，无需改代码：

```jsonc
// ~/.webtool/plugins.json
{
  "engine": {
    "bing": {"base": 0.6},                              // 改权重 (默认 0.9)
    "my_eng": {"module": "mypkg.search:run", "desc": "自建引擎"}
  },
  "extractor": {
    "my_ext": {"module": "mypkg.extract:run", "desc": "自定义提取器"}
  }
}
```

各类函数签名：

| 类别 | 签名 | 说明 |
|---|---|---|
| `engine` | `(query, max_results, proxy, timeout, market) -> [结果]` | `base` 决定排序权重 |
| `hot` | `(query, limit, proxy, timeout) -> [结果]` | `search` 决定能否直接传关键词 |
| `site` | `(query, limit, proxy, timeout, **kw) -> [结果]` | `proxy` 为 `direct`/`proxy` |
| `extractor` | `(html, url, meta) -> (正文, meta)` | 返回 `('' , {...})` 表示降级 |
| `resolver` | `(url, proxy, timeout) -> 新 url` | `match` 指认跳转链特征 |
| `filter` | `(results, ctx) -> [结果]` | 剔除不该出现在结果里的条目 |
| `transformer` | `(results, ctx) -> [结果]` | 补字段、改写 url 等 |

- `module` 格式 `包路径:函数名`
- 三层来源，后者覆盖前者：包内 JSON → 用户 JSON → `WEBTOOL_PLUGIN_DIR`（默认 `~/.webtool/plugins`，放外部 `.py` 后在配置里指向）
- 顺序即优先级：`hot`/`extractor`/`filter`/`transformer` 按插入顺序执行；提取器首个返回非空正文的生效
- 过滤规则同样可配：`~/.webtool/filters.json` 覆盖 `adfilter`（广告词/域名）、`blocklist`（低质站点）、`merge`（词典先验域/跟踪参数/短实体表）、`spa`（内嵌 state 挂载点追加）
- 引擎行为参数在 `engine.<name>.params`：`rate`（请求间隔秒）、`captcha_signs`（验证页指纹 `[算子,值]`，算子 contains/title_contains/len_lt）、`cooldown`（触发后静默秒）
- 启停：`webtool plugins enable|disable <kind> <name>`（写用户清单翻转 `enabled`，mtime 自动生效）；被禁用的插件在 `plugins list --all` 与 status 里仍可见（state=disabled）
- RSSHub 公共实例表在 `data/instances.json`（用户可建 `~/.webtool/instances.json` 同构覆盖）

### 跳转链解码

搜狗 `/link`、百度 `/link?`、Google News `/articles/` 这类跳转链会被还原成原始 URL（无条件执行：不还原则去重与黑名单匹配均失效）。这一层是 `resolver` 插件，与引擎无关——**按 URL 特征认链，不是按结果来自哪个引擎**：

```jsonc
// ~/.webtool/plugins.json
{
  "resolver": {
    "myshort": {"module": "mypkg.deLink:resolve", "match": ["~t\\.co/"]}
  }
}
```

`match` 里普通字符串按子串匹配（域名和整条 URL 都比），`~` 开头按正则匹配整条 URL。加自己的短链服务只需照此声明一条。

### 热更新

| 改什么 | 生效方式 |
|---|---|
| `~/.webtool/plugins.json` 增删改条目 | **自动**（按 mtime 判定失效，同进程内立即生效） |
| `~/.webtool/filters.json` 过滤规则 | **自动**（同上） |
| 外部插件 `.py` 文件内容 | `webtool plugins reload`（Python 缓存了已导入模块，需显式重载） |
| 装饰器 `@register` 注册的代码 | 重启进程 |

`webtool plugins list`（清单与来源：builtin/user/code）、`plugins check`（逐个加载体检，报失败项）、`plugins reload`（重载外部模块并清配置缓存）。配置坏了不会拖垮进程，退回内置默认并在 `plugins check` 报错。

## 给 Agent 用

复制 `skills/webtool/SKILL.md` 到 Agent 的 skill 目录（Claude Code `.claude/skills/`、Minis `/var/minis/skills/`）。

深入文档：`docs/coding-standard.md`（**编码规范/分层，改代码先读**）· `docs/design.md`（架构）· `docs/feed-sources.md`（feed 源实测）· `docs/custom-sites.md`（site 扩展）· `docs/engine-notes.md`（引擎通道记录）。
