---
name: webtool
description: 网页搜索与内容获取 CLI。多引擎搜索（含 exa 语义搜索）+ 榜单聚合 rank（知乎/微博/抖音/B站/HN/GitHub Trending 等 19 源）+ 18 站点站内搜索 site + RSS 订阅 feed（RSSHub 路由库 radar 查询填参、增量、坏源登记）+ zen 免费层 LLM 对话 + 通用 MCP 客户端 mcp + 股票能力 stock（实时行情/涨停池/选股池/单股深度/风险核查/公告财务，桥接 stock-master + 多源编排）+ 正文提取转 markdown/text/json。当用户提到「搜索网页 / 查资料 / 抓网页正文 / 热榜 / 榜单 / 订阅 / RSS / 站内搜索 / 问大模型 / MCP / exa / 股票行情 / 涨停 / 选股 / 个股分析 / 资金流 / webtool」时触发。
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
webtool stock quote 600519 创业板指            # 实时行情 (桥 stock-master + 多源编排)
webtool stock analyze 600519                  # 单股深度 (技术面 + 100 分制评分 + 信号)
webtool stock screen --min-score 70           # 短线选股 (含剔除清单)
webtool stock tools                           # 24 个动作清单
webtool stock report 600519                   # 成稿研报 (markdown)
webtool stock sentiment --text "业绩超预期"     # 消息面打分 -100~+100
webtool stock data find 龙虎榜                 # 跨域搜 4 类目录 (eco/api/em配方/docs)
webtool stock data list                       # 15 个功能域总览 (每域接口数)
webtool stock data list 龙虎榜                 # 域内明细 (api 分类 + eco 接口 + em 配方)
webtool stock data 行情 find 茅台              # 域内搜 (eco 结果按域过滤)
webtool stock data call RPT_LICO_FN_CPD --arg date=20260331   # 按名调 (em配方→api→eco)
webtool stock data call sse_yunhq_snap --arg code=sh600519    # 数据源层方法
webtool stock data url "https://qt.gtimg.cn/q=sh600519"       # 裸 HTTP (反爬内置)
webtool stock data list api                   # 数据源层 154 方法 (按源分组)
webtool stock docs-search companyType         # 查底层接口文档 (URL/参数/字段含义)
webtool stock holder 600519                  # 股东研究 (东财)
webtool stock health                         # 三侧桥接探活
webtool config set default_engines bing,sogou
webtool --version                           # 版本/Python/依赖 (报障第一句)
webtool upgrade --check                     # 查新版: 0 最新 / 1 有新版 / 2 判不出
webtool upgrade                             # 升级 (pip 升降, 线路按 rules.json)
```

## search

- 引擎：bing / sogou / baidu / so360 / marginalia（境内可直连；配了规则/代理就照样走）／ google（**直连必然不通**，代理不可用时静默跳过；429 自动降级 news RSS，结果 `channel: news` 且链接已还原原文 URL，直接 fetch）／ exa、parallel、firecrawl（MCP 语义搜索，均匿名免 key，均**默认不开**）
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
webtool zen --list-free               # 免费层清单 (表格: 模型/提供方/上架/免费层)
webtool zen --list-free --check       # 逐个真调出实测结果 (加 --check-all 验全表)
webtool zen "问题" --system "只回 JSON" --tool-choice none
webtool zen "问题" --tools all          # 工具集: min(默认 bash+read)/all/逗号清单
webtool zen "问题" --dry-run            # 打印将要发出的请求 (URL+头+体), 不出网
webtool zen "问题" --show headers       # 只看一段: request(默认)/headers/body/text
webtool zen "问题" --no-sticky          # 每次运行都换 ses_id (默认是粘性)
```

模型上下架频繁，别凭记忆报模型名，先 `--list-free`（表格列取接口字段，免费层按命名约定）。
免费层 403 的两道判据（2026-10-14 抓包二分坐实）：① 端点必须 `/inference/v1/chat/completions`（`/zen/v1` 那条不给免费层）；② body 的 `tools` 要用官方原版 schema 且 `tool_choice=auto`，最小集 bash+read（只要一个、空壳 schema、描述截到 400 字以下都 403）。另需 `User-Agent`/`x-opencode-session-id`/`Authorization: Bearer public` 三个头。猛打会 429 限流，指数退避重试。

- 会话 id 默认**粘性**：存 `~/.webtool/sticky.json`，按**整点**轮换（`floor(now/3600)`，HH:00:00 换新，不是"创建满一小时"），同小时内跨进程复用同值；`--no-sticky` 每次运行换新。注意它只有会话稳定性意义——实测免费层 `cached_tokens` 恒为 0，开不开耗时无差异，别当提速手段
- JSON 里 `usage_available` = 上游是否返回用量；`false` 且 `ok: true` 是"调用成功但端点不给统计"，不是故障
- 排查请求看 `--dry-run`（URL+头+体，不出网）或 `--show request|headers|body|text`；要整结构 `-f json`。`--tools min/all/逗号清单` 选工具集，`--no-live` 只是不边收边打（body 恒 `stream:true`，闸门判据，关不掉）
- 请求头与真机逐项对齐（真机 13 个）：我们手写 10 个，`Host`/`Content-Length` 由 http.client 补，`Connection` 被 urllib 写死成 `close`（真机是 `keep-alive`；要发出去只能弃用 urllib 自己写报文，而 urllib 本就不复用连接，收益 0，不做）；头名发出去时被 urllib `.title()` 规范化成 `X-Opencode-Session-Id`（真机小写，HTTP/1.1 不敏感，实测不影响闸门）。`Accept-Encoding` 照抄真机，配套 gzip/deflate 增量解压兜底，br/zstd 会明确报错而不是喂乱码。`--dry-run` 打的就是这套服务端视角的头
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
- 端点声明（url / verbs / api_key_env）在 `data/mcp.json`，`engines/exa.py` 引擎与 `webtool mcp` 共用同一份数据
- 端点别名可自建：`~/.webtool/mcp.json` → `{"mcp":{"别名":{"url":"...","api_key_env":"MY_KEY","verbs":{...}}}}`
- key 只经环境变量名映射，配置文件不存明文；免 key 服务不发认证头
- **exa 免 key 配额按出口 IP 计**：走全局代理等于蹭别人的配额池，实测必 429、直连才稳。端点表**不再**给它写死线路（那是替用户做决定），要它稳就显式配 `webtool config set engine_proxy.exa direct` 或加一条 exa 域名的 `direct` 规则；临时用 `--no-proxy`
- **传参两条通道可并存**：`--arg k=v`（可多次，值按 JSON 字面量猜 int/bool/null/数组，含空格/中文/URL 原样保留）或位置 JSON；同给时 `--arg` 覆盖
- **先 `probe`/`list` 再 `call`**：免 key 与带 key 暴露的工具集可能不同（实测 exa 免 key 仅 `web_search_exa` + `web_fetch_exa`，带域名/日期过滤的 `web_search_advanced_exa` 需 key）
- 免 key 有真实限额，**响应头无任何预告**，只能撞 429 才知道；配额**按出口 IP** 计。撞 429 先怀疑走了代理，按上面配 `engine_proxy.exa direct` 即恢复；仍受限则配 `EXA_API_KEY`（自动生效，`--apikey` 可临时覆盖）
- `list` / `probe` 不消耗搜索额度，只有 `call` 计
- 失败走 stderr + 退出码 1，错误体原样带出

## stock

桥接两侧股票能力，不复制业务逻辑，**全链路纯进程内、不起子进程、不经协议层**：**stock-master 桥**（行情/涨停池/选股/风险）与 **编排层**（多源回退；公告/财务/股东/K线等 24 个动作）。

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

# 第四侧: 生态库 (akshare 1099 / tushare 124 / baostock 29)
# 覆盖宏观/另类数据/期货/基金/外汇等数据源层没有的领域, 返回 DataFrame
# 默认给 shape + 前 5 行预览 (全市场快照这类接口动辄几千行), --full 取全量
webtool stock eco-health                     # 各库可用性与接口数
webtool stock eco-list stock_zh_a_hist        # 看接口签名与文档
#   注意: akshare 有些接口很慢 (stock_zh_a_spot_em 全市场快照约 76s), --full 慎用

# 第三侧: 数据源层 154 个低阶方法 (包化: stock/bridge/sources/, 按数据源分包)
# 编排层只聚合了 56 个成 24 个动作; 其余 97 个（股东研究/盈利预测/研报日历/
# 早盘晚报/板块多维排行/分钟线/产业链分类…）从这里直接调
webtool stock api-list                        # 按数据源分组列全部方法
webtool stock api --method ths_rank_cxfl --arg sort_type=1   # 调任一方法
webtool stock api --method sina_kline_min --arg symbol=sh600519 --arg scale=5
webtool stock holder 600519                   # 股东研究摘要 (户数趋势/前十大/机构)
webtool stock forecast 600519                 # 盈利预测 (东财)
webtool stock mcp --tool stock_kline --arg symbol=600519
webtool stock tools                           # 24 个动作清单;  health  # 两侧探活
```

- **两侧都只做桥接**：数据源与口径归数据源层与 stock-master 技能维护。三块（数据源层 154 方法 / stock-master skill / 编排层 24 动作）都已包进 `webtool.stock`，用静态 import 接入，不改 `sys.path`，**无需额外安装**；缺失时只让 stock 动作退 2，不影响其他命令
- **依赖只有包内一条路**：`webtool.stock` 包内静态 import，没有 `STOCK_*_HOME` 环境变量覆盖（数据源层共享同一个 `APIClient`，token/session 缓存只有一份）。`webtool stock health` 三段都标 `source: packaged`
- **纯进程内**：单次调用 0.1-2s。直接调编排层函数，不起子进程、不走协议握手、不套信封。stock-master 的 `webtool search` 子进程出口在运行时被注入成进程内实现，不改 skill 文件
- **动作清单读编排层 `t_stock_*` 函数名**，增删动作自动跟上
- **失败语义**：handler 抛异常或返回 `ok=False` 都按"调用失败"处理（stderr + 退出码 1），不会崩进程
- **`api` 动作的 text 只给摘要**（状态/来源/各键条目数），不倾倒原始 JSON —— 股东研究一家返回 34KB。全量用 `-f json`。`holder` 有专门的摘要渲染（户数趋势 + 前十大 + 机构持股）
- **`eco` 返回含 `datetime.date` / numpy 标量**，渲染层走 `command.py::_j` 做 JSON
  兜底转换 —— 直接 `json.dumps` 会 TypeError 崩在渲染层（数据其实已经取到了）
- **`api` 动作不套"未解析"守卫** —— 数据源层有些接口（如 `ths_stockpage_finance`）本身就返回 HTML 表格，套 news 那个守卫会误报
- **report / diagram / excel 原样透传**（成稿 markdown、mermaid 源码、落盘确认），不再包 JSON 或表格 —— 这些产出本来就是给人直接看的。sentiment 分数带符号印出（`+12` 而非 `12`），方向是消息面的关键信息
- **`report` / `excel` 跑短线池会扫全市场**（约 70 秒），别放进交互式调用；`excel` 缺 openpyxl 会明确报错而非静默不出文件
- **口径纪律**：涨停池必带真实数据日（该接口对无效日期会静默回旧数据）；北向 `status=3` 或接口回填额度上限一律标 ⚠「未取得」，**禁止当 0**；上游回了原始 HTML 未解析出条目时显式标注，不把 100KB 噪声当结果
- `--arg` 纯数字一律留字符串（600519 是代码，整数会被动作参数校验拒）—— 与 `webtool mcp` 口径不同
- `screen` 输出必含**剔除清单与闸门原因**，只给通过名单会让调用方以为没被选中的票不存在
- 退出码：0 成功 / 1 数据动作失败 / 2 用法错误

## 通用约定

- `-n` 条数 / `-f` 格式（`md`≡`markdown`、`txt`≡`text`，大小写不敏感）/ `-o` 落盘（按 `-f` 补扩展名，目录自动命名，`-o -` 强制 stdout）/ `--no-cache` / `--no-proxy` / `--proxy URL`
- 退出码：0 成功 / 2 用法错误（提示走 stderr）
- 缓存 TTL：search 60s / fetch 10s / 跳转解析 10min / zen 模型清单 1h
- 证书校验：默认严格（fail-closed）。`webtool config set ssl_verify on|off` 总开关 · `ca_bundle <ca.pem>` 自定义 CA · `verify_hosts a.com,b.cn` 点名豁免自签/过期证书站（覆盖子域，其余域仍严格，优先于全局开关）。`webtool config list` 看**实际生效**策略与 CA 来源。证书失败抛 `TlsError` 直接报错，不进换指纹/换代理的降级梯
- 插件与配置：`webtool plugins list`（清单与来源 builtin/user/code）· `check`（逐个加载体检）· `reload`（重载外部插件）。改 `~/.webtool/plugins.json`、`filters.json` 自动生效（按 mtime 判定），改外部插件 `.py` 需 `plugins reload`
- 规则路由（按请求目标分流，不只是按引擎名）：`webtool proxy rule add '{"domain":["*.cn"]}' direct` · `add '{"geosite":["cn"]}' direct`（按域名库判，**不解析 DNS**，不受 CDN 就近解析影响）· `add '{"geoip":["CN"]}' direct` · `add '{"port":[8080]}' proxy:tokyo`（命名代理）· `add '{"domain":["ads.io"]}' block` · `rule del 2`（0 起）· `webtool proxy rules [URL]`（列规则 / 试算某 URL 走哪条线）。命名代理用 `webtool proxy named <名字> <URL>` 配（`named list` / `named del <名字>`），**密码同样进保险库**，`rules.json` 只留 `user@host`，老配置里的明文密码加载时自动迁移。**顺序即优先级**，第一个命中的生效；`match` 内多条件 AND、同条件内多值 OR。库：MaxMind `.mmdb` 或 v2ray/sing-box 的 `geoip.dat`/`geosite.dat`，用 `webtool proxy geosite <路径>` / `geoip <路径>` 配（配完立即自检）。**判不出来=不匹配**（缺库则该条规则跳过并提示），不会当成匹配放行
- 代理凭据：`webtool proxy set http://user:pass@host:port` 会把密码**加密**存进 `~/.webtool/config.json` 的 `proxy_auth`，配置文件只留用户名，出网前才在内存解密。`webtool proxy setpass <用户名> [<密码>]` — **省略密码即终端交互输入且不回显**（推荐）；给位置参数方便脚本但明文会进 shell history；`echo "<密码>" | webtool proxy setpass <用户名>` 走管道（Agent/脚本用）· `proxy passwd`（保险库状态）· `proxy delpass <用户名>`。日志与报错里的密码出口处统一脱敏成 `***`；保险库缺密码时直接报错指出该跑哪条命令，不拿空密码去撞 407。需 `cryptography`（`pip install webtool[secrets]`），没装则拒绝存密码而非降级成明文

- `upgrade` 只走 pip, 不碰本地源码; 装的是 editable/本地目录时, pip 会用 git 版覆盖它 —— 本地开发想更新请自己在仓库里收代码

- 装的时候报 `externally-managed-environment` (Kali/Debian/新 Alpine 的 PEP 668 保护) → 装进 venv 或 `pipx install`, 别用 `--break-system-packages`; `--user` 是开关, 不带值
## 注意

- 出网全走浏览器指纹（UA/TLS 由 impersonate 同源生成）。**走哪条线一次定死**：`proxy` 配置 + 路由表在请求前决定，请求失败就是失败，不做"直连→代理"或"代理→直连"的隐式切换（否则同一次调用走哪条线取决于它先在哪失败，而"代理失败退直连"恰恰会毁掉只允许代理出网的目标）。要全直连 `--no-proxy`，要单点覆盖 `engine_proxy.<引擎名>` 或规则表
- 出网统一走 `webtool.net.netx`（`netx.get(url, proxy=..., verify=...)`）：**代理归一（`auto` 问路由表、`user@host` 补保险库密码）、证书策略、浏览器指纹默认头都在这里做一次**。别在其他模块自己判断 `proxy == 'auto'` 或再调 `resolve_auth`——历史上正是这种重复导致 `stock/http.py` 完全绕开代理与路由表。已接入：`stock/http.py`（`Http(proxy=...)`，默认 auto）、`core/probe.py`、`core/http.py`、`net/transport.py`；加新通道只需实现 `_run()` 分支
- google / docs.rsshub.app 被墙，直连必然不通：`webtool proxy set http://127.0.0.1:2080` 或加 `direct`/`proxy` 规则；google 在代理探活失败时静默跳过，docs.rsshub.app 相关命令会立即说明不空等
- 撞证书错误别反复重试也别全局关校验：报错里已给出域名，按提示 `webtool config set verify_hosts <域名>` 点名豁免即可
- 分流优先用 `geosite` 而不是 `geoip`：前者按域名分类查库，不解析 IP，不会因 CDN 就近解析把境内站判到境外、进而该直连的走了代理
- 手写规则错一条只废那一条（非法动作/缺 match/非对象都会被跳过并在 `proxy rules` 里列出原因），但**规则表整体损坏时退回全局代理而非纯直连** —— 后者会让必须代理的目标直接连不通
- 代理 URL 里的密码别反复重输：`proxy setpass` 存一次就够，后续 `proxy set http://user@host:port` 即可；报错或 `proxy rules` 输出里的密码已脱敏成 `***`，看到 `***` 是正常的不是配置坏了
- 报错自带处置建议（换引擎 / 切 `--profile` / 配代理），照做即可
- 优先 fetch 而非啃原始 HTML
