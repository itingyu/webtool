# webtool 编码规范

本文件是 `src/webtool` 的约定来源。新增代码先读这里；改老代码顺手对齐。

## 1. 分层与分包

物理包结构（自上而下只允许向下依赖，禁止反向）：

```
webtool/
  cli/          L4 应用编排   app(仅 app/callback/main) / _ctx(共享) /
                               commands/{data,maintenance,stock} / config / plugins /
                               sitesearch / zenproto / zen/
                               mcp (通用 MCP 客户端)
                               zen/  (__init__ 入口 + client + render)
  feeds/        L3 业务流程   command / sources / parse / fetch / cards / feedhealth
  stock/        L3 业务流程   engine (业务脚本层) / bridge (数据源层 + 多源编排)
                               command/ (__init__ 入口 + _registry 动作表
                               + _actions* 动作 + _textfmt/_render 视图 + _common)
  radar/        L3 业务流程   routes / rules / instances / official / template
                                           / race / instances_cfg
  pipeline/     L2 合并输出   search / rank / merge / topup / qhint / query_ops
  render/       L2 合并输出   render / hotrender / output
  filters/      L2 结果过滤   blocklist / adfilter        —— 纯规则, 不出网
  net/          L1 采集实现   transport / tls / http / connectivity / proxy /
                               intercept / captcha / spa / fetch / download /
                               mcpclient / dns / netx(门面) / rules
  engines/      L1 采集实现   baidu / bing / google / sites / hotsites
                               exa / parallel / firecrawl (MCP 语义引擎)
                               extractors / customsites ...
  core/         L0 基础设施   plugins / config_data / cache / state
                                              resilient / logging / stdin
                通用工具类     text / urls / jsonfmt
```

数据源子包 (`sources/em/`) 用 mixin 组合而非继承树：方法只用 `self`，
族间调用是属性访问不是 import，所以拆分不引入环；对外仍是同一个类名。

包根只留 `__init__.py`——不允许新的包根单文件模块，模块按层归位
（CLI 层 `cli/`、抓取层 `pipeline/`、渲染层 `render/`、网络层 `net/`）。

`radar/` 与 `feeds/` 是"业务包"的样板：一个能力域一个包，`__init__` 只做再导出，
对外仍可 `import webtool.radar`。拆包的切分原则是**按数据源/职责切，不按函数个数切**——
`radar` 切成 routes(官方目录)/rules(规则库)/instances(实例探活)/official(官网兜底)/
template(模板语法)/race(并发) 六块，每块对应一个独立的数据源或算法。

**拆单文件为包时，`X.py` → `X/` 的再导出要留神 monkeypatch 目标迁移**：测试（含
`test_smoke`/`test_tls`/`test_config_migrate`）惯用 `改模块全局变量` 来隔离，
例如 `proxy.CONFIG_PATH = 临时路径`。单文件时"模块全局"就是函数真正读的那个变量；
拆成包后 `proxy.CONFIG_PATH` 只是 `__init__` 的副本，函数读的是 `proxy/store.py`
里的那个 —— 补丁打不到，测试会静默读写**真实配置**。规矩：**补丁打在定义处**
（`proxy.store.CONFIG_PATH`），并让消费者从定义处 import（如 `tls` 从
`proxy.store` 取 `CONFIG_PATH`），别从包根取会变的全局。

### net/ 内部分层（按实际业务归位，OSI 仅作依赖方向参照）

**分层是指导思想，不是目录模板**：OSI 用来回答"这一层该不该依赖那一层"（依赖只许向下），
不按 L1~L7 建目录。现有 `proxy / rules / transport / intercept / tls / netx` 切分
已符合业务逻辑，保持并按需微调：

```
net/
├── connectivity   连通性探测：TCP 握手探活 / 可达性缓存（net.connectivity 已并入）
├── dns            域名 → IP：系统 resolver + 进程内缓存（负缓存也缓存）
├── proxy/         代理配置子包: store(config/原语/迁移) auth geo rules_cli pool cli
├── tls.py         证书校验、CA、verify_hosts、TLS 策略唯一决策点（原 net/tls 归位）
├── http.py        urllib 兜底通道（transport 的备胎本体，非第二条策略）
├── stream.py      L7 流式原语：SSE 逐行 iter_sse() + 增量解压 + WS 帧编解码（出网仍走 transport）
├── transport.py   会话编排（DNS+代理+TLS+HTTP 组装，工厂产出）
├── fetch/download L7 通道：HTTP、流式（SSE/WebSocket 按需再加）
├── intercept.py   拦截与绕过（captcha/spa 并入，不动）
├── rules/         规则引擎子包: spec(契约/kind 注册) builtin matchers geodb router tidy migrate loader
└── netx.py        唯一门面
```

归位原则：**一块职责一个文件，文件承载两种职责才拆**（如 transport 混了 DNS 就拆出去）；
现有层间无环的不动。判定规则：子包之间不互相 import（组装只发生在 transport.py）；
ip/ping 等连通性探测归 `net.connectivity`，不单开网络层，ICMP 受限环境自动降级 tcp 探测。

**归位已完成（P1）**：`tls` / `http` / `connectivity` 三个模块 2026-10 从 `core/` 迁入 `net/`，
调用点全量改为 `webtool.net.*`（不留 `core/` 薄壳 —— 那会让 `core → net` 反向依赖，
与本节"core 不 import 上层"冲突）。分层守卫 `tests/test_layering.py` 已修复：此前
`top_module` 返回 `webtool.net` 而禁用集写的是 `net`，两边永不相交，断言全部空转（形同虚设）。

### 数据流向分层

数据源接口(sources/) → DAO(bridge/ filters/ data) → 控制(engines/ stock/engine/ pipeline/ feeds/command) → 视图(render/) → 模块(cli/)。
依赖只许向下：`cli → 控制 → DAO → sources`；sources 不知道给谁用（只有 DataPacket 契约），render 是纯函数。

`core/` 内部分两类，别混：

- **底座模块**（plugins/config_data/cache/state/resilient）：运行期状态与 I/O 机制
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
  `pipeline/fetch._emit`）；管理命令内部是 print，由 `cli/adminfmt.py` 把吐出的 JSON 转格式
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

## 2.5 规则引擎：特殊走规则，否则走通用

任何环节的特殊行为都必须以规则表达，**禁止在通用代码里写 `if domain == 'xxx'`**。
规则模型全仓统一（`net/rules/spec.py` / RuleSpec 注册表），按环节分 kind，格式一致：

```jsonc
// rules.json 各 kind 统一 {kind, match, 动作字段}
{"kind": "http",  "match": {"domain": "xueqiu.com"}, "fingerprint": "chrome131", "timeout": 15}
{"kind": "retry", "match": {"domain": "sina.com.cn"}, "retries": 5, "backoff": "exp"}
{"kind": "breaker", "match": {"domain": "*"}, "fail_threshold": 5, "cool_seconds": 300}
```

- 粒度随对象：proxy/dns/HTTP 指纹/熔断按**域名**；timeout/retry 按域名+路径；渲染按输出格式
- 匹配：文件顺序 first-match-wins（`priority` 键已废弃）；**无命中走通用默认值**，通用默认值集中在该层模块顶部常量，不散落调用点
- 新环节要特殊化时先问：默认路径能不能覆盖？能就不加 kind；加 kind 必须同时给通用默认 + 文档一条
- **kind 元数据注册制**：新环节在自己的模块 `register(RuleSpec(kind, fields, match_keys, doc))` 即可，**不改 `net/rules/` 包**。内置三 kind 见 `net/rules/builtin.py`；`rules.specs()` 可枚举全量 kind
- **kind 必须有消费方才立**：`http`/`retry`/`breaker` 已接线（transport/resilient）；
  `params_for()` 对任意 kind 都能查，但没有消费方的 kind 属预留位，不写进文档当能力
- Router 会校验 kind 条目的 `match` 键拼写，把"`domian` 写错 → 静默死规则"报进 warnings

## 2.6 日志与 --debug

- 每模块 `logger = logging.getLogger(__name__)`；打印给人看的用 print，定位问题用的**必须**走 logger
- `--debug/-d` 是 app.py 全局回调注入的通用参数，全命令零改动生效；级别 DEBUG(灰)/INFO(绿)/WARN(黄)/ERROR(红)，非 tty / NO_COLOR 自动去色
- 叠加：`-d` 放开本仓 DEBUG；`-dd` 连三方库（urllib3/curl_cffi…）也放开。`WEBTOOL_DEBUG=1` 等效 `-d`
- `--log-file PATH`（`WEBTOOL_LOG_FILE` 等效）把**全量 DEBUG** 写进文件，stderr 可见度不受影响 ——
  跑批/复现问题时抓日志用，不用把终端刷满。文件 handler 存在时 logger 本体放 DEBUG，stderr handler 单独卡级别
- 耗时埋点用 `core.logging.timed(logger, label, **fields)`（如 transport 的 `HTTP GET`），异常也照记（finally）
- 必埋点：请求 URL、规则命中结果、重试次数、熔断状态、缓存命中、耗时
- 捕宽异常处必须 `logger.debug(..., exc_info=True)`——`except Exception: pass` 是排障黑洞，禁止
- `--debug` 时被吞的异常打印完整 traceback

## 2.7 stdin / 管道

- 输入一律经 `core/stdin.py:read_input(arg)`：arg 有值用 arg；arg 为 `-` 或无参且 stdin 非 tty 时读 stdin
- 文本命令（search/fetch/site/stock）支持 `x | webtool <cmd> -` 范式，写进 SKILL.md
- **不是所有命令都该隐式读 stdin**：`rank`/`feed` 无参 = "列清单+用法"，是**有语义**的默认，
  隐式吞 stdin 会把"想列清单"变成"读空管道"。这类命令只在显式给 `-` 时才读
- stdin 只承诺文本；输出侧 `-o -` 已有，保持

## 2.8 设计模式使用门槛

- **适配器**：数据源实现 `SourceBase` 契约（请求→解析→校验→DataPacket），模板方法上提公共流程
- **工厂**：Source/Engine/Transport 实例化一律走注册表工厂，禁止调用点 if-else 链
- **策略**：解析/渲染/传输可替换行为用策略对象；只有一个实现时**不抽**（普通函数就够），出现第二个实现再抽
- 门面：上层只 import `netx`；观察者(轻)：日志/进度用 logger 事件，不加回调参数

## 2.9 弹性层：并发 / 重试 / 熔断 / 恢复

统一走 `core/resilient.py`，业务模块不自己写线程池：

- 并发：`parallel_map(tasks, policy)`，policy 来自规则（max_workers）；共享状态只在主线程写（见"多源抓取"节）
- 重试：指数退避 + jitter；**默认不重试**（`retries=0`），要开则 `config set retries N` 或按站写 `kind:retry` 规则；只重试幂等请求
- 熔断：按域名失败计数，打开时直接短路并打 debug 日志；状态持久化到 state。**默认关闭**（`breaker_cool=0`），要开则 `config set breaker_cool N`（配合 `breaker_fails`）
- 取值优先级：`kind` 规则 > `config.json` > 模块常量（`DEFAULT_RETRIES` / `DEFAULT_COOL_SECONDS` = 0）
- 恢复：批任务（rank/feed/screen）写 checkpoint，重跑跳过已完成条目
- 反爬降级梯：被拦后换指纹/换头/按插件绕法重试；**默认 0 步**（`ladder_steps=0`，首次被拦即报），要开则 `config set ladder_steps N`
- 优雅关闭：并发一律走 `core.resilient.thread_pool()`（daemon 线程池 + 打断即取消未开始任务、不等待在飞请求）；CLI 入口装 `core.shutdown.install()` —— 一次 Ctrl-C 协作退出（rc 130），再按一次强制退出。**别再用裸 `ThreadPoolExecutor`**：它退出时 `shutdown(wait=True)` 会 join 在飞请求，让 Ctrl-C"停不下来"；也别给这个助手起名 `pool`（业务里 `pool=[]` 会把导入遮成局部变量 → UnboundLocalError）

## 2.10 交付自检（每个 PR 过一遍）

- [ ] 新文件 ≤ 500 行，目录名即分层名
- [ ] 分层 import 方向未破坏（`rg "from webtool.pipeline" src/engines src/core src/net` 应无输出）
- [ ] 复制超过 3 处的逻辑下沉 core/
- [ ] 特殊行为都走规则，无硬编码域名分支
- [ ] `--debug` 下新路径有埋点；宽异常有 exc_info
- [ ] `python3 tests/test_smoke.py` 全 PASS

## 2.11 错误与退出码

- 退出码口径（`core/errors.py:MEANING`）：`0` 成功 · `1` 一般错误 · `2` 用法/输入错 · `130` 中断(Ctrl-C)
- 抛本仓异常而非手搓 `print+return`：`core.errors` 的 `UsageError`(→2) / `NotFound`(→2) /
  `WebtoolError(msg, code=)`；`main()` 认 `exit_code` 属性统一落码
- 想直接终止用 `core.errors.die(msg, code=)`（`sys.exit` 带正确码），别裸 `sys.exit(1)`
- `main()` 兜底把**未预期的异常**压成一行 `webtool: 内部错误 …`（退出 1）——
  `-d` 时改为原样抛出保留 traceback。所以"内部错误"出现在输出里 = 有 bug 没兜住，去 `-d` 复现
- 管道截断（`| head`）产生的 BrokenPipeError 算成功（0），不算错误

## 3. 插件与配置边界

- **逻辑进代码，数据进 JSON，调参进 config**：
  - 抓取/解析逻辑 → 模块函数，经 `plugins.json` 声明成插件（engine/site/hot/extractor/resolver/filter/transformer/interceptor/source 九类，函数类签名见 `plugins.SIGNATURES`，`interceptor`/`source` 是类见下）
  - **引擎预设**（`plugins.json` 的 `presets` 段）走 `config_data.load`，**不走插件注册表** —— preset
  是纯数据没有 module/params 可执行字段，注册表那套 fn 解析用不上；同文件意味着用户覆盖
  `plugins.json` 时引擎与预设一起生效。优先级 `--engine` > `--preset` > `config.default_engines` >
  清单默认开启项；未知 preset 退 2 不静默回退（静默回退会让用户以为跑了 A 组其实跑了默认组）
 - 新增搜索引擎的门槛：必须**免 key**、**HTTP 直连**、**HTML 里能拿到真实 URL**。
  perplexity / metaso 是 SPA（要浏览器渲染），duckduckgo / brave 直连 DNS 污染且代理
  返回反爬挑战页或 429 —— 这类接不进来，别浪费一轮去试
 - 改引擎解析后验证必须带 `--no-cache`（搜索结果默认缓存 30s，会让你以为改动没生效）  - 运行时调参（开关联动多模块）→ `webtool config set`（白名单在 `cli/config.py`）
- 新增"看起来该配置化"的东西前先问：它是数据吗？改它需要重跑算法基准吗？数据才进 JSON
- **运行必需的数据必须随包，一律不读仓外路径**：交易日历、逆向文档、接口配方这类
  "没它就跑不对"的数据放 `src/webtool/**/data/`（`pyproject.toml` 的 package-data 要
  覆盖到），需要用户改的放 `~/.webtool/`。曾经交易日历读
  `shared/短线复盘/holidays-*.json`：源码树里跑得好好的，装包后换台机器就静默降级成
  "只按周末判交易日"，而把节假日当交易日的后果是涨停池拿 10-01 去问接口、接口静默
  回旧数据 —— 错误现场离真凶十万八千里。第三方包自带的文件（如 akshare 的 `data/ths.js`）
  用 `importlib.util.find_spec` 定位，**别写死 site-packages 路径**（那是"某版本某装法"的
  快照）。`tests/test_smoke.py` §19/§20 有守卫（缺本年日历 / 代码里出现仓外路径即 FAIL）
- **一次性迁移的"对账守卫"用完就删**：拿"迁移前的原文件"做基准的完整性测试
  （原单体里每个 def 都在、逐行切点对不对），只在迁移**进行中**有意义 ——
  事成之后它测的是一份永不变的历史文件，结论永远为真，却要长期养着那份基线、
  还让功能代码跟它扯上关系。迁移结束就把基线与对账脚本一起删掉，换成当下能验
  的东西：真接口自测 + `self.X(` 悬空检查（漏拆的私有辅助当场暴露）+ 契约测试
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
- 探活统一走 `net.connectivity.proxy_ok`；`pipeline/rank.py` 的 `_proxy_ok` 是它上面加了进程内缓存的薄包装
- 引擎/端点都不自报线路：没有 `engine_proxy` 覆盖，没有 `proxy_hint`，没有 `_proxy_alive`。
  一条请求走直连还是代理，只由规则表（`netx`）判一次
- **MCP 端点既可以只是 `mcp` 的调用目标，也可以直接充当搜索引擎或 fetch 兜底通道**。
  `engines/parallel.py` 与 `engines/firecrawl.py` 是样板：`engines/exa.py`（三者同源）
  端点声明（url / verbs / api_key_env）全部读 `data/mcp.json`，与 `webtool mcp` 共用同一份数据，
  engines 层不 import `cli/`（L1 不得反向依赖 L4），只 import `net/mcpclient` 出网 + `core/config_data` 读声明。
  要让某个 MCP 端点进 `search` 引擎池，实现 `search(query, max_results, proxy, timeout, market, **_)` 返回
  `[{rank, title, url, snippet}]`，再在 `data/plugins.json` 的 `engine` 段登记 `module` + `enabled_by_default`。
  端点侧的 `verbs` 映射不写死在代码里 —— 新端点声明 `verbs` 即可复用。要支持新协议的端点才写新的 `cli/<name>.py`，别把协议塞进引擎里
- **同一个 MCP 端点的 `web_fetch` 返回形状按端点不同，必须在 `pipeline/fetch.py::_reader_text` 分派**，
  别写死一种：firecrawl 回 `{"markdown": ...}`、parallel 回 `{"results":[{excerpts:[...]}]}`、
  exa 回已拼好的 markdown 纯文本。新增通道时**先实测形状**再写分支，并在该通道的 docstring 注明是否已用真 key 验证过
  （无 key 的端点只能按公开文档推定 —— 这种代码要明说"未实测"，别让人误以为已验证）。
  入参形状同样按端点不同，见 `_reader_arg`
- **端点表 `data/mcp.json` 不声明线路**，所有端点统一交给路由表
  （`auto` → 规则表 → proxies.default/直连）。免 key 配额按出口 IP 计，走代理等于蹭别人
  的配额池，要固定某端点直连就加一条针对它域名的规则：
- **默认头（UA/指纹）只有一个注入点**：统一出网层按站点现算（`transport` 的
  requests 适配器 / `headers_for`）。调用点想覆盖就自己给同名头，但**不要**在任何
  局部函数里再补一套默认头——股票源 61 个调用点里只有 15 个走得到 `_kwargs`，
  曾经那条"按站点给 UA"的注释就这么成了空头支票，直到同花顺 data 子域回 403
  才暴露（其余站点不校验，所以静默坏了很久）
  `webtool proxy rule add '{"domain":["exa.ai"]}' direct`
- **`plugins.json` 里没有任何线路字段**：`site.*.proxy`、`engine.*.params.proxy_hint` 都已删除。
  引擎和内置站点一律把线路交给规则表。自定义站点 `~/.webtool/sites/*.json` 的 `proxy` 是
  **用户配置**，继续有效（`direct` / `proxy` / `auto`）
- **只在"只读用户目录那一份、且用户要直接编辑"的文件上做首次落地**：`core/bootstrap.ensure_user_files()`
  在 CLI 首次启动时把包内 `data/rules.json` 复制到 `~/.webtool/rules.json`（已存在则不动）。
  走"包内默认 + 用户覆盖"两层合并的 `config.json`/`plugins.json` 之类**不落地** —— 凭空生成
  一份会盖住以后升级带来的新默认值。pip 没有可靠的 post-install 钩子，所以入口只能是首次启动
  - 种子表是**给"配了代理的人"用的**：`default` 写 `proxy:default`，并带 `geosite:cn` /
    `geoip:cn` 的国内直连规则（比手写域名清单全，也省得漏站）。但刚装好的机器上还没有代理，
    原样落地会让每条请求都撞"规则引用了未定义的代理: default"，所以落地时 `default` 指向的
    命名代理不存在就落成 `direct`（`core.bootstrap._direct_if_proxy_missing`），等
    `webtool proxy set` 那一刻再切回 `proxy:default`（`net.proxy.pool._set`）
- **线路只由配置决定，不做隐式切换**（`netx.resolve_proxy` 是唯一归一点）。"先直连、失败
  再代理"这类回退会让同一次请求走哪条线取决于它先在哪失败，"代理失败退直连"更会毁掉只允许
  代理出网的目标。写通道别加 `allow_fallback` 参数，也别在适配器里写死 `proxy=None` ——
  那等于无视管线传入的代理
- **日志是排查的第一界面，不是装饰**：每条 `logger.*` 都要能回答"哪一层、对什么、
  什么结果"。统一格式 `<模块> | 动作 对象 key=value`，`tests/test_smoke.py` §16 有
  格式守卫。反面教材是 `logger.debug('忽略异常 (容忍路径)', exc_info=True)` ——
  看的人只知道"某处吞了异常"，不知道哪一层、为什么吞；这种日志等于没写
- **级别分工**：`debug` 给排查（决策/耗时/数量/降级）；`warning` 给"用户该知道但不
  致命"（配置键被忽略、配置读坏、降级、熔断、拒绝写入脏数据）。`warning` 会直接
  打到 stderr，别拿它报常规进度
- **每行日志自带时间/文件行号/线程，不许只打消息**：终端
  `12:34:56.789 D [ThreadPoolExecutor-0_0] search.py:175 search | ...`，
  文件版再加完整日期与 logger 名，`.jsonl` 每行含 `ts/thread/file`。
  三者缺一都会让排查卡住：没有毫秒分不清并发先后，没有线程名分不清两行是不是
  同一件事（搜索是多线程抓引擎），没有 `文件:行号` 每看一条都得再去搜一遍代码。
  格式在 `core/logging.py` 一处定义，`tests/test_smoke.py` §17 有守卫
- **关键环节必须有日志**（一次请求要能串成链）：CLI 入口参数 → 引擎调度 → 规则
  命中 → 线路决策 → 请求耗时 → 缓存命中/未命中 → 降级/重试 → 提取结果 →
  过滤统计。链路缺一环，排查就得靠猜
- **每请求必打的日志要去重**：同一结论（如 `resolve_proxy` 一次请求被调两轮）
  成对刷屏会把真正的异常淹没。用进程内 `(key, 结论)` 集合去重并设上限
- **URL 进日志前过 `core.logging.redact_url`**：`token`/`key`/`password` 一类的
  query 值留参数名、值换成 `***`。日志会被贴进 issue、发给别人看，为了排查
  方便把 URL 打全正是最常见的令牌泄漏口
- **配置键必须真有消费者，且默认值要表达"没指定"**：`config.json` 的每个键要么被读，
  要么别放进去 —— 否则用户 `config set` 完毫无反应，排查时还以为是代码里的 bug。
  已经出过三种死法：① 键存在但全仓没人读（`ua`）；② 键在 `cli/config.py` 键表里、
  却不在 `net.proxy.store` 的 `_KNOWN` 白名单里，被 `load_config` 静默过滤
  （`cache` / `default_format`）；③ 读是读了，但被上游形参默认值短路（`timeout=15`
  这种看着像"没指定"、实际是"显式指定 15"，`config set timeout 30` 永远轮不到）。
  规则：默认值一律写 `None` 表示"交兜底链"，兜底链写清优先级；`tests/test_smoke.py`
  有死键守卫盯第①②种
- **超时的兜底链**（`net.pacing.rule_timeout`）：调用方显式 > `rules.json` 的
  `kind:http` 条目（特殊站点特殊对待）> `config.json` 的 `timeout` > 内置 15。
  读 `config.json` 带 mtime 缓存（同 `net.tls._load`），每请求问一次也不读盘
- **输出格式的兜底链**（`cli/_ctx._run`）：CLI 显式 `-f` > `config.json` 的
  `default_format` > 命令自带默认。收口在一处，别让每个命令自己读一遍 ——
  曾经只有 search 读，其余数据命令配了不生效
- **`None` 与 `'auto'` 在代理语义上是同一个意思**：都是"调用方没表态，交规则表定"。
  `'direct'` 才是"强制直连"。这条曾经不一致（`netx.resolve_proxy` 把 None 当直连，
  `proxyhelper.resolve` 把 None 升成 auto，同一份 rules.json 在两条入口给出相反结果），
  最坑的是看不出区别：引擎签名都写 `proxy=None`，谁忘了把管线传下来的 `'auto'` 再传下去，
  谁的会话就永久直连、规则表连问都不问一次。`--no-proxy` 一律传字符串 `'direct'`。
  `tests/test_netx.py` 有纯文本守卫盯这条
- **归一结果回喂必须补 `'direct'`**：`netx.resolve_proxy` 返回的 `None` 是"已判定的直连"
  这个**结论**，不是"没表态"。原样回传给下游（`transport.request` / `_new_session`）会被
  当成 `'auto'` 再问一遍规则表 —— 多问一次，且往往以另一个 URL 问（bing 用 CN 端点判完
  再拿真实 URL 建会话），规则按 path/port 写时结果就可能翻案。要么别提前归一，要么回喂时
  写 `proxy or 'direct'`
- **线路归一必须带目标 URL**：`netx.resolve_proxy(proxy, url)` 少了 url 就只能退默认动作，
  域名/端口/协议/GeoIP 规则对该请求全部失效 —— 这正是用户看到"规则没起作用"的根因。
  `stock/bridge/sources/_routing.resolve(url, override)` 形参顺序相反（URL 在前），别混
- **SOCKS5 的 DNS 归属只在归一层升级**：curl 与 requests 都把 `socks5://` 读成**本地**
  解析（域名先在本机解析，代理只转 IP），`socks5h://` 才是远端解析。国内本机 DNS 常被污染，
  写 `socks5://` 等于代理白配、看着走了其实还是本地网络。升级点收口在
  `netx.resolve_proxy`，下游（`_py_proxies`、`_routing.proxies_for`）只做 URL→字典 的形状
  转换，不自己判线路、不改 scheme —— 否则哪条通道漏改就重现这个坑
- **环境变量不是线路决策源**。`http_proxy`/`https_proxy` 在容器里很常见，各库默认都会读它
  （urllib 的默认 `ProxyHandler`、requests 与 curl_cffi 的 `trust_env=True`）—— 于是规则表
  判定"直连"的主机被悄悄送去代理，用户改配置文件改不动。已经在三处堵死：`net.http.build_opener`
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
  渲染层一律走 `stock/command/_common.py::_j` 兜底序列化 —— 直接 `json.dumps` 会 TypeError
  **崩在渲染层**，而那时数据其实已经取到了，白跑一次网络请求
- **第三侧 `rawapi.py`** 桥 `bridge/sources/`（随仓内置）的
    **157 个低阶方法**（`webtool stock data list api` 出清单），按数据源分包：
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
    `sources/tencent.py` 的 `gtimg_quote_flat` 与 `sources/em/_quote.py` 的 `em_zt_pool`）。engine
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
  结构化输出反而破坏可读性。这类走 `stock/command/_common.py::_passthrough`
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
- **stock 动作的载荷形状按动作不同，`stock/command/_common.py` 的 `_items_of`（广度优先下钻
  `items/list/rows`）统一认领**：news 是 `data.items`，announcement 是 `data.data.list`，
  capital_flow north 是 `data.data.data.{hk2sh,...}`（无列表）。**认不出就标注不猜** ——
  同花顺 stockpage 是 SPA，上游站点解析不出列表会回 100KB 原始 HTML，印出来等于把噪声
  当结果
- **stock 的 `--arg` 类型推断与 `cli/mcp.py` 有意不同**：纯数字一律留字符串（600519 是
  A股代码，整数会被动作参数校验拒）。改这段前先确认不是在给非代码字段传数字
- **`stock/command/_render.py::_render` 对未解析载荷只在 text/markdown 标 stderr 警告**，
  json 保持原样 —— 程序消费方可能自己要那份 html，不该由渲染层替它决定丢弃
- 打包数据在包根 `src/webtool/data/`（不在 `core/` 下），`core.config_data.DATA_DIR`
  指向它；`pyproject` 的 `package-data` 按此配

## 不许 failover（走哪条线一次定死）

同一次请求走哪条线，只能由**配置 + 路由表**决定一次；不许出现"先直连、失败换代理"
"代理被拦就换直连"这类补救。历史上 7 个模块各发明过一套：`core/resilient.py`（代理
失败退直连）、`net/transport.py`（被拦就代理↔直连互换）、`cli/zen.py`（直连优先 +
换代理重试 + 换前探活）、`pipeline/rank.py`、`feeds/fetch.py`、`feeds/command.py`、
`radar/rules.py`。害处有二：①同一次请求走哪条线取决于"它先在哪失败"，不可预测；
②"代理失败退直连"恰好毁掉"只允许代理出网"这个目标本身——你以为在兜底，其实是在
绕过规则。

现在：`transport.get/request` 签名里没有 `allow_fallback` 之类的开关（加了就等于
把这条路请回来），一条通道要么走规则表给的线，要么报错让上层换源/换线路。
测试只断言**行为**（签名里没有该开关），不做文案措辞扫描——换个说法就误报，
且拦不住任何 bug。

## 显式线路不被环境改写

规则表/命令行已经指定了线路（proxy / direct），环境变量不该再插嘴：
`no_proxy` / `NO_PROXY` 只在"没人指定线路"时才说话。反面教材是 urllib 的
`ProxyHandler` —— 它装代理前先问 `proxy_bypass(host)`，于是 `no_proxy='*'`
能让走代理的请求**静默直连**，还把死代理报成 OK，把错误退化成"直连超时"
（查半天也想不到是环境变量）。所以装显式代理一律走
`net.http._NoBypassProxyHandler`；`direct` 用空 ProxyHandler 反遮环境代理。

## 测试脚本的 check() 只有一个签名

手写测试序列统一 `check(cond, msg, detail='')` —— **条件在前，说明在后**。
曾经 21 个脚本写 `check(说明, 条件)`、8 个写 `check(条件, 说明)`，同一个名字
两套顺序，读的人得先翻定义。

统一时最大的坑是**漏搬某个调用点**：如果那个脚本的 `check()` 体用 f-string
打印（不靠 `+` 拼串），传反了也不报错 —— 说明文字是字符串、恒真，于是永远
PASS。所以 `test_smoke.py` §21 用 AST 扫调用点，第一位是字符串常量 / f-string
/ `%` 拼接就判 FAIL。

## 测试不许碰真实 HOME

测试要验证"改配置 → 行为跟随"时，必须在**临时目录**里造配置，一个字节都
不许落到 `~/.webtool`。真实事故：`tests/test_smoke.py` 曾直接改写
`~/.webtool/config.json` 塞入 `proxy: http://127.0.0.1:9`，`finally` 只还原了
config.json，而遗留键迁移顺手把该值写进了 `rules.json` 的 `proxies.default`
—— 每跑一次测试就把现网默认代理改成死端口，用户看到的是"我没改，它自己变的"。

两个坑：① 只改 `config_data.USER_DIR` 不够，路由读的是 `net.proxy` 自己那份
全局（`CONFIG_PATH` / `USER_DIR`），要一起打补丁；② 断言里加一道"真实文件
指纹未变"的校验，否则打错补丁的测试会在真身上跑，还看起来是绿的。

## 遗留键迁移不许覆盖明确配置

迁移（把 config.json 的旧键搬进 rules.json）只在目标位置为空时写入；
已存在的 `proxies.default` / `rules` 优先，冲突只告警不改写。
同样，**没迁成的键必须留在原处** —— 悄悄删掉一个我们读不懂的键才是数据丢失。

## 多源抓取一律并发，但回填顺序恒定

一次搜索打多个源（引擎/站点/榜单），源之间是不同站点、彼此不排队，串行就是
白等：实测 5 个引擎 17s → 10s，`google` 一个就能拖十几秒。并发用
`ThreadPoolExecutor`，并发度统一走"源数、上限 MAX_WORKERS=4 (core.resilient 常量, 业务模块不许自己写数字)"（`--jobs` / `config jobs`
可覆盖），别默认全开 —— 出口是同一条代理/同一条网，开太满只是把自己打满。

两条硬纪律（`tests/test_search_parallel.py` 钉住）：
1. **共享状态只在主线程写**：线程函数只返回自己那份数据（结果、状态、计数），
   累加与回填全在收集循环里做，不在线程里 `results.extend` / `ad_filtered +=`；
2. **结果与错误都按声明顺序回填**：merge 的排序对并列项是稳定的，回填顺序一变
   同一 query 两次跑出不同排名。错误同理，否则"哪个源挂了"随线程完成顺序漂。

反面教材：线程里回填 + 收集循环里再回填一次 —— 结果条数翻倍，而且因为
去重/聚类会"看起来正常"，只有顺序断言能抓到。

## 站点证书进仓库，不关校验

`src/webtool/data/certs/ca-bundle.pem` 是仓库自带的 CA 包（Mozilla 根证书集，
随 wheel 分发，package-data 必须带上 `certs/*.pem` —— 漏了就等于"装完又回到
宿主没 CA 的状态"）。探测链 环境变量 → 系统 CA → certifi → **自带**，自带那份
是兜底：于是"宿主没装 ca-certificates"不再等于"全站不校验"。

站点自签/内部 CA 用 `data/certs/extra/*.pem` 投放，**不要**用 `verify_hosts`
或 `verify=False` —— 前者只是换信任根、仍然是验过才放行。有 extra 时才现拼
"基础 CA + extra"的合并文件（cache/tls/，按内容指纹命名），没 extra 零开销。
合并文件写不进去要退回基础 CA，不能因为缓存目录只读连原有信任根也弄丢。

证书失败的**类别**必须分清再给修法（`tls.cert_advice`）：域名不符（塞证书没用）、
自签（进 extra/）、过期（只能 verify_hosts）、缺中间证书（补 ca_bundle）、
需旧版 TLS 重协商（根本不是证书问题）。一律叫用户改 `ca_bundle` 是误导。

## 被挡的响应走 intercept，传输层不认识具体拦截类型

`net/transport.py` 里不许出现"验证码""WAF""限流"这类词 —— 它只调
`net/intercept.py`：`preflight`（发之前能不能发）/`inspect`（回来的是不是被挡）/
`bypass`（有没有绕法）/`note_ok`/`note_hit`（记账）。加一种拦截（WAF 页、429、
登录墙）只该是写一个 `Interceptor` 子类，不改传输层。

三条硬约束：

- **报错信息不许反向依赖具体插件**：冷却剩多久由 `note_hit` 写回 `hit.left`，
  transport 只读 `hit.why`/`hit.sign`/`hit.left`。否则加插件就得改报错文案。
- **优先级以清单为准**（`plugins.json` 的 `interceptor.<name>.priority`），类属性只是
  代码注册时的默认值。`Registry.items()` 默认过滤 `enabled: false`，要知道"谁被显式
  停用"必须用 `items(enabled_only=False)` —— 过滤掉之后停用信息就没了，内置实现会
  像从没被停过一样照跑。
- **插件出错只让它自己掉队**：加载/实例化/调用三处都要 try，错误记进 `_ERR` 让
  `describe()` / `plugins check` 看得见，绝不能把整条请求链路带崩。
- **引擎自己探通道的路径也得走拦截器**：sogou 的 PC/移动双通道、baidu 的预热会话、
  google 的 web/news 降级都是引擎直接读正文，不走 transport —— 这些地方统一调
  `intercept.gate(engine, text, url=…)`（判定 + 记账一次做完）与
  `intercept.cooldown_of(engine)`（取"冷却 N s"），不许再 `captcha.detect/mark_*`。
  否则新加的拦截器插件对这条路径莫名不生效，而报错文案又会反过来认识 captcha。

## 出网统一走 transport，拦截判定只在网页通道上生效

**本仓自己的代码只有一条出网通道：`net/transport.py`。** 搜索引擎、抓取、
feeds、股票源（`stock/bridge/**`）、MCP（`net/mcpclient`）、LLM（`cli/zen`）、
探活（`net/connectivity`）都经它出网 —— 线路（`netx`）、证书（`tls.policy`）、
指纹（`headers_for`）、cookie、流式读法全在那一层，别处不再各建一套。
`net/http.py` 的 urllib 通道是 transport 的备胎本体（cffi 崩了才走），不是第二条策略。清单钉在 `tests/test_netx.py`「出网原语必须登记」一节：新开一个
`requests.` / `_cr.Session` / `urlopen` 出口会被测试拦下，逼你来这里签字。
（`net/http.py` 曾被列入"与 net 层重叠待合并"——评估结论：不合并。它是
net 之下的原语，net/proxy、net/netx、net/transport 三处依赖它，按"谁被
依赖更广住更低"恰好住对了；真正重叠的通道组装已由 transport 统一。）

只留下三个明确例外（都登记在册）：

- `cli/zenproto.py`：LLM 流式要拿裸 `http.client` 连接。
- `stock/bridge/_eco_net.py`：akshare/tushare 等**外部库**自建 session，改不动，
  作用域内给 `requests.Session.request` 包一层默认代理。
- pip/git 子进程：只能靠环境变量给代理。

由此产生一条边界：**反爬判定/冷却/降级梯只在网页搜索与抓取通道上**（引擎自己
读正文的路径另有 `intercept.gate`）。MCP 服务、LLM API、行情接口虽然也经
transport，但走的是 `transport.request`（不带判定），被挡时只如实报错 —— 这些
上游不会有人机验证页，套上判定是白搭一层。给这类通道加拦截判定前先问：上游
真的会出现人机验证页吗？会，才接。

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
核对与代码一致（命令名、选项、数字）
