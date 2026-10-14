# webtool 编码规范

本文件是 `src/webtool` 的约定来源。新增代码先读这里；改老代码顺手对齐。

## 1. 分层与分包

物理包结构（自上而下只允许向下依赖，禁止反向）：

```
webtool/
  cli/          L4 应用编排   app / config / plugins / sitesearch / zen / zenproto
                               mcp (通用 MCP 客户端)
  feeds/        L3 业务流程   command / sources / parse / fetch / cards / feedhealth
  stock/        L3 业务流程   engine (业务脚本层) / bridge (数据源层 + 多源编排)
                               command (动作分发 + 渲染)
  radar/        L3 业务流程   routes / rules / instances / official / template
                                           / race / instances_cfg
  pipeline/     L2 合并输出   search / rank / merge / topup / qhint / query_ops
  render/       L2 合并输出   render / hotrender / output
  filters/      L2 结果过滤   blocklist / adfilter        —— 纯规则, 不出网
  net/          L1 采集实现   transport / proxy / captcha / spa / fetch / mcpclient`
  engines/      L1 采集实现   baidu / bing / google / sites / hotsites
                               exa / parallel / firecrawl (MCP 语义引擎)
                               extractors / customsites ...
  core/         L0 基础设施   plugins / config_data / cache / state / http
                                              probe / resilient
                通用工具类     text / urls / jsonfmt
```

包根只留 `__init__.py`——不允许新的包根单文件模块，模块按层归位
（CLI 层 `cli/`、抓取层 `pipeline/`、渲染层 `render/`、网络层 `net/`）。

`radar/` 与 `feeds/` 是"业务包"的样板：一个能力域一个包，`__init__` 只做再导出，
对外仍可 `import webtool.radar`。拆包的切分原则是**按数据源/职责切，不按函数个数切**——
`radar` 切成 routes(官方目录)/rules(规则库)/instances(实例探活)/official(官网兜底)/
template(模板语法)/race(并发) 六块，每块对应一个独立的数据源或算法。

`core/` 内部分两类，别混：

- **底座模块**（plugins/config_data/cache/state/http/probe/resilient）：运行期状态与 I/O 机制
- **通用工具类**（`core.text` / `core.urls` / `core.jsonfmt`）：纯函数，无状态、无业务概念
  - `core.text`：`clean_markup` / `plain` / `unescape` / `truncate` —— HTML 转纯文本，按语义分函数而不是给一个 `mode` 参数
  - `core.urls`：`norm_key`（去重键）/ `host_of` / `registrable` / `section_of` / `same_site` —— 命名即用途，杜绝"归一化"的五种变体
  - `core.jsonfmt`：`read`（坏了退默认）/ `write`（原子替换）/ `fingerprint`（mtime 热更新判失效）

判定规则（写代码前自查）：

- `core/` 不知道任何业务概念：不 import `net / engines / pipeline / render / feeds / cli` 中任何一个
- `engines/` 只被上层调用，实现里不 import `pipeline / feeds / cli`
- 工具函数按"谁依赖更广就住更低"归位：探活、限速这类被多业务用的，住 `net`/`core`，不住业务文件
- 发现某逻辑在 3 处以上重复 → 抽成 `core/` 工具类，不要再复制第四份
- 顶层单文件超过 ~500 行 → 按职责拆成子包（如 `feed.py` → `feeds/`、`radar.py` → `radar/`），别让一个文件既管数据又管出网又管渲染；判据是"有几件事"而不是"多少行"
- 只有一个实现时不抽策略基类/注册表，普通函数就够（多一层间接、多一处配置面）；真有第二种实现时再抽
- 出现 `from webtool.pipeline import ...` 出现在 `engines/` 或 `core/` 下即分层破坏

## 输出格式（`-f`）

规范名只有 3 个，别名 `md`=markdown、`txt`=text，`render/output.py:FORMATS` 是单一事实来源。
不提供 csv：抓来的字段是不可信文本，导出表格要背公式注入的负担。

| 格式 | search | site | rank | feed | fetch | zen | stock | engines/plugins/cache/config |
|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| json | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| text | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| markdown | ✅ | ✅ | ✅ | ✅ | ✅ | ~ | ~ | ✅ |

- `zen`：只有模型清单（`--list-models` / `--list-free`）接 json；对话输出本身是流式
  文本，markdown 无结构可渲染，回落 text
- `stock`：quote/pool/tools/screen 有表格结构，markdown 出表；analyze/screen/risk 的
  未解析 MCP 载荷回落 text（见 stock 段的形状约定）

约定：

- **默认 txt**（`_run` 的 `fmt_default='text'`）：命令的主要消费者是人，直接可读。
  要给程序/Agent 消费时显式 `-f json`
- **非法值直接退出码 2**，不静默回落 text（`cli/app.py::_norm_fmt`）。回落会让 Agent
  拿到人类可读文本却毫无提示，解析阶段才炸
- 数据命令自己按 `args.format` 渲染（`render.render` / `render.hotrender` /
  `net/fetch._emit`）；管理命令内部是 print，由 `cli/adminfmt.py` 把吐出的 JSON 转格式
- 管理命令不给 `-f` 时保持原样直出（不套一层），给了才转
- 需要表格/再加工时用 `-f json` 自行转换，不提供 csv：抓来的字段是不可信文本，
  导出表格必然要回答「要不要防公式注入」，这个长期负担不值当
- **每条结果的字段就是最终形态，没有"精简开关"**。`merge.rerank` 直接产出最终字段：
  `rank/title/url/snippet/weight/engines`。评分中间量 `sem_score`（内部键 `_sem`）
  与 `confirmations`/`quality` 算完即删，不进对外结果。
  **`engines` 恒为数组**（单引擎命中也是 `["sogou"]` 而非 `"sogou"`）—— 形状一致，
  消费方不用写 `isinstance` 分支；数组长度就是交叉验证数。`engine` 单数字段不外泄。

  `text`/`markdown` 同口径：md 不显示 `✕N` 与 `⚠poor`（引擎名列出几个就是几个，
  权重低自然看得出差）。顶层判定信息由 `weight` / `engines` / `dropped_by_floor` 承载。

## 2. 导入

- **一律绝对导入**：`from webtool.core.config_data import load`；禁止 `from .x` / `from ..x`
  （检查：`rg "from \.|from \.\." src/` 应无输出）
- import 顺序：标准库 → 三方 → webtool，组间空行
- 循环依赖靠"函数内延迟 import"打破只允许出现在真实循环场景，且写一行注释说明原因；能靠分层消除的不用这招

## 3. 插件与配置边界

- **逻辑进代码，数据进 JSON，调参进 config**：
  - 抓取/解析逻辑 → 模块函数，经 `plugins.json` 声明成插件（engine/site/hot/extractor/resolver/filter/transformer 七类，签名见 `plugins.SIGNATURES`）
  - **引擎预设**（`plugins.json` 的 `presets` 段）走 `config_data.load`，**不走插件注册表** —— preset
  是纯数据没有 module/params 可执行字段，注册表那套 fn 解析用不上；同文件意味着用户覆盖
  `plugins.json` 时引擎与预设一起生效。优先级 `--engine` > `--preset` > `config.default_engines` >
  清单默认开启项；未知 preset 退 2 不静默回退（静默回退会让用户以为跑了 A 组其实跑了默认组）
 - 新增搜索引擎的门槛：必须**免 key**、**HTTP 直连**、**HTML 里能拿到真实 URL**。
  perplexity / metaso 是 SPA（要浏览器渲染），duckduckgo / brave 直连 DNS 污染且代理
  返回反爬挑战页或 429 —— 这类接不进来，别浪费一轮去试
 - 改引擎解析后验证必须带 `--no-cache`（搜索结果默认缓存 30s，会让你以为改动没生效）  - 运行时调参（开关联动多模块）→ `webtool config set`（白名单在 `cli/config.py`）
- 新增"看起来该配置化"的东西前先问：它是数据吗？改它需要重跑算法基准吗？数据才进 JSON
- 模块级**禁止缓存插件表/配置快照**——一律调用点现取（`_plugin_table(kind)` / `config_data.load`），这是热更新名实相符的前提

## 4. 代码风格

- 行长 ≤ 120；py3 下不写 `# -*- coding: utf-8 -*-`
- 禁止裸 `except:`；捕宽异常必须 `except Exception` 且注释为什么吞
- docstring 首行说清"这是什么"，参数含义复杂才展开；不写空话
- 私有约定：`_` 前缀 = 包内私有；跨模块复用就去掉前缀并挪到低层
- 命名：函数/变量小写下划线；常量 UPPER；模块名单词小写，不加下划线尾巴

## 5. 变更纪律

- 动手前 `rg` 摸清调用点；批量重构先在副本跑通 + `tests/test_smoke.py` 过了再落主仓
- `tests/test_smoke.py` 是回归底线：import 全量 + 插件体检 + 配置装载。改完必须跑，全 PASS 才提交
- 提交信息格式：`<type>: <一句话> [空行] [要点列表]`，type ∈ refactor/fix/feat/docs

## 6. 已知取舍（防止"好心办坏事"）

- `Registry.items()` 返回 dict——遍历要 `.items().items()`；直接 `for k, v in reg.items()` 会把 key 字符串解包报错（smoke 有契约测试锁死）
- 探活统一走 `core.probe.proxy_ok`；`pipeline/rank.py` 的 `_proxy_ok` 是它上面加了进程内缓存的薄包装
- 引擎/端点都不自报线路：没有 `engine_proxy` 覆盖，没有 `proxy_hint`，没有 `_proxy_alive`。
  一条请求走直连还是代理，只由规则表（`netx`）判一次
- **MCP 端点既可以只是 `mcp` 的调用目标，也可以直接充当搜索引擎或 fetch 兜底通道**。
  `engines/parallel.py` 与 `engines/firecrawl.py` 是样板：`engines/exa.py`（三者同源）
  端点声明（url / verbs / api_key_env）全部读 `data/mcp.json`，与 `webtool mcp` 共用同一份数据，
  engines 层不 import `cli/`（L1 不得反向依赖 L4），只 import `net/mcpclient` 出网 + `core/config_data` 读声明。
  要让某个 MCP 端点进 `search` 引擎池，实现 `search(query, max_results, proxy, timeout, market, **_)` 返回
  `[{rank, title, url, snippet}]`，再在 `data/plugins.json` 的 `engine` 段登记 `module` + `enabled_by_default`。
  端点侧的 `verbs` 映射不写死在代码里 —— 新端点声明 `verbs` 即可复用。要支持新协议的端点才写新的 `cli/<name>.py`，别把协议塞进引擎里
- **同一个 MCP 端点的 `web_fetch` 返回形状按端点不同，必须在 `net/fetch.py::_reader_text` 分派**，
  别写死一种：firecrawl 回 `{"markdown": ...}`、parallel 回 `{"results":[{excerpts:[...]}]}`、
  exa 回已拼好的 markdown 纯文本。新增通道时**先实测形状**再写分支，并在该通道的 docstring 注明是否已用真 key 验证过
  （无 key 的端点只能按公开文档推定 —— 这种代码要明说"未实测"，别让人误以为已验证）。
  入参形状同样按端点不同，见 `_reader_arg`
- **端点表 `data/mcp.json` 不声明线路**，所有端点统一跟随 `proxy` 配置 + 路由表
  （`auto` → 规则表 → 全局代理/直连）。免 key 配额按出口 IP 计，走全局代理等于蹭别人
  的配额池，要固定某端点直连就加一条针对它域名的规则：
  `webtool proxy rule add '{"domain":["exa.ai"]}' direct`
- **`plugins.json` 里没有任何线路字段**：`site.*.proxy`、`engine.*.params.proxy_hint` 都已删除。
  引擎和内置站点一律把线路交给规则表。自定义站点 `~/.webtool/sites/*.json` 的 `proxy` 是
  **用户配置**，继续有效（`direct` / `proxy` / `auto`）
- **只在"只读用户目录那一份、且用户要直接编辑"的文件上做首次落地**：`core/bootstrap.ensure_user_files()`
  在 CLI 首次启动时把包内 `data/rules.json` 复制到 `~/.webtool/rules.json`（已存在则不动）。
  走"包内默认 + 用户覆盖"两层合并的 `config.json`/`plugins.json` 之类**不落地** —— 凭空生成
  一份会盖住以后升级带来的新默认值。pip 没有可靠的 post-install 钩子，所以入口只能是首次启动
- **线路只由配置决定，不做隐式切换**（`netx.resolve_proxy` 是唯一归一点）。"先直连、失败
  再代理"这类回退会让同一次请求走哪条线取决于它先在哪失败，"代理失败退直连"更会毁掉只允许
  代理出网的目标。写通道别加 `allow_fallback` 参数，也别在适配器里写死 `proxy=None` ——
  那等于无视管线传入的代理
- **环境变量不是线路决策源**。`http_proxy`/`https_proxy` 在容器里很常见，各库默认都会读它
  （urllib 的默认 `ProxyHandler`、requests 与 curl_cffi 的 `trust_env=True`）—— 于是规则表
  判定"直连"的主机被悄悄送去代理，用户改配置文件改不动。已经在三处堵死：`core.http.build_opener`
  直连时也传一个空 `ProxyHandler`（它顶掉默认那个，自身没有 `*_open` 方法，装代理和读环境变量
  都不发生）、`transport._new_session` 与 `netx._get_cffi` 传 `trust_env=False`、数据源层
  requests/curl_cffi 会话 `trust_env=False`。新写通道照此办理
- **不在代码里写死线路名单**（push2 直连名单、`STOCK_DIRECT_DOMAINS` / `STOCK_PROXY` 这类
  环境变量兜底）：写在代码里的判断发生在问规则表之前，会把显式传入的代理静默吃掉，且与规则表
  构成同一件事的第二个决策源。要固定某站走直连就写 `~/.webtool/rules.json` —— 那份文件
  用户看得见也改得动
- **规则命中由 `rules.json` 顶层的 `priority` 决定**（默认 `direct`）：`direct` 时任一匹配的
  direct 规则生效（block 优先于它），不受前面更宽的 proxy 规则阻挡；`order` 表示按文件顺序
  first-match-wins
- **管理命令的退出码与输出是两件事**：rc!=0 时 `cli.app._run` 照样把已打出的报告发出去
  （`upgrade --check` 有新版就退 1，报告照给），退出码只表达"有没有可用结果"。要机器读就配
  `-f json`；要"失败也带信息"就直接打印或走 stderr
- `engines/sites.py` 的 `_mk/_fetch/_headers` 被 6 个模块跨文件复用（customsites / sitesearch /
  feeds.fetch / hotsites / moresites / moresites2 / oversites），暂留私有名；
  真要复用得按规范去掉 `_` 并下沉到 `core` 或 `engines/base.py`
- **`stock/` 是桥接层，不实现业务逻辑，且全链路纯进程内**。三侧口径都归各自维护方：
  - **第四侧 `eco.py`** 桥生态库：**akshare 1093 / tushare 122 / baostock 29 / efinance 55**
  （返回 DataFrame），覆盖数据源层没有的领域（宏观、另类数据、期货、基金、外汇）。
  `webtool stock eco --lib <库> --method <接口>` 调，默认给 shape + 列名 + 前 5 行，
  `--full` 才给全量 —— akshare 不少接口返回几千行（`stock_zh_a_spot_em` 全市场快照
  5923×23，约 76 秒），直接印会刷屏。
  `eco-search` 按中英文关键词搜（中文能命中是因为 akshare 不少接口文档首行写了中文）
- **生态库的数据列里常有 `datetime.date` / numpy 标量**，不是 JSON 原生类型。
  渲染层一律走 `command.py::_j` 兜底序列化 —— 直接 `json.dumps` 会 TypeError
  **崩在渲染层**，而那时数据其实已经取到了，白跑一次网络请求
- **第三侧 `rawapi.py`** 桥 `bridge/sources/`（随仓内置）的
    **156 个低阶方法**（`webtool stock data list api` 出清单），按数据源分包：
    ths/sina/xueqiu/em/gtimg/tencent/cninfo/sse/csindex/ef/np。编排层把其中一部分
    聚合成 24 个动作，其余（股东研究/盈利预测/研报日历/早盘晚报/板块多维排行/分钟线/
    产业链分类 等）从 `webtool stock api <方法>` 直接调
  - `rawapi.call` **按签名校验参数**：多传参数直接报错而不是吞掉 —— 静默丢弃参数
    等于让调用方以为生效了，实际跑的是默认值
- **全部依赖都在 `webtool.stock` 包内**（`bridge/sources/` 数据源、
  `bridge/orchestrate.py` 编排层、`engine/` 业务脚本层），**静态 import 接入**：
  `from webtool.stock.bridge.sources import APIClient` /
  `webtool.stock.engine.<name>`。装包即用，无需额外安装
  - 目录名必须是合法标识符（带连字符的名字当不了包名），业务脚本层因此叫 `engine/`。
    文档与自测脚本不进包：包内只放能跑的业务代码，副本留外面那份
  - **engine 不出网**：取数一律经 `bridge/sources/`（腾讯行情、东财涨停池的端点在
    `sources/sina.py` 的 `gtimg_quote_flat` 与 `sources/em.py` 的 `em_zt_pool`）。engine
    自己起 urllib 出口不放行 —— 少一个出网出口就少一处能绕过规则表的地方
  - **不要用 `sys.path.insert` + `importlib` 接内部依赖**。sys.path 是全局可变状态，
    谁先 import 谁改变后续所有 import 的结果：两个目录各插一次，同名模块会被加载成两份，
    各带一套 `lru_cache`(token/session)，数据状态互不相通 —— 包内 import 从结构上消除
    这个歧义
    （测试断言：导入依赖全程 `sys.path` 不变，且顶层 `'api_client'` 从未进
    `sys.modules`）
  - **不要留外部覆盖路径**（`STOCK_API_HOME` / `STOCK_MASTER_HOME` / `STOCK_MCP_HOME`
    这类从仓外目录加载的环境变量）：覆盖路径加载出的模块与包内那份是**两个模块对象**，
    同一个进程里两份
    `APIClient` 各带一份 token/session 缓存，cookie 互相看不见，而"我配的到底是
    哪份"还取决于谁先 import。**要换版本就改包内那份**
  - `webtool stock health` 的 `orchestrator` 段 `found` 恒为真 —— 只有一种状态可报，
    所以它同时是一个"没被改回去"的回归哨兵
  - 包化后 `engine/` 是真包（靠 `__init__.py`），由 `packages.find` 自动收进 wheel；
    它没有非代码资源，`package-data` 不必列它。但 `stock/data/**` 仍要显式列：键是**包名**、值是**相对包根**的路径，
    `data/**` 够不到 `stock/` 下的子目录。这个坑只在查 wheel 内容时才暴露，
    源码树里跑永远是好的
  **全程不起子进程、不经协议**：
  - 服务端 `TOOLS` 注册表每项自带 `handler` 函数 —— `bridge/srv.py` 直接调 handler，
    拿到的是工具自己的 dict，**没有 content 信封的序列化往返**（`_call_tool` 那条路
    会把结果 dumps 成字符串再塞进 MCP content 再被解析回来，多一轮序列化 + 解析）
  - `engine/clients.mcp()` 是**进程内直调** `bridge/srv.py`（→ `orchestrate.py`），
    不起子进程、不套信封；`engine/clients.web_search()` 仍起 `webtool search`
    子进程（要的是搜索管线与渲染，不是一条裸请求）
  - engine 缺失只让 stock 的脚本层动作退 2，不影响 webtool 其余命令（所以
    `bridge/engine.py` 的 mod() 必须在函数内 import，不能放模块级）
- **失败语义要与原 MCP 路径一致**：handler 抛异常（如 `normalize` 失败）或返回
  `ok=False` → 抛 `SrvError`。engine 侧包装函数捕获后仍拿到 `{"ok":False,"err":...}`
  —— 直调 handler 若不捕获，单只票参数非法会整条命令崩掉
- **`web_search` 的进程内实现走 `cli.app.main(argv)`**，不直接调 `pipeline.search.do_search`
  —— 后者要 29 个字段的 args 对象，自己拼等于复制一份 CLI 契约，迟早漂移
- **别拿 `net/mcpclient.py` 去调 stock**，那是给通用 HTTP MCP server 用的，与这条
  进程内直调通道互不相通
- **工具清单的单一事实来源是服务端的 `TOOLS` 注册表**，不是本地表。本地 `TOOLS` 只是
  服务端 import 不了时的兜底；`do_tools`/`tool_names` 都优先读服务端，新增减工具不用改 webtool
- **原样透传类动作**（`report` / `diagram` / `excel`）不套 json/表格渲染 —— 它们
  产出的是成稿 markdown、mermaid 源码、落盘确认，本来就是给人直接看的东西，再包一层
  结构化输出反而破坏可读性。这类走 `command.py::_passthrough`
- **`sentiment` 的分数必须带符号印出**（`+12` 而非 `12`）—— 消息面的关键信息是方向，
  印绝对值会被读成"强利好"
- **`chain` 图的上游/中游/下游分别对应 `--driver` / `--mid` / `--catalyst`**，
  不复用 `--risk`：产业链图没有"风险"概念，拿 risks 当中游是语义错配
- **`screen` 三个池的返回结构不同**：只有 short 池带 `passed_count`/`failed_count`/
  `min_score_threshold`/`industry_dispersion` 和 `position_tag`，mid/long 池只给
  `passed`/`failed` 列表且 `industry` 是 `[{ind_code,ind_name,ind_type}]` 数组。
  计数走 `_screen_counts`（有计数字段优先，否则用列表长度），行业列走 `_industry_cell`
  （数组只取 `ind_type==1` 的一级行业名）—— 直接读 `passed_count` 会渲染成"通过 None"
- **`analyze` 的 text 走 `_text_analyze`**：结论先行（评分/信号/三档入场/止损），
  默认吐裸 JSON 会把"能不能买、什么价买"埋在 20 行里；程序读字段用 `-f json`
- `announcement` 动作曾起 1 个 `curl` 子进程（`np_notice_ann` 东财公告接口），
  已消除：改为 `self._std.get()` 走统一会话。理由与验证见 `bridge/ROUTING.md`
- **stock 动作的载荷形状按动作不同，`stock/command.py` 靠 `_items_of`（广度优先下钻
  `items/list/rows`）统一认领**：news 是 `data.items`，announcement 是 `data.data.list`，
  capital_flow north 是 `data.data.data.{hk2sh,...}`（无列表）。**认不出就标注不猜** ——
  同花顺 stockpage 是 SPA，上游站点解析不出列表会回 100KB 原始 HTML，印出来等于把噪声
  当结果
- **stock 的 `--arg` 类型推断与 `cli/mcp.py` 有意不同**：纯数字一律留字符串（600519 是
  A股代码，整数会被动作参数校验拒）。改这段前先确认不是在给非代码字段传数字
- **`stock/command.py::_render` 对未解析载荷只在 text/markdown 标 stderr 警告**，
  json 保持原样 —— 程序消费方可能自己要那份 html，不该由渲染层替它决定丢弃
- 打包数据在包根 `src/webtool/data/`（不在 `core/` 下），`core.config_data.DATA_DIR`
  指向它；`pyproject` 的 `package-data` 按此配

## 7. 注释与文档纪律

- 注释只写两类：**为什么这么做**（约束、坑、不直观的取舍）与**外部协议事实**（上游字段形状、必须带的头、限速）。代码本身在做什么，不写
- 不写沿革：不出现「以前 / 原本 / 曾 / 已撤除 / 不再 / 改成 / 替换成」，也不写 bug 复盘与实测过程 —— 那些属于 git log 与提交信息
- 不写自辩：不铺开论证「为什么不选另一种做法」；一句结论，完整理由放本文件的取舍清单，代码里只留指针
- 不写没验证过的事实。上游形状、限速、配额必须来自实际调用或官方文档；推定的一律标注「未实测」
- 会变的数字（接口数、方法数、限额）要么从常量/数据文件取，要么别写具体值，改成指向查询命令
- 分区只用一行短标签（如 `# 语义相关性`），不画横线装饰；纯装饰的横线行直接删
- 空话注释一律删：`# 统一入口`、`# 方便调用`、复述下一行代码的注释
- docstring 首行一句话说清「这是什么」，参数复杂才展开；不留空话（如"统一入口"「方便调用」）
- README / docs 同标准：只写当前行为与用法，改完核对与代码一致（命令名、选项、数字）
