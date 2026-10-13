# webtool 编码规范

本文件是 `src/webtool` 的约定来源。新增代码先读这里；改老代码顺手对齐。

## 1. 分层与分包

物理包结构（自上而下只允许向下依赖，禁止反向）：

```
webtool/
  cli/          L4 应用编排   app / config / plugins / sitesearch / zen / zenproto
                               mcp (通用 MCP 客户端)
  feeds/        L3 业务流程   command / sources / parse / fetch / cards / feedhealth
  stock/        L3 业务流程   master (桥 stock-master skill) / mcp (桥 stock MCP)
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

包根只留 `__init__.py`——2026-10-12 起不再允许新的包根单文件模块（原
`zen/zenproto/sitesearch/fetch/blocklist/adfilter/query_ops/extractors/customsites/feedhealth`
已按层归位）。

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
（曾加过 csv，因 CSV 公式注入风险与字段转义复杂度撤除——抓来的字段是不可信文本，
导出表格必然引出「是否要防注入」的长期负担，而实际用途以 json 为主。）

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
  要给程序/Agent 消费时显式 `-f json`。原先默认 json（fetch 除外）
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

  曾实现过 `merge(slim=True)` + 输出前再剥一层的设计，已撤除 —— 那等于让数据先
  长出多余字段再当场删掉，多余的参数和两次遍历都是纯负担，且派生 bug（剥字段
  与诊断逻辑的执行顺序耦合）。

  `text`/`markdown` 同口径：md 不再显示 `✕N` 与 `⚠poor`（引擎名列出几个就是几个，
  权重低自然看得出差）。顶层 `quality_hint` 已随 7b2feca 一并移除（判定信息改由
  `weight` / `engines` / `dropped_by_floor` 承载），文档里别再提。

## 2. 导入

- **一律绝对导入**：`from webtool.core.config_data import load`；禁止 `from .x` / `from ..x`
  （历史 116 处已于 2026-10 全量迁移，rg 检查：`rg "from \.|from \.\." src/` 应无输出）
- import 顺序：标准库 → 三方 → webtool，组间空行
- 循环依赖靠"函数内延迟 import"打破只允许出现在真实循环场景，且写一行注释说明原因；能靠分层消除的不用这招

## 3. 插件与配置边界

- **逻辑进代码，数据进 JSON，调参进 config**：
  - 抓取/解析逻辑 → 模块函数，经 `plugins.json` 声明成插件（engine/site/hot/extractor/resolver/filter/transformer 七类，签名见 `plugins.SIGNATURES`）
  - **引擎预设**（`plugins.json` 的 `presets` 段）走 `config_data.load`，**不走插件注册表** —— preset
  是纯数据没有 module/params 可执行字段，注册表那套 fn 解析用不上；同文件意味着用户覆盖
  `plugins.json` 时引擎与预设一起生效。优先级 `--engine` > `--preset` > `config.default_engines` >
  清单默认开启项；未知 preset 退 2 不静默回退（静默回退会让用户以为跑了 A 组其实跑了默认组）
 - 新增搜索引擎的门槛：必须**免 key**、**HTTP 直连**、**HTML 里能拿到真实 URL**。实测 perplexity /
  metaso 是 SPA（要浏览器渲染）、duckduckgo 直连 DNS 污染且代理返回反爬挑战页、brave 直连 DNS 污染
  且代理 429 —— 这类都接不进来，别浪费一轮去试
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
- `pipeline/search.py` 的 `proxy_hint/_proxy_alive` 同理是兼容再导出，实现在 `net/transport.py`
- **MCP 端点既可以只是 `mcp` 的调用目标，也可以直接充当搜索引擎或 fetch 兜底通道**。
  `engines/parallel.py` 与 `engines/firecrawl.py` 是样板：`engines/exa.py`（三者同源）
  端点声明（url / verbs / proxy / api_key_env）全部读 `data/mcp.json`，与 `webtool mcp` 共用同一份数据，
  engines 层不 import `cli/`（L1 不得反向依赖 L4），只 import `net/mcpclient` 出网 + `core/config_data` 读声明。
  要让某个 MCP 端点进 `search` 引擎池，实现 `search(query, max_results, proxy, timeout, market, **_)` 返回
  `[{rank, title, url, snippet}]`，再在 `data/plugins.json` 的 `engine` 段登记 `module` + `enabled_by_default`。
  端点侧的 `verbs` 映射不写死在代码里 —— 新端点声明 `verbs` 即可复用。要支持新协议的端点才写新的 `cli/<name>.py`，别把协议塞进引擎里
- **同一个 MCP 端点的 `web_fetch` 返回形状按端点不同，必须在 `net/fetch.py::_reader_text` 分派**，
  别写死一种：firecrawl 回 `{"markdown": ...}`、parallel 回 `{"results":[{excerpts:[...]}]}`、
  exa 回已拼好的 markdown 纯文本。新增通道时**先实测形状**再写分支，并在该通道的 docstring 注明是否已用真 key 验证过
  （无 key 的端点只能按公开文档推定 —— 这种代码要明说"未实测"，别让人误以为已验证）。
  入参形状同样按端点不同，见 `_reader_arg`
- **MCP 端点的代理策略**由 `data/mcp.json` 声明，缺省跟随全局配置（同其余命令），
  `"proxy":"direct"` 强制直连。exa 声明了 `direct`：免 key 配额按出口 IP 计，走全局代理
  等于用别人的配额池（实测同一命令带代理必 429、直连稳定通过）。这是**端点特性不是
  MCP 通用约定** —— 别把整个 MCP 层都改成默认直连，否则被墙的端点接不上。
  命令侧解析在 `cli/mcp.py::_proxy_for`；引擎侧（`engines/exa.py`）因拿不到 `args.no_proxy`，
  由自己按端点声明强制 `proxy=None`，两处逻辑同源但各按自己的调用形状落地
- **管理命令返回 rc!=0 时，`cli.app._run` 会丢弃 stdout 缓冲**（只保留退出码）。`plugins check` 失败即看不到内容，是既有问题。`cli/mcp.py` 因此把失败输出走 stderr —— 新写管理命令若有"失败也要给信息"的需求，同样走 stderr
- `engines/sites.py` 的 `_mk/_fetch/_headers` 被 6 个模块跨文件复用（customsites / sitesearch /
  feeds.fetch / hotsites / moresites / moresites2 / oversites），暂留私有名；
  真要复用得按规范去掉 `_` 并下沉到 `core` 或 `engines/base.py`
- **`stock/` 是桥接层，不实现业务逻辑，且全链路纯进程内**。两侧口径都归各自维护方：
  stock-master 在 `/var/minis/skills/stock-master`（`STOCK_MASTER_HOME` 可覆盖），
  stock 数据服务端在 `/var/minis/mcp-servers/stock_mcp_server.py`（`STOCK_MCP_HOME`
  可覆盖）。**全程不起子进程、不经 MCP 协议**：
  - 服务端 `TOOLS` 注册表每项自带 `handler` 函数 —— `stock/srv.py` 直接调 handler，
    拿到的是工具自己的 dict，**没有 content 信封的序列化往返**（`_call_tool` 那条路
    会把结果 dumps 成字符串再塞进 MCP content 再被解析回来，多一轮序列化 + 解析）
  - stock-master 自己的两个子进程出口（`clients.mcp()` 起 `minis-mcp-cli`、
    `clients.web_search()` 起 `webtool search`）在 `stock/master.py::_patch_inproc`
    里被**运行时注入**成进程内实现，产物形状不变
  - 注入只在 webtool 进程内生效，不改 skill 文件 —— skill 有自己的维护流程，改动应由
    skill 侧提；webtool 只做运行时覆盖
  - skill 缺失只让 stock 动作退 2，不影响 webtool 其余命令（所以桥接必须在函数内
    import，不能放模块级）
- **失败语义要与原 MCP 路径一致**：handler 抛异常（如 `normalize` 失败）或返回
  `ok=False` → 抛 `SrvError`。skill 侧包装函数捕获后仍拿到 `{"ok":False,"err":...}`
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
- 已知残留：`announcement` 动作会起 1 个 `curl` 子进程，来自服务端依赖
  `/var/minis/shared/股票/API调研/api_client.py::np_notice_ann`（东财公告接口）——
  是数据层自己的实现，不在 webtool 桥接范围内
- **stock MCP 的载荷形状按工具不同，`stock/command.py` 靠 `_items_of`（广度优先下钻
  `items/list/rows`）统一认领**：news 是 `data.items`，announcement 是 `data.data.list`，
  capital_flow north 是 `data.data.data.{hk2sh,...}`（无列表）。**认不出就标注不猜** ——
  同花顺 stockpage 是 SPA，MCP 解析不出列表会回 100KB 原始 HTML，印出来等于把噪声
  当结果
- **stock 的 `--arg` 类型推断与 `cli/mcp.py` 有意不同**：纯数字一律留字符串（600519 是
  A股代码，整数会被 MCP schema 拒）。改这段前先确认不是在给非代码字段传数字
- **`stock/command.py::_render` 对未解析载荷只在 text/markdown 标 stderr 警告**，
  json 保持原样 —— 程序消费方可能自己要那份 html，不该由渲染层替它决定丢弃
- 打包数据在包根 `src/webtool/data/`（不在 `core/` 下），`core.config_data.DATA_DIR`
  指向它；`pyproject` 的 `package-data` 按此配
