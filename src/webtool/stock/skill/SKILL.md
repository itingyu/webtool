---
name: stock-master
description: A 股 / 港股 / 美股**全场景股票分析 hub**。触发词：「短线选股 / 下周一买什么 / 入场价位 / 每日候选 / 盘中可买入清单 / 涨停过滤 / 复盘 / 打板 / 涨停追入 / 追板 / 二板战法 / 龙头战法 / 集合竞价打板 / 集合竞价 / 早盘准备 / 中报预增 / 主线跟随 / 回踩低吸 / 突破跟随 / 反包 / 事件驱动 / 板块轮动 / 单股分析 / 估值 / DCF / 可比公司 / 财报前 / 财报后 / 首次覆盖 / 行业深度 / 事件日历 / thesis 跟踪 / 并购 / IC memo / 长线底仓 / 高股息 / 破净蓝筹 / 龙虎榜 / 北向资金 / 融资融券」。工作流：单股深度 / 短线选股（1-5 个交易日，不可买板块过滤 + 6 项工具自动闸门 + 4 项人工判定 + 100 分制评分 + 三档入场价）/ 打板 SOP（6 道关 + 三档出场）/ 中线池 / 长线池 / 板块轮动 / 资金面 / 政策追踪 / 财报前 / 财报后 / 晨会 / 研报 / 估值建模（DCF / comps）/ 竞争分析 / 并购模型 / IC memo。数据源：腾讯行情 + 东财涨停池 + 雪球 + 同花顺 + 新浪 + 巨潮 + 多源编排(24 动作)。
---

# stock-master

读到这个 SKILL.md 时，先按下面"场景 → reference"表找到最匹配的工作流文件，读它，再按工作流内部的步骤调用 `scripts/` 下对应模块。

agent 自己决定调用顺序与并行策略。

---

## 工作流

按文件列。每个文件自述适用场景，agent 读完用户消息后对照"适用场景"判断读哪个。

### 筛选 / 选股

| 文件 | 适用场景 |
|---|---|
| `references/workflows/short-screen.md` | **稳健模式**。短线选股、每日候选、盘中可买入清单、下周一买什么、入场价位、复盘、中报预增选股 |
| `references/workflows/limit-up.md` | **进攻模式**。打板、涨停追入、二板战法、龙头战法、集合竞价打板 |
| `references/workflows/mid-screen.md` | 中线选股（3-6 月）、产业主线机会 |
| `references/workflows/long-screen.md` | 长线选股（6-18 月）、高股息底仓、破净蓝筹、价值投资 |
| `references/workflows/idea-generation.md` | 通用选股思路、价值/成长/质量/事件驱动 4 大风格框架 |

> ⚠️ `short-screen` 与 `limit-up` 是**两种互斥模式**（稳健 vs 进攻），
> 同一时段只跑一个，不要混用输出。

### 分析

| 文件 | 适用场景 |
|---|---|
| `references/workflows/single-analysis.md` | 分析单只股票、估值、技术面、"能买吗"/"能进吗"、"加仓减仓"、"看看 XX"、"位置好不好"、"目标价" |
| `references/workflows/sector-overview.md` | 行业深度、赛道研究、半导体/银行/医药板块 |
| `references/workflows/competitive-analysis.md` | 竞争格局、护城河分析 |

### 财报 / 催化

| 文件 | 适用场景 |
|---|---|
| `references/workflows/earnings-preview.md` | 财报前分析、pre-earnings、业绩前瞻 |
| `references/workflows/earnings-analysis.md` | 财报后点评、业绩 update |
| `references/workflows/catalyst-calendar.md` | 事件日历、下周事件、催化跟踪 |

### 估值 / 模型

| 文件 | 适用场景 |
|---|---|
| `references/workflows/comps-analysis.md` | 可比公司、comps、同业对比 |
| `references/workflows/dcf-model.md` | DCF 估值、内在价值、现金流折现 |
| `references/workflows/merger-model.md` | 并购模型、M&A、accretion dilution |

### 持仓 / 投行

| 文件 | 适用场景 |
|---|---|
| `references/workflows/thesis-tracker.md` | thesis 跟踪、持仓 monitoring、调仓、组合调整 |
| `references/workflows/deal-tracker.md` | deal pipeline、IPO 跟踪、并购重组跟踪 |
| `references/workflows/initiating-coverage.md` | 首次覆盖、initiation |
| `references/workflows/ic-memo.md` | 投委会备忘录、IC memo |

### 模板（直接套，不算 workflow）

| 文件 | 适用场景 |
|---|---|
| `references/templates/morning-note.md` | A 股晨会、开盘前准备、集合竞价、9:25 异动 |
| `references/templates/short-screen-card.md` | 短线选股报告输出结构 |
| `references/templates/excel-short-screen.md` | 短线选股 Excel（4 sheet） |
| `references/templates/single-analysis-card.md` | 单股决策看板输出结构 |
| `references/templates/research-report.md` | 完整研报输出结构（首次覆盖 / 行业深度）|
| `references/templates/earnings-preview.md` | 财报前分析输出结构 |
| `references/templates/ic-memo.md` | 投委会备忘录输出结构 |

**完整索引**：`references/workflows/README.md`

### 拿不准时

- 用户提了**具体股票代码**但没说干啥 → `single-analysis.md`
- 用户说**"看看"/"分析"/"怎么样"** 但没标的 → 追问代码，或读 `short-screen.md` 出推荐
- 用户说**"打板"/"追板"/"二板"** → `limit-up.md`（**不要走 short-screen**）
- 用户提**板块名** + 想了解 → `sector-overview.md`
- 用户说**"我的持仓"/"调仓"/"复盘"** → `thesis-tracker.md`
- 用户说**"今天"/"9:25"/"开盘前"** → `morning-note` 模板
- 完全模糊 → 追问一句：你要做选股、单股分析、研报，还是其他？

---

## 数据层（scripts/clients/ — 唯一入口）

**工作流不要直接调 `fetchers.*`，统一走 `clients`。**
这样数据源切换、fallback、单位统一只在一处维护。

```python
import sys; sys.path.insert(0, '/var/minis/skills/stock-master')
from scripts import clients as C
```

| 需求 | 调用 | 说明 |
|---|---|---|
| 实时行情（含涨停/跌停价、量比、换手、流通市值） | `C.quote(codes)` | 腾讯主源，支持指数别名（`上证指数`/`创业板指`）；单位=亿元 |
| 涨停池（连板/首封/炸板/封单/行业） | `C.limit_up_pool(date)` | 东财；`date=None` 或 `"last"` = 上一交易日 |
| 公告 / 新闻 / 财务指标 | `C.announcements(code)` / `C.news(code)` / `C.financials(code)` | 走编排层 |
| 资金流（行业榜 / 个股榜 / 北向） | `C.capital_flow(scope)` | `scope ∈ {industry, individual, north}`；**均为榜单**（Top N 表格），不是按代码查询；北向 `status=3` → `unavailable` 字段列出不可用项，**禁止当 0** |
| 网页搜索（消息面 / 黑天鹅扫描） | `C.web_search(q, n)` | 走 webtool（Bing/搜狗/百度） |
| 不可买板块过滤 | `C.code_ok(code)` | 全局唯一口径 |

> **K 线取数**：`xueqiu.kline(sym, period, count)` 的实际条数由 `begin` 时间戳决定，
> 已按周期反推跨度（day ×1.6 / week ×9.8 / month ×39）。请求 250 条即得 ≥250 条；
> 自检有断言锁住，改动此处务必先跑 `_selftest.py`。

#### 共享资产（skill 之外，改动需谨慎）

| 路径 | 用途 | 谁在用 |
|---|---|---|
| `/var/minis/shared/短线复盘/holidays-YYYY.json` | 节假日表（`non_trading` 数组） | `_common._holidays()`、`short_tool.calendar()`；**缺文件时静默退化为「仅按周末判断」**，跨长假会算错交易日 |
| `/var/minis/shared/股票/短线选股/` | 短选报告与 Excel 归档 | `export/short_screen_excel.py` |
| `/var/minis/shared/股票/数据/` | 板块推演 / 月度复盘底稿 | 人工分析素材 |

> 节假日表**只到当年**，跨年要补 `holidays-2027.json`，否则次年春节等长假会被判成交易日。

### 命令行（常用）

```sh
cd /var/minis/skills/stock-master
python3 scripts/short_tool.py calendar
python3 scripts/short_tool.py quote 上证指数 创业板指 沪深300
python3 scripts/short_tool.py pool --date last --only-buy
python3 scripts/short_tool.py check 600886 600036
python3 scripts/short_tool.py filter 600121 300913
python3 scripts/short_tool.py header --mode pre --kind screener
python3 scripts/_selftest.py --quick        # 改过脚本后先跑这个（约 20s）
```

### 底层 fetchers（clients 内部的实现，一般不用直接调）

`fetchers.xueqiu`（quote/kline/f10/行业归属）、`fetchers.ths`（申万行业/板块 K 线）、
`fetchers.sina`（涨幅榜/5 档）、`fetchers.cninfo`（公告/公司简介）、
`fetchers.eastmoney`（雪球失败时的 fallback）。

**鲁棒性**：HTTP 4xx/5xx、字段缺失、列表为空时打 `WARN` 日志，不静默吞。

### 数据源实测状态

| 源 | 用途 | 状态 |
|---|---|---|
| 腾讯 `qt.gtimg.cn` | 实时行情（涨停/跌停价、量比、换手） | ✅ 首选 |
| 东财 `push2ex` | 涨停池（连板/首封/炸板/封单） | ✅ |
| 雪球 | quote / K 线 / industry | ✅ |
| 同花顺 | 行业板块 / 资金流 | ✅ |
| 新浪 | 涨幅榜 / 全市场快照 | ✅ |
| 巨潮 | 公告 / 公司概况 | ✅ |
| 编排层（24 动作） | 公告 / 新闻 / 财务 / 资金流 | ✅ |
| 东财 push2/push2his | 个股行情备源 | ⚠️ 沙盒受限，作 fallback |

**不可用**：东财 clist 列表、中证、网易、百度 finance、同花顺 gn 概念板块（沙盒返 0 字节）。

### 自检（改动脚本后必跑）

```sh
python3 scripts/_selftest.py            # 全链路 60 项：日历/行情/涨停池/可买性/clients/fetchers/分析/筛选/风险/情绪/研报
python3 scripts/_selftest.py --quick    # 跳过慢项（约 20s）
python3 scripts/_probe_actions.py       # 编排层 24 个动作探活（出网，串行约 10s）
```

自检退出码非 0 即代表有 FAIL/EMPTY 项，**不得交付**。

### 已知限制

| 限制 | 影响 | 缓解 |
|---|---|---|
| 港股 / 美股未直连 | 单股分析仅 A 股 | 走 `clients.web_search` 兜底 |
| 同花顺 f10/indicators 下线 | DCF / Comps 数据缺 | 巨潮 + `web_search` 补 |
| 龙虎榜 / ETF 申赎未直连 | 资金面维度缺 | 同花顺资金流代理（**榜单形式**，非按代码查） |
| 北向资金 `status=3` | 资金面维度不可用 | 显式标注 `unavailable`，跳过该项，**禁止当 0** |
| 东财涨停池忽略无效日期 | 请求 20261011 会回 `qdate=20261009` 的旧数据 | `pool()` 返回 `date`（真实数据日）+ `日期回退` 告警，**以 `date` 为准** |
| 节假日表只到当年 | 跨年被判成交易日 | 每年补 `shared/短线复盘/holidays-YYYY.json` |

---

## 分析层（scripts/analysis/）

| 用途 | 调哪个 |
|---|---|
| 单只股票深度（quote + K 线 + 技术指标 + 100 分制评分 + 决策信号 + 公司画像） | `analysis.single_analysis.analyze(code[, news_items])` |
| 技术指标 / 三档入场价位 / 止损止盈 | `analysis.tech_indicators.calc()` / `.technical_levels()` |
| 短线技术分（0-100，仅技术面）/ 综合分（0-100） | `analysis.tech_indicators.score_short()` / `.score_general(df, news_items=None, macro_score=None)` |

---

## 筛选层（scripts/screening/）

| 用途 | 调哪个 |
|---|---|
| 短线池（1-5 个交易日，6 项工具自动闸门 + 4 项人工判定，技术面分 ≥ 60/100） | `screening.short_pool.run(min_score=60)` |
| 中线池（3-6 月，MA60 向上 + 市值 > 200 亿） | `screening.mid_pool.run(codes=[...])` |
| 长线池（市值 > 500 亿） | `screening.long_pool.screen_one(code)` |
| 典型标的池（各主线代表股，已全部过滤为可买主板） | `screening.mid_pool.suggest_typical_stocks()` / `screening.long_pool.suggest_typical_stocks()` |
| 池路由（short / mid / long 统一入参） | `screening.pool_selector.select(pool_name, codes=[...])` |
| 风险股核查（重组股 / 减持 / 立案 / 预亏） | `screening.risk_check.scan(code)` |

筛选硬门槛 / 配比 / 风控在 `references/data/screen-criteria.md` + `pool-indicators.md`。

---

## 静态规则（references/data/）

按需查阅，不要全部加载：

| 文件 | 何时读 |
|---|---|
| `data/screen-criteria.md` | 跑筛选时（不可买板块 + 闸门 A/B 两层 + 评分） |
| `data/strategy-playbook.md` | 选股时匹配主策略（6 选 1） |
| `data/limit-up-types.md` | 打板时（6 种类型详解） |
| `data/limit-up-pitfalls.md` | 打板前（13 条避坑） |
| `data/pool-indicators.md` | 长中短线池指标 |
| `data/a-share-rules.md` | A 股特殊规则（T+1 / 涨跌停 / 北交所） |
| `data/typical-stocks.md` | 用户要参考标的池时 |
| `data/sector-rotation.md` | 板块轮动判断 / 主线识别 |
| `data/industry-chains.md` | 行业深度报告的产业链段 |
| `data/themes.md` | 主题轮动（短/中/长期） |
| `data/flow-tracking.md` | 资金面 5 维度信号解读 |
| `data/policy-tracking.md` | 政策日历 + 解读框架 |
| `data/policy-keywords.md` | 政治局关键词—板块映射 |
| `data/auction-patterns.md` | 集合竞价 4 形态 |
| `data/morning-note-checklist.md` | 开盘预测 / 晨会 6 条硬清单（自检） |
| `data/lessons-learned.md` | 跨工作流通用经验教训（软规则） |

---

## 硬约束（无论哪个工作流都遵守）

1. **数据真实性**：行情/资金/价格必须来自 `clients`、`short_tool.py` 或联网验证，**不允许凭印象编造**
2. **入场价位**：突破/回踩/竞价三档必须给具体数字（脚本输出），禁止"前高附近"
3. **止损纪律**：硬止损 -7%（全 skill 唯一值），必须给具体价格
4. **仓位口径**：短线单票 ≤ 10%/持仓 ≤ 3 只；打板单票 ≤ 5%/持仓 ≤ 2 只/日总仓 ≤ 10%
5. **行业分散**：短线池跨 ≥ 3 个申万一级；打板**不做**分散要求（题材集中取胜）
6. **策略类型**：6 主策略必须明确标签
7. **风险声明**：末尾必须含"仅基于公开信息研究，不构成投资建议；A 股 T+1，硬止损必须执行"
8. **已删除清单**：选股/打板输出必须列明被剔除标的及原因（含重组股）
9. **接口 0/空处理**：0 / 空字符串 / 停牌不能当正常值，标"未取得"或"接口未推送"；
   北向 `status=3` 必须显式标注 ⚠️，**禁止填 0**
10. **开盘预测硬清单**：开盘预测 / 晨会 / 9:25 准备工作流必须过
   `data/morning-note-checklist.md` 6 条（外盘标注内因确认 / 指数vs个股分开 /
   指数间强弱 / 涨幅榜属性 / 资源三要素 / 接口 0 标注）

---

## 使用模式

```bash
# 单只股票分析
python3 -c "
import sys, json; sys.path.insert(0, '/var/minis/skills/stock-master')
from scripts.analysis import single_analysis
print(json.dumps(single_analysis.analyze('600519'), ensure_ascii=False, indent=2))
"

# 短线选股（稳健）
python3 -c "
import sys; sys.path.insert(0, '/var/minis/skills/stock-master')
from scripts.screening import short_pool
r = short_pool.run(min_score=60)
print(f\"通过 {r['passed_count']} 只\")
for p in r['passed'][:5]:
    print(f\"  {p['code']} {p['name']} 评分={p['score']}\")
"

# 打板（进攻）—— 先看今天有什么板
python3 scripts/short_tool.py pool --date last --only-buy
```

agent 在 conversation 中自己决定调哪个、调几次、结果怎么呈现。

---

## 维护本 skill

当用户说"优化 skill"/"补一个功能"/"skill 缺什么"，或 agent 跑工作流发现脚本 / 模板 / 数据缺位时：

**读 `references/maintenance/updating-skill.md`** —— 按 7 步流程执行：

1. 明确缺口（功能 / 数据源 / 模板 / 规则 / 工作流）
2. 归类到 `scripts/{clients|fetchers|analysis|screening|export}/` 或 `references/{workflows|templates|data}/`
3. 写代码 / 文档（最小化改动 + 向后兼容）
4. 在 SKILL.md 表格登记入口（不改 `name` / `description`）
5. 在相关 workflow 文件加引用
6. 自测（`python3 scripts/_selftest.py` 退出码必须为 0；新增接口补进自检）
7. 在 updating-skill.md 底部追加**决策记录**——只写「为什么」和「当前状态」，
   不写版本号、不写「从 X 改成 Y」的对比

**不在 skill 根目录建 README / CHANGELOG**：SKILL.md 就是唯一入口说明，
重复文件必然失同步（`references/workflows/README.md` 是内部索引，可以留）。

**禁止**：
- 不写 CHANGELOG / 版本历史（用完即弃的中间态，不是交付物）
- 不改 frontmatter 的 `name` / `description`（触发器，改了技能就认不出来）
- 不破坏硬约束（硬止损 -7%、仓位口径是纪律）
- 不写会变的东西进文档（字段号、具体价位、接口路径）——写工具命令，不写字段号
