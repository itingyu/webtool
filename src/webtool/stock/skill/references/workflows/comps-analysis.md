# Comps Analysis — 可比公司分析

**触发词**：comps / 可比公司 / comparables

## Workflow

### Step 1: 同业列表
- 用户提供
- 参考 `../data/typical-stocks.md` 同主线标的
- `clients.web_search` 找可比

### Step 2: 拉数据
每只调 `scripts/fetchers/xueqiu.quote()`：
- PE (TTM) / PE (预测)
- PB
- PS
- EV/EBITDA（如有）
- 收入增速 / 净利润增速
- 毛利率 / 净利率

### Step 3: 表格
```
| 代码 | 公司 | PE | PB | ROE | 收入增速 | 净利润增速 |
```

### Step 4: 中位数 + 区间
- 同业中位数
- 当前标的 vs 中位数溢价/折价

### Step 5: 估值结论
- 当前标的合理估值区间
- 目标价

## 数据源

雪球 quote + `clients.web_search` 兜底

## 沙盒限制

雪球 f10/indicators（财务指标）已下线 → 部分指标 `clients.web_search` 补足。

## 输出形态

可比公司表 + 估值结论段。