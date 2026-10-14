# webtool

网页搜索与内容获取 CLI。输出 markdown/text/json。

## 安装

```bash
pip install 'git+https://github.com/itingyu/webtool'
# 依赖**全部**随安装自动装 (trafilatura / curl_cffi / pysocks / typer / certifi
# / cryptography / maxminddb / requests / pandas / numpy / urllib3 / efinance
# / openpyxl / akshare)。没有 extra 分档 —— 全装是唯一形态。
```

系统 Python 被发行版保护时（Kali / Debian / Ubuntu 23.04+ / 新版 Alpine），上面那条会被拒：

```
error: externally-managed-environment … PEP 668
```

这不是包的问题，是发行版不让 pip 往系统 Python 里塞东西（追 PEP 668）。三条路，按推荐排序：

```bash
# 1) venv（最省事，官方也这么建议）
sudo apt install python3-full python3-venv          # Alpine: apk add python3
python3 -m venv ~/.webtool-venv
~/.webtool-venv/bin/pip install 'git+https://github.com/itingyu/webtool'
~/.webtool-venv/bin/webtool search "test"           # 直接用 venv 里的 webtool

# 2) pipx（想要 webtool 这种"命令行应用"，它自动给你建 venv 并挂到 PATH）
sudo apt install pipx && pipx install 'git+https://github.com/itingyu/webtool'

# 3) --user（装到 ~/.local，不动系统 Python；注意 --user 是**开关不带值**）
pip install --user 'git+https://github.com/itingyu/webtool'
```

`--break-system-packages` 能硬闯，但会把系统 Python 搅乱（Kali 上一堆工具靠它），不建议。
千万别写 `--user=你的用户名` —— `--user` 不吃值，pip 会直接报
`--user option does not take a value` 然后什么都不装。

**Termux / Android 上不能直接 `pip install`** —— PyPI 只发 manylinux/macos/win 的
轮子，没有 `android_*` 平台，`cryptography`/`numpy`/`pandas`/`lxml` 只能从源码构建。
其中 `cryptography` 要 Rust，而 rustup 不认 `aarch64-unknown-linux-android` 这个 target，
装在 `Preparing metadata` 那步就断：

```
Target triple not supported by rustup: aarch64-unknown-linux-android
ERROR: Failed to build 'cryptography' when installing build dependencies
```

那条路走不通，得让 Termux 自己的包供原生库（**flavour 要选 termux，不是 glibc** 的那种）：

```bash
pkg install tur-repo                        # pandas 只在 TUR 第三方源里
pkg install python-cryptography python-numpy python-pandas python-lxml
pip install 'git+https://github.com/itingyu/webtool'
```

先装原生库、再 `pip install`：pip 看到它们已被满足就只装**纯 Python 的那些**
（trafilatura / typer / akshare / efinance / openpyxl …）和 `curl_cffi`
（它自带 `android_24_arm64_v8a` 轮子）。顺序不能反 —— 反过来 pip 一上来就要构建
cryptography，又回到上面那个报错。少库时 webtool 的报错也会直接给出 `pkg install`
那一条（`core/deps.py` 认得出 Termux），不会再让你"重装 webtool"原地打转。

git 装法的升级是**强制重装自己那份代码**：我们不按 commit 改版本号，pip 光比版本号会以为
"已最新"什么都不干，所以 `upgrade` 对 git 源走 `--force-reinstall --no-deps`（只换代码，不动依赖）。
`upgrade --check` 除了版本号还会比一次远端 HEAD，所以**同版本的新提交也看得见**；索引来源
（PyPI 等）仍按版本号走。

装完升级走同一条路：venv/pipx 环境里的 `webtool upgrade` 调的是**它自己**那个 pip；
`webtool upgrade --check` 先干跑一遍问有没有新版（退出码 0 最新 / 1 有新版 / 2 判不出）。

依赖声明在 `pyproject.toml`（**唯一权威**，`pip install` 会按它自动装；全装是唯一形态，没有 extras）。
`requirements.txt` 是从它生成的清单，改完 pyproject 跑
`python3 scripts/gen_requirements.py` 重新生成（`tests/test_smoke.py` 会校验一致，手改会被测出来）。
"import 了却忘了声明"由 `python3 scripts/audit_deps.py` 兜住 —— 已捞过 certifi / numpy / urllib3 / efinance 四个。

代码按分层分包（`cli` → `feeds`/`radar`/`zen` → `pipeline`/`render` → `net`/`engines` → `core`），只允许向下依赖。改代码前先读 [docs/coding-standard.md](docs/coding-standard.md)，整体设计见 [docs/design.md](docs/design.md)。

## 卸载

默认就是**安全卸载**：只卸包，`~/.webtool` 里的配置、规则、凭据、缓存一概留着，装回来即原样。

```bash
webtool uninstall                      # 安全卸载（默认）: 只卸包
webtool uninstall --dry-run            # 只看会跑什么，不动手
webtool uninstall --purge-data --yes   # 完全卸载: 连配置/凭据/缓存一起删
```

卸载命令按装法给：venv 用 venv 里的 pip、pipx 用 `pipx uninstall`、`--user` 装的就带 `--user`
那套，发行版包管理器装的被 pip 拒时会指回 apk/apt。`--purge-data` 单独用**什么都不做**（rc=2）：
删除不可逆，确认得明说。数据目录里 `secret.key`（保险库密钥）、`rules.json`（手写路由规则）、
`sites/`、`feeds.json`（自己加的源）删了要重配，`cache/`、`state.json`、`sticky.json` 可再生。

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
webtool stock quote 600519 创业板指              # 实时行情 (engine 脚本层 + 多源编排)
webtool stock analyze 600519                    # 单股深度 (技术面+100分制评分+决策信号)
webtool stock pool --only-buy                   # 涨停池 (只留可买板块)
webtool stock screen --min-score 70             # 短线选股 (含剔除清单)
webtool stock flow --scope industry             # 资金流榜单
webtool stock tools                             # stock 24 个动作清单
webtool stock health                            # 两侧桥接探活
webtool -v | --version                          # 版本号 (放子命令后也认)
webtool --version -f json                       # 完整体检: Python/平台/代码路径/依赖, 报障贴这个
webtool upgrade --check                         # 只问有没有新版 (退 0 最新 / 1 有新版 / 2 判不出)
webtool upgrade                                 # 升级到最新 (pip 走 rules.json 判定的线路)
```

## 功能

### search
- 引擎：bing / sogou / baidu / so360 / marginalia（境内可直连，配了规则/代理也照样走）／ google（直连必然不通，靠全局代理/规则表走线，429 降级 news RSS，链接已还原原文 URL）／ exa（MCP 语义搜索，免 key，**默认不开**）/ parallel（MCP 语义搜索，**匿名免 key**，**默认不开**）/ firecrawl（MCP 搜索，**匿名免 key**，**默认不开**）
  - 走哪条线由 `webtool config set proxy` + 规则表决定，引擎之间不再有硬编码差异。境内站想要直连：`webtool proxy rule add '{"geosite":["cn"]}' direct`
  - `exa` 走 Exa MCP 的 `web_search_exa`，免 key 配额按**出口 IP** 计，走代理等于蹭别人的配额池（实测带代理必 429）。需要它时加一条 exa 域名的 `direct` 规则：`webtool proxy rule add '{"domain":["exa.ai"]}' direct`，**没有隐式绕过**。不进默认组合，按需 `-e exa` 或加进 preset
  - `parallel` 走 Parallel Search MCP 的 `web_search`，**匿名免 key 可用**（fast 模式），注册后每月 $5 循环额度（$1/1000 请求 ≈ 5000 次/月），配 `PARALLEL_API_KEY` 自动生效。返回 JSON 含 `publish_date`，比 exa 的纯文本更好解析，实测也更快（1.4–2.0s vs 2.6s）。
  - `firecrawl` 走 Firecrawl MCP 的 `firecrawl_search`，**匿名免 key 可用**，免费层 500 次/月 search 或 1000 页 scrape，配 `FIRECRAWL_API_KEY` 自动生效。它的 `firecrawl_scrape` 能过 JS 渲染页，是 `fetch --via` 的最佳兜底通道。
  - 三者召回都是**语义**而非关键词，与 bing/sogou 重叠少，作为长尾与英文技术内容的补充源最划算。实测召回各有胜负（同一查询 exa 条数更多、parallel 更快且带日期），按需挑或并用。
- `-e` 组合引擎；跳转链默认自动解码；query 精简（核心实体 + 意图词，优先英文）
- 结果按 `prior × √(pos×base_avg) × sem` 加权排序，尾部低质由 `weight_floor` 挡掉；`-f json` 看 `weight` 与 `engines`（交叉验证数）
- `--preset <组>` 用引擎组合预设，省得手拼 `-e`。优先级 `--engine` > `--preset` > `config.default_engines` > 清单里默认开启的引擎

  ```bash
  webtool engines presets                         # 列预设
  webtool search "查询词" --preset zh              # bing,sogou,baidu,so360
  webtool search "query" --preset en              # bing,google,marginalia (含直连不通的 google)
  webtool search "查询词" --preset direct          # 全部免代理需求的引擎 (配了全局代理仍走代理, 要真直连加 --no-proxy)
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
webtool zen --list-free               # 免费层清单 (表格: 模型/提供方/上架/免费层)
webtool zen --list-models             # 全量清单
webtool zen --list-free --check       # 逐个真调, 出"实测/耗时/首答" (默认只验免费层)
webtool zen --list-free --check-all   # 连收费模型一起验 (80+, 慢且易被限流)
webtool zen "问题" --system "只回 JSON" --tool-choice none
webtool zen "问题" --tools all        # 工具集: min(默认 bash+read)/all/逗号清单 (bash,read,grep)
webtool zen "问题" --dry-run          # 打印将要发出的请求 (URL + 请求头 + 请求体), 不出网
webtool zen "问题" --show headers     # 只看一段: request(默认)/headers/body/text
webtool zen "问题" --no-live          # 不边收边打, 攒到最后一次性输出 (请求始终 stream, 闸门要求)
webtool zen "问题" --no-sticky        # 会话 id 每次运行换新 (默认粘性: 每整点轮换)
webtool zen "问题" --think high       # 思考强度 (默认 medium; 可选值随模型而异, off 表示不带该字段)
```

- **流式输出**：在终端里默认边收边打（思考与回答都实时出）。输出被管道接走或 `-f json` 时自动改为一次性输出，管道里拿到的正文才干净
- **终端着色**（非终端 / `NO_COLOR` 时自动关闭）：思考灰、工具调用黄、`[思考]`/`[回答]` 分段标签青，正文原色
- **思考标签兜底**：个别模型把思考塞进正文并用 `</think>` 之类标签包着；这类标签会被剥掉，标签前的内容并入思考、之后的才算答案（跨 chunk 的标签也认得）
- **思考强度** `--think`：原样透传给上游 `reasoning_effort`，默认 `medium`。可选值**随模型而异**（有的只认 low/medium/high，有的还收 xhigh/minimal，有的不吃这个字段），客户端不预判；真发出去被拒（400 且报错提到 effort）会自动去掉该字段重试一次，并明确提示
- **默认值都能配**：`model` / `max_tokens` / `reasoning_effort` / `system` / `tools` / `tool_choice` / `live` 的默认写进 `~/.webtool/zen.json` 的 `zen` 段（`~/.webtool/zen.json` 与包内 `data/zen.json` 深合并，mtime 热生效）。优先级：**命令行 > zen.json > 内置**（`max_tokens` 内置 200000）

```jsonc
// ~/.webtool/zen.json —— 只写要改的键即可
{"zen": {"model": "mimo-v2.6-flash-free", "max_tokens": 8000,
         "reasoning_effort": "high", "tools": "all", "live": false,
         // 原样并进请求体, 补上游字段 (同名字段以它为准)
         "extra_body": {"thinking": {"type": "enabled", "budget_tokens": 8000}}}}
```

`extra_body` 是本客户端**唯一**的自定义请求体入口：像 `thinking` 这类上游扩展字段没有独立开关，直接从这塞；实测加未知字段不会触闸门（免费层 403），但也不会被校验，写错了上游可能静默忽略。

模型上下架频繁，先 `--list-free` 再用。清单列取接口字段（`id/created/owned_by`），
免费层是命名约定推断的；能不能用只有 `--check` 真调一次才算数。

免费层 403 FreeTierError 的真相（2026-10-14 用官方 1.19.0 抓包逐项二分坐实）：
闸门看**两件事**，任缺其一即 403——
1. 端点必须走 `/inference/v1/chat/completions`（旧的 `/zen/v1` 那条服务不给免费层）；
2. body 里 `tools` 必须是官方原版 schema 且 `tool_choice=auto`。最小可用集是 **bash+read 两个**（全量 12 个也行）；只要 read 或只要 bash、空壳 schema、描述截短到 400 字以下，全部 403。
请求头要带 `User-Agent` / `x-opencode-session-id` / `Authorization: Bearer public`，缺一项也 403（大小写/顺序/Accept-Encoding/Connection 都不敏感）。
按此发请求即可拿到流式回答；连着猛打会被 `429 FreeUsageLimitError` 限流，退避重试（指数 2/4/8s，尊重 Retry-After）。

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

**Exa、Parallel、Firecrawl 都已并入 `search` 引擎池**（`webtool search -e exa` / `-e parallel` / `-e firecrawl`），不再有独立的 `webtool exa` 命令 —— 原 `exa search` 用引擎替代，`exa fetch` / `exa list` 分别由 `webtool fetch` 与 `webtool mcp list exa` 覆盖。端点声明（url / verbs / api_key_env）在 `data/mcp.json`，三个 `engines/*.py` 与 `webtool mcp`、`webtool fetch --via` 共用同一份数据。三者均匿名免 key：Exa 撞限额返回 429 并提示配 `EXA_API_KEY`；Parallel 注册后每月 $5 额度，配 `PARALLEL_API_KEY` 生效；Firecrawl 免费层 500 次/月 search 或 1000 页 scrape，配 `FIRECRAWL_API_KEY` 生效。

- 端点别名在 `src/webtool/data/mcp.json`，用户可建 `~/.webtool/mcp.json` 同构覆盖：`{"mcp":{"my_srv":{"url":"...","api_key_env":"MY_KEY","verbs":{"search":"..."}}}}`
- **代理策略**：端点表不声明线路，所有请求统一跟随 `proxy` 配置与规则表。要给单个端点指定线路，加一条针对它域名的规则；`--no-proxy` 全局临时绕过。exa 免 key 配额按**出口 IP** 计，走全局代理等于蹭别人的配额池——实测同一命令带代理必 429、直连稳定通过，所以需要它时得**显式**配直连规则
- key 一律经**环境变量名**映射，配置文件不存明文；免 key 服务不发认证头
- **传参两条通道，可并存**：`--arg k=v`（可多次；值按 JSON 字面量猜 `int`/`bool`/`null`/数组，含空格/中文/URL 的原样保留）或位置 JSON `'{"k":"v"}'`；两者同时给时 `--arg` 覆盖同名键
- `--tools a,b` 下发工具白名单（`?tools=`），缩小 Agent 选择面
- **先 `probe` / `list` 再 `call`**：免 key 与带 key 暴露的工具集可能不同（实测 exa 免 key 只有 `web_search_exa` + `web_fetch_exa`，带过滤的 `web_search_advanced_exa` 需 key）
- 失败走 stderr 并返回退出码 1，错误体原样带出（如 429 限额提示会告诉你 key 怎么配）
- 内核在 `net/mcpclient.py`，已抽出 `parse_response` / `parse_sse_message` 两个纯函数，可被其他 MCP 源直接复用

### stock
把**股票能力**收进 webtool，两座桥：

- **engine 脚本层**（`stock/engine/`，静态 import）：行情 / 涨停池 / 可买性 / 交易日历 / 资金流 / 单股深度 / 选股池 / 风险核查。**取数一律经 `bridge/sources/`**（腾讯/东财/雪球/同花顺多源 fallback），这一层只留业务口径
- **stock 数据桥**（进程内直调服务端 handler）：公告 / 财务三表 / 股东 / K线 / IPO / 分红 / 两融 / 指数成分 等 24 个工具

**全链路纯进程内，不起子进程、不经 MCP 协议**：服务端的 `TOOLS` 注册表每项自带 handler 函数，直接调它拿到的就是工具自己的结果 dict（没有 JSON-RPC、没有 content 信封的序列化往返）；engine 的 `clients.mcp()` 直接调 `bridge/srv.py` 的 handler（进程内），不再起 `minis-mcp-cli` 子进程。实测单次调用 0.1-2s，相比原先每次起子进程（2.5-2.9s）省一个数量级。

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
webtool stock report 600519                     # 成稿研报 (markdown, 单股)
webtool stock report --pool short               # 短线池研报 (慢: 扫全市场 ~70s)
webtool stock excel --excel picks.xlsx --min-score 70   # 选股池导出 xlsx (4 sheet)
webtool stock sentiment 600519                  # 该股新闻的消息面打分 -100~+100
webtool stock sentiment --text "业绩超预期"       # 或直接对给定文本打分
webtool stock diagram --kind tree               # mermaid 决策树
webtool stock diagram 600519 --kind logic --name 贵州茅台 --thesis "稀缺性"
webtool stock diagram --kind chain --name 白酒 --driver 高粱 --mid 酿造 --catalyst 提价
webtool stock mcp --tool stock_kline --arg symbol=600519 --arg period=day
webtool stock tools                             # 24 工具清单
webtool stock data list api                      # 数据源层 156 方法 (按源分组)
webtool stock api --method ths_rank_cxfl         # 直接调任一低阶方法
webtool stock holder 600519                     # 股东研究 (东财)
webtool stock forecast 600519                   # 盈利预测 (东财)
webtool stock eco-health                        # akshare/tushare/baostock 可用性
webtool stock eco-search 龙虎榜                 # 在 1099 个接口里搜
webtool stock eco --method stock_zh_a_hist --arg symbol=600519
webtool stock http-get "https://qt.gtimg.cn/q=sh600519"   # 底层 HTTP 直调 (反爬已内置)
webtool stock http-rows <URL> --pick data.0.quote          # 直调并转表格
webtool stock em-report RPT_LICO_FN_CPD --arg sort=Col,Col  # 东财 datacenter 取数
webtool stock em-ctype SH600519                            # 探测 companyType
webtool stock docs-report RPT_LICO_FN_CPD       # 查底层接口: 参数表+字段列序映射+源码行号
webtool stock docs-stats                       # 逆向文档总量 (7 分册 / 122 reportName / 322 端点)
webtool stock health                            # 四侧探活
```

- **两侧都不复制业务逻辑**，只是进程内 import；外部数据源没装时 `stock health` 报 unavailable，不拖垮 webtool 其他命令。依赖只有包内这一条路，没有环境变量能改
- **第五侧：底层 HTTP 直调**（`stock/http.py`）。`rawapi` 只能调数据源层封好的 156 个方法、`eco` 只能调 akshare/tushare 现成函数——本模块**不封装**，直接拼 URL 发请求，因此逆向出的 900+ 接口全部可调，包括 akshare 没封或封了不可用的（东财 `companyType` 探测、`quoteColumns` 注入、`dates` 批量取表）。**反爬已内置**：雪球走 curl_cffi chrome110 指纹 + token warmup，新浪/中证自动带 Referer，东财 push2 自动补 `ut`、datacenter 自动补 `token`/`source`/`client`，腾讯 GBK 自动解码。动作：`http-get`/`http-post`/`http-rows`/`em-report`/`em-ctype`
- **第六侧：逆向接口文档**（`src/webtool/stock/data/reverse/`，7 分册 9134 行，从 akshare 源码**手工逆向**）。前三侧给的都是**函数名**，这一侧给的是**底层 HTTP 细节** —— 端点 URL、`reportName`/`filter`/`columns` 怎么拼、返回字段（`SECURITY_CODE`/`ACCEPT_DEPOSIT_INTERBACC` 这类缩写）对应第几列、哪些接口已下线/需要 token/列序会静默错位。每条记录带源码 `文件:行号` 可回溯。动作：`docs-books`/`docs-stats`/`docs-search`/`docs-book`/`docs-section`/`docs-report`/`docs-endpoint`。akshare 某函数返回空或字段错位时，`docs-report <reportName>` 是首选排查动作
- **第四侧：生态库 1291 个接口**（`akshare` 1099 / `tushare` 124 / `baostock` 29 / `efinance`，返回 DataFrame）。覆盖 API 文档里 `函数.json` 记录的 akshare 生态，含宏观、另类数据、期货、基金、外汇等数据源层完全没有的领域。`webtool stock eco <接口>` 直接调，默认给形状+前 5 行，`--full` 取全量；`eco-search` 按中英文关键词搜接口
- **第三侧：数据源层 156 个低阶方法**（`stock/bridge/sources/`，按数据源分包：ths/sina/xueqiu/em/gtimg/tencent/cninfo/sse/csindex/ef）。编排层只把其中 58 个聚合成 24 个动作，另外 96 个（股东研究/盈利预测/研报日历/早盘晚报/板块多维排行/分钟线/产业链分类…）通过 `webtool stock api <方法>` 直接调。三块（数据源层 / engine 脚本层 / 编排层）都包进 `webtool.stock`，静态 import 接入，装包即用；数据源层共享同一个 `APIClient`（token/session 缓存只有一份）。`webtool stock health` 三段都标 `source: packaged`
- **动作清单读编排层 `t_stock_*` 函数名**，增删动作 webtool 自动跟上
- **口径纪律（从 stock-master 继承，现由 engine 维护）**：涨停池输出必带真实数据日（该接口对无效日期会静默回旧数据）；北向 `status=3` 或接口回填额度上限一律标 ⚠「未取得」，**禁止当 0**；上游回了原始 HTML 未解析出条目时显式标注，不把 100KB 噪声当结果
- `--arg` 的值猜类型时**纯数字一律留字符串**（600519 是代码不是整数），与 `webtool mcp` 的口径不同
- `screen` 的 text 输出必含**剔除清单与闸门原因** —— 只给通过名单会让调用方以为没被选中的票不存在
- 退出码：0 成功 / 1 数据动作失败 / 2 用法错误

## 通用约定

- `-n` 条数 / `-f` 格式（`md`≡`markdown`、`txt`≡`text`，大小写不敏感）/ `-o` 落盘（按 `-f` 补扩展名）/ `--no-cache` / `--no-proxy`
- 退出码：0 成功 / 2 用法错误（提示走 stderr）
- 缓存 TTL：search 60s / fetch 10s / 跳转解析 10min（`config set cache_ttl.<桶>=<秒>` 覆盖）
- 出网全走浏览器指纹，**走哪条线一次定死**：配置 + 路由表在请求前决定，请求失败就是失败，不做"直连→代理"的隐式切换（否则同一次调用走哪条线取决于它先在哪失败，且"代理失败退直连"会毁掉只允许代理出网的目标）。要临时全直连用 `--no-proxy`，要单点覆盖就加规则表条目
- 报错自带处置建议，照做即可

### 证书校验

三条出网通道（curl_cffi / urllib / requests）共用同一份证书决策，都由 `webtool.core.tls` 出，不各自读环境变量：

```bash
webtool config set ssl_verify on|off                    # 总开关，默认 on
webtool config set ca_bundle /path/to/ca.pem            # 自定义 CA，替代系统 CA
webtool config set verify_hosts czce.com.cn,gtjaqh.com  # 点名豁免，其余域仍严格
webtool config list                                    # 看**实际生效**策略与 CA 来源
```

- **默认严格校验**（fail-closed）。`ca_bundle` 写不存在会当场报错，不会静默降级
- **`verify_hosts` 优先于全局开关**：郑商所 / 国泰君安 / 99期货 这类交易所站点用自签或过期证书，为抓它们关全局校验等于把代理 MITM 也一起放进来了；名单模式只对指定域开口（覆盖子域）
- **证书失败不重试**：抛 `TlsError` 直接上抛，不进换指纹/换代理的降级梯 —— 证书不对就是不对，重试只会把 1 次失败放大成 4 次
- **无 CA 自动降级**：精简环境没装 `ca-certificates` 时严格校验会让所有 HTTPS 失败且报错指不到根因，故自动降级为不校验并在 `config list` 打警告；装上后自动恢复严格校验
- 调用方也可定点覆盖：`Http(verify=False)`（stock 裸调层）、`transport.get(url, verify=...)`

### 规则路由

按**请求目标**分流，不只是按引擎名。同一个引擎里境内直连、境外走代理，或者把某条 CDN 子域单独扔给另一台机器：

```bash
webtool proxy rule add '{"domain":["*.cn"]}' direct        # 境内直连
webtool proxy rule add '{"geosite":["cn"]}' direct         # 同上, 但按域名库判, 不解析 IP
webtool proxy rule add '{"geoip":["CN","HK"]}' direct      # 按 IP 归属地
webtool proxy rule add '{"port":[8080]}' proxy:tokyo        # 命中走命名代理
webtool proxy rule add '{"domain":["ads.tracker.io"]}' block
webtool proxy rule del 2                                    # 删第 3 条 (0 起)
webtool proxy rules                                         # 列规则
webtool proxy rules https://www.baidu.com/x                 # 试算这条请求走哪条线
webtool proxy named tokyo socks5://user@127.0.0.1:1081      # 命名代理 (密码进保险库)
webtool proxy geosite /path/to/geosite.dat                  # 配域名分类库 (1500+ 分类)
webtool proxy geoip /path/to/GeoLite2-Country.mmdb          # 或 geoip.dat
```

命名代理的密码与全局 proxy 走**同一套保险库**：`rules.json` 里只存 `http://user@10.0.0.1:8080`，密文在 `config.json` 的 `proxy_auth`，出网时自动解密。老配置里已有的明文密码会在加载时**自动迁移**（幂等，只做一次）。

**首次运行**（任意一条命令）时若 `~/.webtool/rules.json` 不存在，会自动落一份默认规则：国内常见站点（搜索/门户/财经）与 `opencode.ai`、`exa.ai` 直连，其余跟随全局代理。已有该文件则**永不覆盖**，可直接编辑。

- **顺序即优先级**，第一个命中的生效；`match` 内多个条件 AND，同一条件内多值 OR
- 动作：`direct` / `block`（不发请求）/ `proxy`（全局代理）/ `proxy:<名字>`（命名代理）
- 命名代理用 `webtool proxy named <名字> <代理URL>` 配（`named list` / `named del <名字>`），规则里写 `proxy:<名字>` 引用。**密码同样进保险库**，`rules.json` 只留 `user@host`
- **geosite 不需要 DNS**：判「这域名算不算 CN」按域名分类查库即可，不会因为 CDN 就近解析把 IP 判到别国去。数据支持 MaxMind `.mmdb` 与 v2ray/sing-box 的 `geoip.dat`/`geosite.dat`（[Loyalsoldier/v2ray-rules-dat](https://github.com/Loyalsoldier/v2ray-rules-dat)）；16MB 的库按需解码 + 进程内缓存，只有规则里真引用到的分类才付解码开销
- **判不出来 = 不匹配**：没配库时相关规则跳过并给出提示，而不是当成匹配让流量全部走错方向
- 手写错一条规则只废那一条：非法动作、非对象、缺 `match` 都会被跳过并在 `proxy rules` 里列出原因，不会拖垮整个进程
- 规则表坏掉时退回全局代理而不是纯直连 —— 后者会让必须代理的目标直接连不通
- 命名代理写 `proxies` 段：`{"tokyo":{"url":"socks5://127.0.0.1:1081"}}`

### 代理凭据

`proxy set` 的 URL 里若带密码，密码会被加密存进保险库，配置文件只留用户名，出网前才在内存解密：

```bash
webtool proxy set http://user:pass@127.0.0.1:2080   # 密码自动加密, 配置只留 user@host
webtool proxy setpass <用户名>                      # 终端交互输入, 不回显 (推荐)
webtool proxy setpass <用户名> "<密码>"              # 位置参数: 方便脚本, 但会进 shell history
echo "<密码>" | webtool proxy setpass <用户名>       # 管道: Agent / 脚本
webtool proxy passwd                                # 保险库状态 (密钥来源/用户清单)
webtool proxy delpass <用户名>
```

密码来源按优先级：`getpass` 交互输入（真终端默认，**不回显**）→ stdin 管道 → 位置参数。交互使用应该省略密码参数，否则明文会留在 shell history 和 `ps` 输出里。

- 密文落 `~/.webtool/config.json` 的 `proxy_auth`，`enc:v1:` 前缀标记版本；主密钥在 `~/.webtool/secret.key`（0400），也可用 `WEBTOOL_SECRET_KEY` 环境变量覆盖（容器/CI 场景密钥不进文件）
- **拿不到密钥 = 密文永久解不开**，不做 base64 之类的假加密；保险库里缺某个用户的密码时直接报错指出该跑哪条命令，不会拿空密码去撞一个毫无线索的 407
- 日志与报错里的 `user:pass@` 出口处统一脱敏成 `user:***@`（`webtool proxy rules`、`proxy test` 的输出都不含明文）
- `cryptography` 随包安装（全装形态）；万一环境里被卸掉了，`proxy setpass` 会明确报错而不是降级成明文

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
| `site` | `(query, limit, proxy, timeout, **kw) -> [结果]` | 线路由调用方传入，适配器自己不决定 |
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

## 深入文档

`docs/coding-standard.md`（**编码规范/分层，改代码先读**）· `docs/design.md`（架构）· `docs/feed-sources.md`（feed 源实测）· `docs/custom-sites.md`（site 扩展）· `docs/engine-notes.md`（引擎通道记录）。
