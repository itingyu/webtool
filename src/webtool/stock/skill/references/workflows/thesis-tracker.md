# Thesis Tracker — 持仓 thesis 跟踪

**触发词**：thesis / 持仓跟踪 / portfolio monitoring

## Workflow

### Step 1: 列持仓
用户提供持仓列表（含代码 / 成本 / 仓位）。

### Step 2: 每只检查
对每只持仓调 `scripts/analysis/single_analysis.analyze(code)`，对比上次笔记。

### Step 3: 评分变化
- 评分上升 → 加仓候选
- 评分下降 → 减仓候选
- 信号改变（买入→卖出） → 立即评估

### Step 4: 触发器更新
- 新的催化 / 风险
- 行业轮动是否让位
- 资金面变化

### Step 5: 输出

| 代码 | 上次评分 | 当前评分 | 变化 | 信号 | 操作 |
|---|---|---|---|---|---|

## 数据源

雪球 + 巨潮 + `clients.web_search`

## 输出形态

持仓调整建议表。