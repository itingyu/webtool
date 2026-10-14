# DCF Model — DCF 估值

**触发词**：DCF / intrinsic value / 现金流折现

## Workflow

### Step 1: 财务预测（5-10 年）
- 收入增速
- 毛利率
- 运营成本
- Capex
- 营运资金变化

数据来源：历史财报 + 管理层指引 + 行业增速

### Step 2: WACC 计算
- 股权成本（CAPM）：Rf + β × (Rm - Rf)
- 债务成本（税后）
- 资本结构
- WACC = E/V × Re + D/V × Rd × (1-T)

### Step 3: 终值计算
- Gordon Growth: TV = FCF(n+1) / (WACC - g)
- 或退出倍数法

### Step 4: 现值折现
DCF = Σ FCF(t) / (1+WACC)^t + TV / (1+WACC)^n

### Step 5: 股权价值
EV → Equity = EV - Net Debt + Cash

### Step 6: 每股价值
Equity / Shares Outstanding

### Step 7: 敏感性分析

| WACC \ g | 1% | 2% | 3% |
|---|---|---|---|
| 8% | X | Y | Z |
| 9% | | | |
| 10% | | | |

## 数据源

历史财报（巨潮）+ 行业增速（`clients.web_search`）+ 雪球 quote（当前股价）

## 输出形态

DCF 模型表 + 目标价 + 敏感性分析。