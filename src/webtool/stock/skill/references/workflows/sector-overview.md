# Sector Overview — 行业深度

**触发词**：行业 / 赛道 / sector / industry / 行业分析

## Workflow

### Step 1: 行业基础数据
- 同花顺 industry_kline（板块 K 线）
- 雪球 industry（个股归属）
- `clients.web_search` 行业政策

### Step 2: 行业地位
申万一级排名（31 个行业）+ 估值水位。

### Step 3: 产业链
读 `../data/industry-chains.md` 对应产业链 + 调 `scripts/visualization/logic_renderer.industry_chain()` 画图。

### Step 4: 核心驱动
- 政策催化（`../data/policy-keywords.md`）
- 资金流向（`../data/flow-tracking.md`）
- 周期位置（`../data/sector-rotation.md`）

### Step 5: 推荐个股 3-5 只
从 `../data/typical-stocks.md` 选 + 调 `scripts/analysis/single_analysis.analyze()` 验证。

### Step 6: 输出

按 `../templates/research-report.md` 输出。

## 输出形态

行业深度报告（3-5 页）。