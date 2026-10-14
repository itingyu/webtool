# Deal Tracker — 交易追踪

**触发词**：deal tracker / pipeline / 投行 pipeline / IPO 跟踪

## Workflow

### Step 1: 数据源
- `clients.web_search` 搜 "IPO 招股" "并购重组公告"
- 巨潮 announcements 拉公告
- 雪球 daily 新闻

### Step 2: 分类记录

| 类型 | 公司 | 时间 | 进度 | 规模 | 主办 |
|---|---|---|---|---|---|
| IPO | XX | YYYY-MM-DD | 已受理 | 10 亿 | 中信 |
| 并购 | YY | | 进行中 | | |
| 重组 | ZZ | | 完成 | | |

### Step 3: 进度跟踪
- IPO：受理 → 问询 → 注册 → 发行 → 上市
- 并购：筹划 → 董事会 → 股东大会 → 证监会 → 交割

### Step 4: 关联标的
- 券商（投行业务受益）
- 被收购方（套利）
- 同业（可比）

## 输出形态

Deal pipeline 表格 + 关联标的列表。

## 数据源

巨潮 + `clients.web_search`