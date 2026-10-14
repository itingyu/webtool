# Long-Screen — 长线选股工作流

**触发词**：长线 / 高股息 / 破净蓝筹 / 6-18 月 / 底仓

## Workflow

### Step 0: 参数
- 持有周期 6-18 月
- 流通市值 > 500 亿

### Step 1: 候选池来源
参考 `../data/typical-stocks.md` 长线池典型标的：
- 银行 / 煤炭 / 公用 / 高速铁路 / 保险 / 运营商

或用户提供代码列表。

### Step 2: 筛选条件
详见 `../data/pool-indicators.md` 长线池段：
- PB < 1.0x（破净优先）
- 股息率 > 4.0%（TTM）
- ROE > 8%（连续 3 年）
- 资产负债率 < 70%
- 北向资金近 60 日净流入
- 机构持仓 > 30%

> **沙盒限制**：股息率 / PB / ROE 等财务指标雪球 f10/indicators 已下线
> 解决方案：`clients.web_search` 查 "{code} 股息率 2026" 或用 Wind / iFinD 补足

### Step 3: 输出

按 `../templates/single-analysis-card.md` 模板输出。

## 输出形态

长线配置：单股 < 5%，总仓位 30%