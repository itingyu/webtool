# Initiating Coverage — 首次覆盖

**触发词**：initiation / 首次覆盖 / 首次推荐 / initiate

## Workflow

### Step 1: 公司概况
- 雪球 f10/company + f10/business
- 巨潮 company_intro
- 主营业务 + 行业地位

### Step 2: 财务三表（最近 3 年）
- 收入 / 净利润 / 现金流 / 负债率
- 雪球 f10/indicators 已下线，`clients.web_search` 兜底

### Step 3: 估值
- PE / PB vs 同业
- 调 `scripts/fetchers/xueqiu.quote()` 拿 PE/PB
- 对照 `../data/typical-stocks.md` 同业

### Step 4: 业务驱动 + 风险
- 收入驱动：客户/产品/区域
- 利润率驱动：成本结构/规模效应
- 风险：竞争/政策/客户集中度

### Step 5: 单股技术位
调 `scripts/analysis/single_analysis.analyze(code)`

### Step 6: 评级 + 目标价
- 买入/持有/卖出
- 12 月目标价（基于 PE 估值）
- 当前价 vs 目标价 = 潜在涨幅

### Step 7: 输出

按 `../templates/research-report.md` 输出完整研报。

## 输出形态

完整首次覆盖报告（5-10 页 Markdown）。