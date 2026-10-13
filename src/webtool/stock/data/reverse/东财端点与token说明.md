# 东财端点体系与 token 说明

> 逆向自 akshare 源码 + 2026-10-13 沙盒实测

## 一、两个 datacenter 端点，行为不同

| 端点 | 版本 | 参数体系 | 沙盒实测 |
|---|---|---|---|
| `/api/data/v1/get` | v1 | `reportName` + `columns` + `pageSize` | ✅ 可用（171 处调用） |
| `/api/data/get` | 旧版 | `type` + `sty` + `p` + `pss` | ✅ 可用（2 处调用） |

**旧版参数**：

| 参数 | 说明 |
|---|---|
| `type` | 报表标识（对应 v1 的 `reportName`） |
| `sty` | 字段选择，`ALL` = 全部 |
| `p` / `pss` | 页码 / 每页条数 |
| `st` / `sr` | 排序字段 / 方向 |
| `source` | 业务来源标识 |
| `client` | `WEB` |
| `ut` | 令牌 |
| `token` | 令牌（旧版另一套） |

实测：`/api/data/get?type=RPT_IF_BILLBOARD_TD&sty=ALL&p=1&pss=200&source=IFBILLBOARD&client=WEB`
**不带 ut 返回 500 条正常数据**，共 327 页。

---

## 二、三个固定 token（源码硬编码）

| token | 用途 | 出现端点 |
|---|---|---|
| `894050c76af8597a853f5b408b759f5d` | 通用 v1 | `RPTA_WEB_ZDHT_LIST`、`RPT_BOND_CB_LIST` 等 |
| `b2884a393a59ad64002292a3e90d46a5` | 期权龙虎榜 | `/api/data/get` `RPT_IF_BILLBOARD_TD` |
| `13697a1cc677c8bfa9a496437bfef419` | push2 行情 | 自建客户端使用（本项目手册 §十一） |

> 这些 token 在 akshare 源码中硬编码，是长期稳定的公开令牌，非用户凭证。

---

## 三、`companyType` — F10 接口的必备参数

东财新版 F10 接口（`PC_HSF10/NewFinanceAnalysis/*`）**必须**带 `companyType`，否则返回 1718 字节「无F10资料」占位符。

该值需先请求 HTML 页面提取：

```
GET https://emweb.securities.eastmoney.com/PC_HSF10/NewFinanceAnalysis/Index
  params: type=web, code={symbol}.lower()
→ BeautifulSoup: soup.find(id="hidctype")["value"]
```

实测：`SH600519` → `companyType=4`（通用）

> 这解决了自建客户端 `em_f10_*` 偶发返回占位符的问题——**未做 companyType 探测**。

---

## 四、`quoteColumns` — 行情字段注入

部分接口（如 `RPT_MUTUAL_QUOTA`）通过 `quoteColumns` 注入实时行情字段，语法：

```
f104~07~BOARD_CODE          → BOARD_CODE 记录的 f104 字段
f3~03~INDEX_CODE~INDEX_f3  → INDEX_CODE 关联记录的涨跌幅
netBuyAmt~07~BOARD_CODE     → 自定义字段名
```

分隔符含义：`~` 分隔配置项，`07` 为字段类型，`03` 为关联类型。

> 自建客户端未使用此机制，这是东财接口可挖的深度能力。

---

## 五、沙盒可用性结论（2026-10-13 实测）

| 端点 | 状态 |
|---|---|
| `datacenter-web.eastmoney.com/api/data/v1/get` | ✅ 正常 |
| `datacenter-web.eastmoney.com/api/data/get` | ✅ 正常 |
| `emweb.securities.eastmoney.com/PC_HSF10/NewFinanceAnalysis/*` | ✅ 需 companyType |
| `emweb.eastmoney.com/PC_HSF10/*/PageAjax` | ✅ 正常 |
| `push2.eastmoney.com/api/qt/stock/get` | ✅ 加 ut 可用（A股） |
| `push2.eastmoney.com/api/qt/clist/get` | ❌ IP ban（沙盒） |
| `push2his.eastmoney.com/api/qt/stock/kline/get` | ✅ 加 ut 可用 |
