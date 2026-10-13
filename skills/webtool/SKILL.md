---
name: webtool
description: 网页搜索与内容获取 CLI。多引擎搜索（含 exa 语义搜索）+ 榜单聚合 rank（知乎/微博/抖音/B站/HN/GitHub Trending 等 19 源）+ 18 站点站内搜索 site + RSS 订阅 feed（RSSHub 路由库 radar 查询填参、增量、坏源登记）+ zen 免费层 LLM 对话 + 通用 MCP 客户端 mcp + 股票能力 stock（实时行情/涨停池/选股池/单股深度/风险核查/公告财务，桥接 stock-master + stock MCP）+ 正文提取转 markdown/text/json。当用户提到「搜索网页 / 查资料 / 抓网页正文 / 热榜 / 榜单 / 订阅 / RSS / 站内搜索 / 问大模型 / MCP / exa / 股票行情 / 涨停 / 选股 / 个股分析 / 资金流 / webtool」时触发。
version: 1.11.0
---

# webtool

## 命令速查

```sh
webtool search "LLM leaderboard" -n 5       # 多引擎, 默认 bing,sogou,baidu
webtool search "query" -e marginalia         # 长尾独立索引 (小站/老网页)
webtool search "查询词" --preset zh            # 引擎组合预设 (webtool engines presets 列)
webtool fetch <url> --max-chars 3000         # 正文提取 → markdown (-f text/json/html)
webtool rank                                 # 榜单清单 (19 源)
webtool rank zhihu weibo -q "汽车"           # 语义筛选 + 跨源重排 (-t 0 只列清单)
webtool feed                                 # 源清单 (7 预设 + 种子/自定义)
webtool feed sspai ithome --new-only         # 抓 feed; --new-only 增量
webtool feed radar 36kr                      # 查 RSSHub 路由库
webtool feed instances                       # 公共实例探活
webtool feed health                          # 坏源登记表
webtool site github fastapi                  # 站内搜索 (18 站点, site list 查全部)
webtool zen "问题"                           # 免费层 LLM 对话, 无需 key
webtool mcp list exa                         # 通用 MCP 客户端, 列端点工具
webtool search "查询词" -e exa                # Exa 语义搜索 (MCP, 免 key)
webtool stock quote 600519 创业板指            # 实时行情 (桥 stock-master + stock MCP)
webtool stock analyze 600519                  # 单股深度 (技术面 + 100 分制评分 + 信号)
webtool stock screen --min-score 70           # 短线选股 (含剔除清单)
webtool stock tools                           # stock MCP 24 工具清单
webtool stock report 600519                   # 成稿研报 (markdown)
webtool stock sentiment --text "业绩超预期"     # 消息面打分 -100~+100
webtool stock health                          # 两侧桥接探活
webtool config set default_engines bing,sogou
```

## search

- 引擎：bing（直连）/ sogou（直连）/ baidu（直连）/ so360（直连）/ google（**必须代理**，429 自动降级 news RSS，结果 `channel: news` 且链接已还原原文 URL，直接 fetch）/ marginalia（直连）/ exa、parallel、firecrawl（MCP 语义搜索，均匿名免 key，均**默认不开**）
- `-e` 组合引擎；`--preset zh|en|direct` 用引擎组合预设（`webtool engines presets` 列），优先级低于 `-e`。`direct` 组全免代理，代理不可用时首选
- 语义引擎按需加：`-e parallel`（最快，返回 JSON 带日期）/ `-e exa`（召回条数常最多）/ `-e firecrawl`（search 免费 500 次/月，scrape 能过 JS 渲染）；均与关键词引擎重叠少，补英文/技术长尾最划算
- `-e` 逗号分隔组合；跳转链默认自动解码（`--no-resolve` 关）
- query 精简：核心实体 + 意图词；优先英文；中文用引擎习惯叫法（`大模型` 而非 `大语言模型`）
- 结果已按 `prior × √(pos×base_avg) × sem` 加权排序，尾部低质由 `weight_floor` 挡掉；`-f json` 看 `weight` / `engines`（交叉验证数）

## fetch

- HTML → markdown/text/json/html；SPA 壳页自动收割内嵌 SSR state，拿不到时显式报错
- 按 UA 分流的站点：`--profile chrome131_android`（或 `safari18_4_ios`）切移动指纹重试
- `--url-file` 批量；`--raw` 跳过提取；`--with-metadata` 附标题/作者/日期
- `--via local|auto|parallel|exa|firecrawl` 选正文通道：默认 `local`（纯本地提取链，**不花配额**）；`auto` 仅在确定性硬失败（JS 壳/导航壳/空正文）时兜底远程 reader；指定通道则直接走其远程 fetch。JS 渲染页拿不到正文时用 `auto` 或 `--via firecrawl`（过 JS 最稳），别反复换 profile 硬试

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

18 站点：github / gh_search / so / hn / wikipedia / arxiv / csdn / csdn_so / juejin / juejin2 / bilibili / bili2 / sspai / npm / thepaper / eastmoney / sov2ex / douban。
JSON 扩展格式见 `docs/custom-sites.md`（`~/.webtool/sites/*.json`，可覆盖内置）。

## zen

```sh
webtool zen "你好"                    # 默认 big-pickle
webtool zen "问题" --model ling-3.1-flash-free
webtool zen --list-free               # 免费模型清单 (实时拉, 不硬编码)
webtool zen "问题" --system "只回 JSON" --tool-choice none
webtool zen "问题" --sticky             # 复用 ses_id (默认关)
```

模型上下架频繁，别凭记忆报模型名，先 `--list-free`。报 403 FreeTierError = 模型已下架，刷新清单。

- `--sticky` 复用 ses_id，默认关：实测 Zen 免费层 `cached_tokens` 恒为 0，开不开耗时无差异，别当提速手段
- JSON 里 `usage_available` = 上游是否返回用量；`false` 且 `ok: true` 是"调用成功但端点不给统计"，不是故障
- 换端点改 `~/.webtool/zen.json` 的 `chat_url` / `models_url`，mtime 热生效；协议固定 OpenAI 形状

## mcp

通用 MCP 客户端（JSON-RPC 2.0 over Streamable HTTP，纯 stdlib，不绑死任何 server）。

```sh
webtool search "LLM 榜单" -e exa -n 3          # Exa 已并入 search 引擎池 (免 key)
webtool fetch https://a.com https://b.com      # 抓正文 (等价于原 exa fetch)
webtool mcp probe exa                             # 端点体检
webtool mcp list exa                               # 列工具 (name/描述/必填/可选参数)
webtool mcp call exa web_search_exa --arg query="..." --arg numResults=3
webtool mcp call https://my.site/mcp my_tool '{}' # 任意端点
```

- **Exa 已并入 `search` 引擎池，没有独立的 `webtool exa` 命令**：原 `exa search` → `webtool search -e exa`；原 `exa fetch` → `webtool fetch`；原 `exa list` → `webtool mcp list exa`
- 端点声明（url / verbs / proxy / api_key_env）在 `data/mcp.json`，`engines/exa.py` 引擎与 `webtool mcp` 共用同一份数据
- 端点别名可自建：`~/.webtool/mcp.json` → `{"mcp":{"别名":{"url":"...","api_key_env":"MY_KEY","verbs":{...}}}}`
- key 只经环境变量名映射，配置文件不存明文；免 key 服务不发认证头
- **exa 已声明 `proxy:direct`**：免 key 配额按出口 IP 计，走全局代理必 429、直连才稳；其余端点默认跟随全局配置，`--no-proxy` 可临时覆盖
- **传参两条通道可并存**：`--arg k=v`（可多次，值按 JSON 字面量猜 int/bool/null/数组，含空格/中文/URL 原样保留）或位置 JSON；同给时 `--arg` 覆盖
- **先 `probe`/`list` 再 `call`**：免 key 与带 key 暴露的工具集可能不同（实测 exa 免 key 仅 `web_search_exa` + `web_fetch_exa`，带域名/日期过滤的 `web_search_advanced_exa` 需 key）
- 免 key 有真实限额，**响应头无任何预告**，只能撞 429 才知道；配额**按出口 IP 计**（所以 exa 声明了 `proxy:direct`）。撞 429 先怀疑走了代理，去掉即恢复；仍受限则配 `EXA_API_KEY`（自动生效，`--apikey` 可临时覆盖）
- `list` / `probe` 不消耗搜索额度，只有 `call` 计
- 失败走 stderr + 退出码 1，错误体原样带出

## stock

桥接两侧股票能力，不复制业务逻辑，**全链路纯进程内、不起子进程、不经 MCP 协议**：**stock-master 桥**（行情/涨停池/选股/风险）与 **stock 数据桥**（直调服务端 handler；公告/财务/股东/K线等 24 工具）。

```sh
webtool stock quote 600519 600036 创业板指      # 行情 (指数别名可用)
webtool stock pool --only-buy                 # 涨停池 (连板/封单/行业)
webtool stock check 600519 300913             # 可买性 (创业板/科创板会标不可买)
webtool stock calendar --n 5                  # 交易日历
webtool stock flow --scope industry           # 资金流 (industry/individual/north)
webtool stock news 600519                     # 新闻;  announcement 600519  # 公告
webtool stock financials 600519               # 核心财务指标
webtool stock analyze 600519                  # 单股深度 (三档入场价 + 硬止损 + 评分)
webtool stock screen --pool short --min-score 70   # short/mid/long 三池
webtool stock risk 600623                     # 风险核查 (重组/减持/立案/预亏)
webtool stock report 600519                   # 成稿研报 (markdown; --pool short 出短线池研报)
webtool stock excel --excel picks.xlsx        # 选股池导出 xlsx (4 sheet, 需 openpyxl)
webtool stock sentiment 600519                # 该股新闻消息面打分; 也可 --text "..." 直接打分
webtool stock diagram --kind tree             # mermaid: tree 决策树 / logic 投资逻辑 / chain 产业链
                                          #   chain: --name 产业链 --driver 上游 --mid 中游 --catalyst 下游
webtool stock mcp --tool stock_kline --arg symbol=600519
webtool stock tools                           # 24 工具清单;  health  # 两侧探活
```

- **两侧都只做桥接**：数据源与口径归 stock-master 与 stock MCP 维护。skill 缺失只让 stock 动作退 2，不影响 webtool 其他命令
- **纯进程内**：单次调用 0.1-2s（原先每次起子进程 2.5-2.9s）。直接调服务端 `TOOLS` 里的 handler 函数，没有 JSON-RPC 也没有 content 信封序列化。stock-master 的两个子进程出口（`minis-mcp-cli` / `webtool search`）在运行时被注入成进程内实现，不改 skill 文件
- **工具清单读服务端 `TOOLS` 注册表**，服务端增删工具自动跟上
- **失败语义**：handler 抛异常或返回 `ok=False` 都按"调用失败"处理（stderr + 退出码 1），不会崩进程
- **report / diagram / excel 原样透传**（成稿 markdown、mermaid 源码、落盘确认），不再包 JSON 或表格 —— 这些产出本来就是给人直接看的。sentiment 分数带符号印出（`+12` 而非 `12`），方向是消息面的关键信息
- **`report` / `excel` 跑短线池会扫全市场**（约 5 分钟），别放进交互式调用；`excel` 缺 openpyxl 会明确报错而非静默不出文件
- **口径纪律**：涨停池必带真实数据日（该接口对无效日期会静默回旧数据）；北向 `status=3` 或接口回填额度上限一律标 ⚠「未取得」，**禁止当 0**；MCP 回了原始 HTML 未解析出条目时显式标注，不把 100KB 噪声当结果
- `--arg` 纯数字一律留字符串（600519 是代码，整数会被 MCP schema 拒）—— 与 `webtool mcp` 口径不同
- `screen` 输出必含**剔除清单与闸门原因**，只给通过名单会让调用方以为没被选中的票不存在
- 退出码：0 成功 / 1 数据动作失败 / 2 用法错误

## 通用约定

- `-n` 条数 / `-f` 格式（`md`≡`markdown`、`txt`≡`text`，大小写不敏感）/ `-o` 落盘（按 `-f` 补扩展名，目录自动命名，`-o -` 强制 stdout）/ `--no-cache` / `--no-proxy` / `--proxy URL`
- 退出码：0 成功 / 2 用法错误（提示走 stderr）
- 缓存 TTL：search 60s / fetch 10s / 跳转解析 10min / zen 模型清单 1h
- 插件与配置：`webtool plugins list`（清单与来源 builtin/user/code）· `check`（逐个加载体检）· `reload`（重载外部插件）。改 `~/.webtool/plugins.json`、`filters.json` 自动生效（按 mtime 判定），改外部插件 `.py` 需 `plugins reload`

## 注意

- 出网全走浏览器指纹（UA/TLS 由 impersonate 同源生成），传输层直连优先、失败才探活代理重试
- google / docs.rsshub.app 被墙，必须代理：`webtool proxy set http://127.0.0.1:2080`；未配置时相关命令立即说明不空等
- 报错自带处置建议（换引擎 / 切 `--profile` / 配代理），照做即可
- 优先 fetch 而非啃原始 HTML
