# Single-Analysis — 单股深度分析工作流

**触发词**：分析下 XX / XX 怎么样 / XX 估值 / TSLA / HK00700 / AAPL

## Workflow

### Step 0: 解析股票代码
- 6 位数字 → A 股
- HK + 5 位数字 → 港股（暂未对接，仅 A 股稳定）
- 1-5 位大写字母 → 美股（暂未对接）

### Step 1: 拉数据
调 `scripts/analysis/single_analysis.analyze(code)`：

输出字段：
- quote: current / percent / pe_ttm / pb / 流通市值(亿)
- technical: 现价 / MA5/10/20/60 / 量比 / ATR / 支撑阻力
- score: 0-60（技术面）
- signal: 强买入/买入/持有/减仓/卖出
- warnings: RSI>80 / 乖离率>5% 等禁买信号
- industry: 雪球行业归属
- announcements_7d: 最近 7 天公告

### Step 2: 消息面（必做）
`clients.web_search` 搜 "{name} 最新消息 2026" / "{code} 公告"

### Step 3: 情绪打分
调 `scripts/sentiment/news_scorer.score(news_items)`

### Step 4: 输出
按 `../templates/single-analysis-card.md` 模板生成决策看板。

## 数据源

- 雪球：quote / K 线 / f10 / industry
- 巨潮：公告
- `clients.web_search`：消息面

## 硬规则

- RSI > 80 → 禁买（标记 warning）
- 乖离率 MA5 > 5% → 禁买（标记 warning）
- 必须给精确的止损价和目标价
- 偏好缩量回调买点

## 输出形态

单只股票决策看板：
- 头部：评级 + 评分 + 关键价位
- 估值与市值表
- 技术面表
- 入场价位三档
- 风控位
- 公告 + 新闻情绪
- 风险声明