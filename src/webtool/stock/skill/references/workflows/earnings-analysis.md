# Earnings Analysis — 财报后分析

**触发词**：earnings update / 财报后 / post-earnings / 业绩点评

## Workflow

### Step 1: 拉财报数据
巨潮 + 雪球 f10/company 拿当季财报。

### Step 2: 同比 / 环比
对比：
- 收入同比 / 环比
- 净利润同比 / 环比
- 毛利率 / 净利率变化

### Step 3: 单股深度
调 `scripts/analysis/single_analysis.analyze(code)` 跑技术面。

### Step 4: 业绩 vs 预期
对比一致预期（来自 earnings-preview）。

### Step 5: 指引与展望
管理层指引 + 下季度展望。

### Step 6: 输出

按 `../templates/single-analysis-card.md` 模板 + 业绩点评段。

## 输出形态

业绩超预期/符合/不及预期 三档判断 + 调整后的目标价。