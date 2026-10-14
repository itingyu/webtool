# Mid-Screen — 中线选股工作流

**触发词**：中线 / 3-6 月 / 产业主线 / 中线选股

## Workflow

### Step 0: 参数
- 持有周期 3-6 月
- 流通市值 > 200 亿
- MA60 向上 + 现价 > MA60

### Step 1: 候选池来源
- 用户指定（如"AI 算力主线"）
- 参考 `../data/typical-stocks.md` 中线池典型标的
- 调 `scripts/screening/mid_pool.run(codes)` 跑筛选

### Step 2: 筛选条件
详见 `../data/pool-indicators.md` 中线池段：
- 流通市值 > 200 亿
- 行业景气度处于上行周期
- 中报预增 / 业绩验证
- MA60 向上
- 北向 / 融资 资金净流入

### Step 3: 输出

按 `../templates/single-analysis-card.md` 模板对每只输出（多只候选用表格）。

## 数据源

雪球 quote / K 线 + f10

## 输出形态

每只标的输出 + 中线配置建议（核心 < 6% / 卫星 < 4%）