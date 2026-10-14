# Workflows 索引

按工作流名查找具体步骤。

| 工作流 | 触发词 | 文件 | 核心调用 |
|---|---|---|---|
| **短线选股**（稳健） | "短线选股" "每日候选" "盘中可买入清单" "下周一买什么" "复盘" | `short-screen.md` | `short_tool.py check` + `screening.short_pool` |
| **打板**（进攻） | "打板" "涨停追入" "二板战法" "龙头战法" "集合竞价打板" | `limit-up.md` | `short_tool.py pool --only-buy` |
| 单股分析 | "分析 XX" "XX 怎么样" "能买吗" | `single-analysis.md` | `analysis.single_analysis` |
| 中线选股 | "中线" "3-6 月" | `mid-screen.md` | `screening.mid_pool` |
| 长线选股 | "长线" "高股息底仓" | `long-screen.md` | `screening.long_pool` |
| 通用选股框架 | "选股" "idea generation" | `idea-generation.md` | — |
| 行业深度 | "行业" "赛道" "sector" | `sector-overview.md` | — |
| 财报前 | "earnings preview" | `earnings-preview.md` | — |
| 财报后 | "earnings update" | `earnings-analysis.md` | `analysis.single_analysis` |
| 首次覆盖 | "initiation" "首次覆盖" | `initiating-coverage.md` | `analysis.single_analysis` |
| 事件日历 | "catalyst" "事件" "下周一事件" | `catalyst-calendar.md` | `clients.announcements` |
| thesis 跟踪 | "thesis" "持仓跟踪" | `thesis-tracker.md` | — |
| 可比公司 | "comps" "可比" | `comps-analysis.md` | — |
| DCF 估值 | "DCF" "估值" | `dcf-model.md` | — |
| 竞争分析 | "competitive" "竞争格局" | `competitive-analysis.md` | — |
| 并购模型 | "merger" "M&A" | `merger-model.md` | — |
| deal tracker | "deal tracker" "pipeline" | `deal-tracker.md` | — |
| IC memo | "IC memo" "投委会" | `ic-memo.md` | — |

> `short-screen`（稳健）与 `limit-up`（进攻）**互斥**，同一时段只跑一个。

## 通用入口（所有工作流共用）

数据层不直接调 `fetchers.*`，统一走 `scripts/clients`：

```python
import sys; sys.path.insert(0, '/var/minis/skills/stock-master')
from scripts import clients as C
C.quote([...])            # 行情（含涨停/跌停价、量比、换手、流通市值）
C.limit_up_pool(date)     # 涨停池（连板/首封/炸板/封单）
C.calendar / prev_trading_day()
C.announcements(code) / C.news(code) / C.financials(code)
C.capital_flow(scope)     # 北向 status=3 → unavailable，禁止当 0
C.web_search(q, n)        # 消息面 / 黑天鹅扫描
C.code_ok(code)           # 不可买板块过滤
```

## 配套规则（`../data/`）

- `screen-criteria.md` — 不可买板块 + 重组股 + 闸门 A/B 两层（6 自动 + 4 人工）+ 评分 + 换手分阶段
- `strategy-playbook.md` — 6 主策略模板
- `limit-up-types.md` — 6 种打板类型详解
- `limit-up-pitfalls.md` — 13 条打板避坑
- `pool-indicators.md` — 长中短线三层池指标
- `a-share-rules.md` — A 股特殊规则
- `typical-stocks.md` — 各池典型标的
- `sector-rotation.md` — 板块轮动框架
- `industry-chains.md` — 产业链联动
- `themes.md` — 主题轮动
- `flow-tracking.md` — 资金面 5 维度
- `policy-tracking.md` / `policy-keywords.md` — 政策日历 / 关键词映射
- `auction-patterns.md` — 集合竞价 4 形态
- `morning-note-checklist.md` — 开盘预测 6 条硬清单
- `lessons-learned.md` — 跨工作流经验教训
