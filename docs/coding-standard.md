# webtool 编码规范

本文件是 `src/webtool` 的约定来源。新增代码先读这里；改老代码顺手对齐。

## 1. 分层与分包

包结构（自上而下只允许向下依赖，禁止反向）：

```
L4 应用编排   cli                    # 命令行入口, 唯一可 import 任何层的层
L3 业务流程   search / rank / feed / sitesearch / fetch
L2 合并输出   merge / render / hotrender / output / proxy / status / topup
L1 采集实现   engines/* / spa / radar / zen / captcha / transport / extractors
              blocklist / adfilter / customsites / query_ops / gnews ...
L0 基础设施   plugins / config_data / cache / state / http / probe / resilient
              feedhealth / qhint / configcmd / plugincmd
```

判定规则（写代码前自查）：

- L0 不知道任何业务概念：不 import L1+ 的任何模块
- `engines/` 只被上层调用，实现里不 import `search / rank / feed / sitesearch / fetch / cli`
- 工具函数按"谁依赖更广就住更低"归位：探活、限速这类被多业务用的，住 transport/probe，不住业务文件
- 出现 `from webtool.search import ...` 出现在 engines/ 下即分层破坏，必须下沉到 L1/L2 或抽到 L0

## 2. 导入

- **一律绝对导入**：`from webtool.config_data import load`；禁止 `from .x` / `from ..x`
  （历史 116 处已于 2026-10 全量迁移，rg 检查：`rg "from \.|from \.\." src/` 应无输出）
- import 顺序：标准库 → 三方 → webtool，组间空行
- 循环依赖靠"函数内延迟 import"打破只允许出现在真实循环场景，且写一行注释说明原因；能靠分层消除的不用这招

## 3. 插件与配置边界

- **逻辑进代码，数据进 JSON，调参进 config**：
  - 抓取/解析逻辑 → 模块函数，经 `plugins.json` 声明成插件（engine/site/hot/extractor/resolver/filter/transformer 七类，签名见 `plugins.SIGNATURES`）
  - 纯数据表（域名、指纹、TTL、实例列表）→ `data/*.json`（`filters.json` / `plugins.json` / `instances.json` / `zen.json` / `feeds.seed.json`），用户用 `~/.webtool/` 同构文件覆盖，mtime 热生效
  - 运行时调参（开关联动多模块）→ `webtool config set`（白名单在 `configcmd.CONFIG_KEYS`）
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
- `rank._proxy_ok` 是 `probe.proxy_ok` 的兼容别名，新代码直接用 `probe.proxy_ok`
- `search.py` 的 `proxy_hint/_proxy_alive` 同理是兼容再导出，实现在 `transport.py`
