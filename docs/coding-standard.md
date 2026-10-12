# webtool 编码规范

本文件是 `src/webtool` 的约定来源。新增代码先读这里；改老代码顺手对齐。

## 1. 分层与分包

物理包结构（自上而下只允许向下依赖，禁止反向）：

```
webtool/
  cli/          L4 应用编排   app / config / plugins / sitesearch / zen / zenproto
  feeds/        L3 业务流程   command / sources / parse / fetch / cards / feedhealth
  radar/        L3 业务流程   routes / rules / instances / official / template
                                           / race / instances_cfg
  pipeline/     L2 合并输出   search / rank / merge / topup / qhint / query_ops
  render/       L2 合并输出   render / hotrender / output
  filters/      L2 结果过滤   blocklist / adfilter        —— 纯规则, 不出网
  net/          L1 采集实现   transport / proxy / captcha / spa / fetch
  engines/      L1 采集实现   baidu / bing / google / sites / hotsites
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

规范名只有 4 个，别名 `md`=markdown、`txt`=text，`render/output.py:FORMATS` 是单一事实来源。

| 格式 | search | site | rank | feed | fetch | zen | engines/plugins/cache/config |
|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| json | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| text | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| markdown | ✅ | ✅ | ✅ | ✅ | ✅ | ~ | ✅ |
| csv | ✅ | ✅ | ✅ | ✅ | ❌ | ~ | ✅ |

- `zen`：只有模型清单（`--list-models` / `--list-free`）接 json/csv；对话输出本身是流式
  文本，markdown 无结构可渲染，回落 text
- `fetch`：拒收 csv，见下

约定：

- **非法值直接退出码 2**，不静默回落 text（`cli/app.py::_norm_fmt`）。回落会让 Agent
  拿到人类可读文本却毫无提示，解析阶段才炸
- 数据命令自己按 `args.format` 渲染（`render.render` / `render.hotrender` /
  `net/fetch._emit`）；管理命令内部是 print，由 `cli/adminfmt.py` 把吐出的 JSON 转格式
- 管理命令不给 `-f` 时保持原样直出（不套一层），给了才转
- `csv` 只导结果行；`filters_applied` 这类统计不进表格，需要就用 `-f json`
- `fetch` 拒收 csv（正文进单元格无意义），抛 `ValueError` 由 `_run` 转成用法错误
- CSV 列序 = `render/csvout.py:COLUMNS` 中本数据集真有值的列，保持固定相对次序。
  曾按固定 19 列输出，导致 `engines list -f csv` 整表全空
- **CSV 公式注入必须防**：字段全是抓来的不可信文本（站方可控制 title/snippet），
  `= + - @` 开头的单元格会被 Excel/Sheets 当公式执行。`csvout._cell()` 统一前缀 `'`
  降级成文本；判定要先 `lstrip` 前导空白，否则 `\t=1+1` 绕过。smoke 有契约测试锁死

## 2. 导入

- **一律绝对导入**：`from webtool.core.config_data import load`；禁止 `from .x` / `from ..x`
  （历史 116 处已于 2026-10 全量迁移，rg 检查：`rg "from \.|from \.\." src/` 应无输出）
- import 顺序：标准库 → 三方 → webtool，组间空行
- 循环依赖靠"函数内延迟 import"打破只允许出现在真实循环场景，且写一行注释说明原因；能靠分层消除的不用这招

## 3. 插件与配置边界

- **逻辑进代码，数据进 JSON，调参进 config**：
  - 抓取/解析逻辑 → 模块函数，经 `plugins.json` 声明成插件（engine/site/hot/extractor/resolver/filter/transformer 七类，签名见 `plugins.SIGNATURES`）
  - 纯数据表（域名、指纹、TTL、实例列表）→ `data/*.json`（`filters.json` / `plugins.json` / `instances.json` / `zen.json` / `feeds.seed.json`），用户用 `~/.webtool/` 同构文件覆盖，mtime 热生效
  - 运行时调参（开关联动多模块）→ `webtool config set`（白名单在 `cli/config.py`）
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
- `engines/sites.py` 的 `_mk/_fetch/_headers` 被 6 个模块跨文件复用（customsites / sitesearch /
  feeds.fetch / hotsites / moresites / moresites2 / oversites），暂留私有名；
  真要复用得按规范去掉 `_` 并下沉到 `core` 或 `engines/base.py`
- 打包数据在包根 `src/webtool/data/`（不在 `core/` 下），`core.config_data.DATA_DIR`
  指向它；`pyproject` 的 `package-data` 按此配
