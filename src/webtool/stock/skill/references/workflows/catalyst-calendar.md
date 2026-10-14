# Catalyst Calendar — 事件日历

**触发词**：catalyst / 事件日历 / 下周事件 / upcoming events

## Workflow

### Step 1: 时间窗口
默认未来 7 天（用户可指定 30 天）。

### Step 2: 政策事件
读 `../data/policy-tracking.md`，列出窗口内的：
- 政治局会议
- 国常会
- 央行 MLF / LPR
- 财政部专项债

### Step 3: 公司事件
调 `scripts/fetchers/cninfo.announcements(code, days=N)` 对持仓股跑。

### Step 4: 行业大会
`clients.web_search` 搜 "下周行业大会" / "下周展会"

### Step 5: 财报披露
- 中报披露密集期（7/15-8/31）
- 季报披露（4/30, 10/30）
- `clients.web_search` 搜 "下周财报披露"

### Step 6: 输出

```
| 日期 | 事件 | 影响板块 | 对应持仓 |
```

## 数据源

巨潮公告 + `clients.web_search`

## 输出形态

周事件日历表（4-7 列）。