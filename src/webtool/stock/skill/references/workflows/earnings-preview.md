# Earnings Preview — 财报前分析

**触发词**：earnings preview / 财报前 / pre-earnings

## Workflow

### Step 1: 财报日历
调用 `scripts/fetchers/cninfo.announcements(code, days=60)` 查财报披露时间。

### Step 2: 一致预期
`clients.web_search` 搜：
- "{公司} Q2 2026 一致预期"
- "{公司} consensus estimate"

### Step 3: 历史对比
拉雪球 K 线，标记过去 4 个财报日 ±3 日的股价表现。

### Step 4: 关键观察指标
列出本季度需要重点关注的：
- 收入增速
- 毛利率
- 运营杠杆
- 指引

### Step 5: Bull/Bear 情景

| 情景 | 概率 | 股价预期 |
|---|---|---|
| 超预期 +5% | 30% | +10-15% |
| 符合预期 | 50% | ±3% |
| 不及预期 -5% | 20% | -8-12% |

### Step 6: 交易策略

- 财报前 5 个交易日：减仓 30% 防黑天鹅
- 财报后开盘：依结果分批加/减
- 财报后开盘跳空跌破 -7% → 立即离场（全 skill 统一止损）

## 输出形态

按 `../templates/earnings-preview.md` 输出。