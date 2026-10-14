# Single Analysis Card — 单股决策看板模板

```markdown
# [代码] [名称] — 单股研报

**数据时间**：YYYY-MM-DD HH:MM
**评级**：强买入 / 买入 / 持有 / 减仓 / 卖出（综合评分 X/100 = 技术 60 + 消息 30 + 宏观 10）
**行业**：申万一级 / 二级

## 公司画像

| 字段 | 值 |
|---|---|
| 公司全称 | 来自 `profile.full_name` |
| 法人代表 | 来自 `profile.legal_rep` |
| 成立 / 上市 | YYYY-MM-DD / YYYY-MM-DD |
| 注册地址 | 来自 `profile.address` |
| **官网** | [www.xxx.com](http://www.xxx.com) |
| 主营业务 | 来自 `profile.main_business`（摘关键 1-2 句） |
| 所属行业 | 证监会行业（来自 `profile.industry_csrc`） |
| 联系方式 | 电话 / 邮箱（可选） |

## 数据源快速跳转

> **不要在模板里硬编码具体链接**——链接由 `scripts/_common.py` 的 `stock_links(code)` 统一生成。
> agent 直接读 `r['links']` 字段拼接 Markdown 链接，不要自己拼字符串。

| 平台 | `r['links'][...]` 字段 | 链接模板 | 实测状态 |
|---|---|---|---|
| 东方财富个股 | `eastmoney_quote` | `https://quote.eastmoney.com/{market}{code}.html` | ✅ |
| 东方财富 F10 | `eastmoney_f10` | `https://emweb.securities.eastmoney.com/PC_HSF10/CompanySurvey/Index?type=web&code={market}{code}` | ✅ |
| 东方财富资金流向 | `eastmoney_flow` | `https://data.eastmoney.com/zjlx/detail/{code}.html` | ✅ |
| **东财公告聚合** | `eastmoney_notice` | `https://data.eastmoney.com/notices/stock/{code}.html` | ✅ |
| 雪球 | `xueqiu` | `https://xueqiu.com/S/{market}{code}` | ✅（SPA，浏览器渲染） |
| 同花顺个股 | `ths` | `https://m.10jqka.com.cn/stockpage/hs_{code}/` | ✅（必须用手机版）|
| 新浪财经 | `sina` | `https://finance.sina.com.cn/realstock/company/{market}{code}/nc.shtml` | ✅（自动跳 m 站）|

> `{market}` = `market_of(code).lower()`（`sz` / `sh` / `bj`），`{code}` = 6 位代码

### agent 输出示例

```markdown
## 数据源快速跳转

[东财个股]({r['links']['eastmoney_quote']}) · [东财 F10]({r['links']['eastmoney_f10']}) · [资金流向]({r['links']['eastmoney_flow']}) · [东财公告]({r['links']['eastmoney_notice']}) · [雪球]({r['links']['xueqiu']}) · [同花顺]({r['links']['ths']}) · [新浪]({r['links']['sina']})
```

### ⚠️ 已弃用链接（不要再用）

| 旧链接 | 问题 |
|---|---|
| `https://basic.10jqka.com.cn/{code}.html` | SPA 客户端未把数据写到 DOM，看到空壳 |
| `https://www.cninfo.com.cn/new/disclosure/stock?stockCode={code}` | 浏览器被劫持到 `webchat.cninfo.com.cn/home/notice` |

**巨潮公告 PDF** 仍用 `https://static.cninfo.com.cn/finalpage/{date}/{id}.PDF`（由 `cninfo.announcements()` API 返回，curl 200 + 浏览器 PDF 渲染正常）。

## 1. 估值与市值

| 指标 | 数值 |
|---|---|
| 当前价 | XX.XX 元 |
| 日涨跌幅 | X.XX% |
| 流通市值 | XXXX 亿 |
| PE (TTM) | XX |
| PB | X.X |
| 换手率 | X.X% |

## 2. 技术面

| 指标 | 数值 |
|---|---|
| 现价 / MA5 / MA10 / MA20 / MA60 | ... |
| 量比（5日/60日） | X.XX |
| ATR (14) | X.XX |
| 支撑位 / 阻力位 | X.XX / X.XX |
| 乖离率 MA5 | X.XX% |
| RSI (6) | XX.X |
| MACD HIST | X.XXXX |

## 3. 入场价位

| 类型 | 字段 | 价位 | 触发 |
|---|---|---|---|
| 突破买入 | `entry_breakout` | XX.XX | 放量突破 MA20 / 前高 + 板块共振 |
| 回踩低吸 | `entry_pullback` | XX.XX | 缩量回踩 MA10 / MA5 不破 |
| 观察位 | `entry_observing` | XX.XX | 现价附近，需等量能确认 |

## 4. 风控

- **硬止损**：XX.XX（`hard_stop`，全 skill 统一 **-7%**）
- **第一目标**：XX.XX（`target_1`）
- **第二目标**：XX.XX（`target_2`）

## 5. 近期公告
- [公告1 标题](url) (时间)
- [公告2 标题](url) (时间)

## 6. 新闻情绪
- 情绪分: X（`news_scorer.from_text()`，-100 ~ +100）| 标签: 强烈看多/看多/中性/看空/强烈看空
- 看多关键词 N / 看空关键词 M（`hits` 字段）

## 7. 风险
- [主要风险 1]
- [主要风险 2]

---
**免责声明**：本研报基于公开信息研究，不构成投资建议。
```

## 字段来源速查

| 字段 | 数据源 | 取值字段 |
|---|---|---|
| `market` | `single_analysis._market_of(code)` | `SH`/`SZ`/`BJ` |
| `profile.*` | `cninfo.company_intro(code)` | 见 `_extract_profile` |
| 行情/技术/评分 | `single_analysis.analyze(code[, news_items])` | `quote`/`technical`/`score`/`score_breakdown` |
| 三档入场价 / 止损目标 | `tech_indicators.technical_levels(df)` | `entry_breakout`/`entry_pullback`/`entry_observing`/`hard_stop`/`target_1`/`target_2` |
| 情绪分 | `sentiment.news_scorer.from_text(text)` | `score`/`hits`/`summary` |
| 公告 | `cninfo.announcements(code, days=N)` | `title`/`time`/`url` |

## 链接拼装规则

- **沪市**：`SH` + 代码（600/601/603/605/688/689）
- **深市**：`SZ` + 代码（000/002/003/300/301）
- **北交所**：`BJ` + 代码（8/4/920 开头）

> 注：东财个股页对**小写**前缀也兼容（`sz002414`），但 `雪球`/部分行情接口要求**大写**。agent 拼链接时**统一用小写**（`sz002414` / `sh600519`），兼容性最好。