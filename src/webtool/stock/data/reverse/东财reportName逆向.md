# 东财 datacenter-web 接口逆向

> 覆盖 122 个 reportName | 参数与字段均摘自源码，非推测

统一端点：`GET https://datacenter-web.eastmoney.com/api/data/v1/get`

通用响应：`data_json["result"]["data"]` 取记录，`data_json["result"]["pages"]` 取总页数。


---

## 1. `PRT_BLOCKTRADE_MARKET_STA`

- **akshare 入口**: `stock_dzjy_sctj()`
- **源码**: `stock/stock_dzjy_em.py:12`
- **用途**: 东方财富网-数据中心-大宗交易-市场统计

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `sortColumns` | `"TRADE_DATE"` | 排序字段 |
| `sortTypes` | `"-1"` | -1降序 1升序 |
| `pageSize` | `"500"` | 每页条数 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `reportName` | `"PRT_BLOCKTRADE_MARKET_STA"` | 数据集标识 |
| `columns` | `"TRADE_DATE,SZ_INDEX,SZ_CHANGE_RATE,BLOCKTRADE_DEAL_AMT,PREMIUM_DEAL_AMT,"` | 返回字段，ALL=全部 |
| `source` | `"WEB"` | 客户端标识 |
| `client` | `"WEB"` | 客户端标识 |

**返回字段**（按列序，共 9 列）

| 列序 | 字段含义 |
|---|---|
| 0 | 序号 |
| 1 | 交易日期 |
| 2 | 上证指数 |
| 3 | 上证指数涨跌幅 |
| 4 | 大宗交易成交总额 |
| 5 | 溢价成交总额 |
| 6 | 溢价成交总额占比 |
| 7 | 折价成交总额 |
| 8 | 折价成交总额占比 |

---

## 2. `PRT_MUTUAL_ORG_STA`

- **akshare 入口**: `stock_hsgt_institution_statistics_em(market: str = "北向持股",
    start_date: str = "20220601",
    end_date: str = "20220609",)`
- **源码**: `stock_feature/stock_hsgt_em.py:777`
- **用途**: 东方财富网-数据中心-沪深港通-沪深港通持股-每日机构统计

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `sortColumns` | `"HOLD_DATE"` | 排序字段 |
| `sortTypes` | `"-1"` | -1降序 1升序 |
| `pageSize` | `"500"` | 每页条数 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `reportName` | `"PRT_MUTUAL_ORG_STA"` | 数据集标识 |
| `columns` | `"ALL"` | 返回字段，ALL=全部 |
| `source` | `"WEB"` | 客户端标识 |
| `client` | `"WEB"` | 客户端标识 |
| `filter` | `f"""(MARKET_TYPE="S")(HOLD_DATE>='{start_date}')(HOLD_DATE<='{end_date}')"""` | 过滤表达式 |

**返回字段**（按列序，共 18 列）

| 列序 | 字段含义 |
|---|---|
| 0 | 持股日期 |
| 2 | 持股只数 |
| 4 | 持股市值 |
| 5 | 持股市值变化-1日 |
| 6 | 持股市值变化-5日 |
| 7 | 持股市值变化-10日 |
| 9 | 机构名称 |

---

## 3. `RPTA_APP_ACCUMDETAILS`

- **akshare 入口**: `_get_page_num_gpzy_market_pledge_ratio_detail(filter: str = None)`
- **源码**: `stock_feature/stock_gpzy_em.py:169`
- **用途**: 东方财富网-数据中心-特色数据-股权质押-重要股东股权质押明细

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `sortColumns` | `"NOTICE_DATE"` | 排序字段 |
| `sortTypes` | `"-1"` | -1降序 1升序 |
| `pageSize` | `"500"` | 每页条数 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `reportName` | `"RPTA_APP_ACCUMDETAILS"` | 数据集标识 |
| `columns` | `"ALL"` | 返回字段，ALL=全部 |
| `quoteColumns` | `""` | 行情字段注入 |
| `source` | `"WEB"` | 客户端标识 |
| `client` | `"WEB"` | 客户端标识 |
| `filter` | `filter` | 过滤表达式 |

---

## 4. `RPTA_APP_IPOAPPLY`

- **akshare 入口**: `stock_dxsyl_em()`
- **源码**: `stock_feature/stock_dxsyl_em.py:17`
- **用途**: 东方财富网-数据中心-新股申购-打新收益率

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `sortColumns` | `"LISTING_DATE,SECURITY_CODE"` | 排序字段 |
| `sortTypes` | `"-1,-1"` | -1降序 1升序 |
| `pageSize` | `"5000"` | 每页条数 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `reportName` | `"RPTA_APP_IPOAPPLY"` | 数据集标识 |
| `quoteColumns` | `"f2~01~SECURITY_CODE,f14~01~SECURITY_CODE"` | 行情字段注入 |
| `quoteType` | `"0"` |  |
| `columns` | `"ALL"` | 返回字段，ALL=全部 |
| `source` | `"WEB"` | 客户端标识 |
| `client` | `"WEB"` | 客户端标识 |
| `filter` | `"""((APPLY_DATE>'2010-01-01')(|@APPLY_DATE="NULL"))((LISTING_DATE>'2010-01-01')(|@LISTING_DATE="NULL` | 过滤表达式 |

**字段重命名**（英文原始名 → 中文含义）

| 原始字段 | 含义 |
|---|---|
| `index` | 序号 |
| `SECURITY_CODE` | 股票代码 |
| `f14` | 股票简称 |
| `ISSUE_PRICE` | 发行价 |
| `LATELY_PRICE` | 最新价 |
| `ONLINE_ISSUE_LWR` | 网上-发行中签率 |
| `ONLINE_VA_SHARES` | 网上-有效申购股数 |
| `ONLINE_VA_NUM` | 网上-有效申购户数 |
| `ONLINE_ES_MULTIPLE` | 网上-超额认购倍数 |
| `OFFLINE_VAP_RATIO` | 网下-配售中签率 |
| `OFFLINE_VATS` | 网下-有效申购股数 |
| `OFFLINE_VAP_OBJECT` | 网下-有效申购户数 |
| `OFFLINE_VAS_MULTIPLE` | 网下-配售认购倍数 |
| `ISSUE_NUM` | 总发行数量 |
| `LD_OPEN_PREMIUM` | 开盘溢价 |
| `LD_CLOSE_CHANGE` | 首日涨幅 |
| `LISTING_DATE` | 上市日期 |

---

## 5. `RPTA_WEB_GETHGLIST_NEW`

- **akshare 入口**: `stock_repurchase_em()`
- **源码**: `stock/stock_repurchase_em.py:13`
- **用途**: 东方财富网-数据中心-股票回购-股票回购数据

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `sortColumns` | `"UPD,DIM_DATE,DIM_SCODE"` | 排序字段 |
| `sortTypes` | `"-1,-1,-1"` | -1降序 1升序 |
| `pageSize` | `"500"` | 每页条数 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `reportName` | `"RPTA_WEB_GETHGLIST_NEW"` | 数据集标识 |
| `columns` | `"ALL"` | 返回字段，ALL=全部 |
| `source` | `"WEB"` | 客户端标识 |

---

## 6. `RPTA_WEB_MARGIN_DAILYTRADE`

- **akshare 入口**: `stock_margin_account_info()`
- **源码**: `stock_feature/stock_margin_em.py:14`
- **用途**: 东方财富网-数据中心-融资融券-融资融券账户统计-两融账户信息

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `reportName` | `"RPTA_WEB_MARGIN_DAILYTRADE"` | 数据集标识 |
| `columns` | `"ALL"` | 返回字段，ALL=全部 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `pageSize` | `"500"` | 每页条数 |
| `sortColumns` | `"STATISTICS_DATE"` | 排序字段 |
| `sortTypes` | `"-1"` | -1降序 1升序 |
| `p` | `"1"` |  |
| `pageNo` | `"1"` |  |
| `pageNum` | `"1"` |  |

**字段重命名**（英文原始名 → 中文含义）

| 原始字段 | 含义 |
|---|---|
| `STATISTICS_DATE` | 日期 |
| `FIN_BALANCE` | 融资余额 |
| `LOAN_BALANCE` | 融券余额 |
| `FIN_BUY_AMT` | 融资买入额 |
| `LOAN_SELL_AMT` | 融券卖出额 |
| `SECURITY_ORG_NUM` | 证券公司数量 |
| `OPERATEDEPT_NUM` | 营业部数量 |
| `PERSONAL_INVESTOR_NUM` | 个人投资者数量 |
| `ORG_INVESTOR_NUM` | 机构投资者数量 |
| `INVESTOR_NUM` | 参与交易的投资者数量 |
| `MARGINLIAB_INVESTOR_NUM` | 有融资融券负债的投资者数量 |
| `TOTAL_GUARANTEE` | 担保物总价值 |
| `AVG_GUARANTEE_RATIO` | 平均维持担保比例 |

---

## 7. `RPTA_WEB_RATE`

- **akshare 入口**: `macro_china_lpr()`
- **源码**: `economic/macro_china.py:1011`
- **用途**: LPR品种详细数据

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `reportName` | `"RPTA_WEB_RATE"` | 数据集标识 |
| `columns` | `"ALL"` | 返回字段，ALL=全部 |
| `sortColumns` | `"TRADE_DATE"` | 排序字段 |
| `sortTypes` | `"-1"` | -1降序 1升序 |
| `token` | `"894050c76af8597a853f5b408b759f5d"` | 固定令牌 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `pageSize` | `"500"` | 每页条数 |
| `p` | `"1"` |  |
| `pageNo` | `"1"` |  |
| `pageNum` | `"1"` |  |

---

## 8. `RPTA_WEB_YJ_BD`

- **akshare 入口**: `energy_oil_hist()`
- **源码**: `energy/energy_oil_em.py:12`
- **用途**: 汽柴油历史调价信息

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `reportName` | `"RPTA_WEB_YJ_BD"` | 数据集标识 |
| `columns` | `"ALL"` | 返回字段，ALL=全部 |
| `sortColumns` | `"dim_date"` | 排序字段 |
| `sortTypes` | `"-1"` | -1降序 1升序 |
| `token` | `"894050c76af8597a853f5b408b759f5d"` | 固定令牌 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `pageSize` | `"1000"` | 每页条数 |
| `source` | `"WEB"` | 客户端标识 |
| `p` | `"1"` |  |
| `pageNo` | `"1"` |  |
| `pageNum` | `"1"` |  |

---

## 9. `RPTA_WEB_YJ_JH`

- **akshare 入口**: `energy_oil_detail(date: str = "20220517")`
- **源码**: `energy/energy_oil_em.py:47`
- **用途**: 全国各地区的汽油和柴油油价

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `reportName` | `"RPTA_WEB_YJ_JH"` | 数据集标识 |
| `columns` | `"ALL"` | 返回字段，ALL=全部 |
| `filter` | `f"(dim_date='{date}')"` | 过滤表达式 |
| `sortColumns` | `"cityname"` | 排序字段 |
| `sortTypes` | `"1"` | -1降序 1升序 |
| `token` | `"894050c76af8597a853f5b408b759f5d"` | 固定令牌 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `pageSize` | `"1000"` | 每页条数 |
| `source` | `"WEB"` | 客户端标识 |

**返回字段**（按列序，共 15 列）

| 列序 | 字段含义 |
|---|---|
| 0 | 日期 |
| 1 | 地区 |
| 2 | V_0 |
| 3 | V_92 |
| 4 | V_95 |
| 5 | V_89 |
| 6 | ZDE_0 |
| 7 | ZDE_92 |
| 8 | ZDE_95 |
| 9 | ZDE_89 |
| 10 | QE_0 |
| 11 | QE_92 |
| 12 | QE_95 |
| 13 | QE_89 |
| 14 | 首字母 |

---

## 10. `RPTA_WEB_ZDHT_LIST`

- **akshare 入口**: `stock_zdhtmx_em(start_date: str = "20200819", end_date: str = "20230819")`
- **源码**: `stock_feature/stock_zdhtmx_em.py:13`
- **用途**: 东方财富网-数据中心-重大合同-重大合同明细

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `sortColumns` | `"DIM_RDATE"` | 排序字段 |
| `sortTypes` | `"-1"` | -1降序 1升序 |
| `pageSize` | `"500"` | 每页条数 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `columns` | `"ALL"` | 返回字段，ALL=全部 |
| `token` | `"894050c76af8597a853f5b408b759f5d"` | 固定令牌 |
| `reportName` | `"RPTA_WEB_ZDHT_LIST"` | 数据集标识 |
| `filter` | `f"""(DIM_RDATE>='{"-".join([start_date[:4], start_date[4:6], start_date[6:]])}')` | 过滤表达式 |

**字段重命名**（英文原始名 → 中文含义）

| 原始字段 | 含义 |
|---|---|
| `index` | 序号 |
| `DIM_SCODE` | - |
| `CONTENTS` | - |
| `CONTRACTNAME` | 合同名称 |
| `CONTRACTTYPE` | - |
| `COUNTERPARTY` | 其他签署方 |
| `COUNTERPARTYREL` | - |
| `ISABOLISHED` | - |
| `DIM_RDATE` | 公告日期 |
| `REMARK` | - |
| `SIGNATORY` | 签署主体 |
| `SIGNATORYREL` | 与上市公司关系 |
| `SIGNDATE` | 签署日期 |
| `SIGNEFFECT` | - |
| `UPDATEDATE` | - |
| `YEAR` | - |
| `AMOUNTS` | 合同金额 |
| `SECURITYCODE` | 股票代码 |
| `SECURITYSHORTNAME` | 股票简称 |
| `CONTRACTTYPENAME` | 合同类型 |
| `SIGNATORYRELNAME` | 签署主体-与上市公司关系 |
| `COUNTERPARTYRELNAME` | 其他签署方-与上市公司关系 |
| `SNDYYSR` | 上年度营业收入 |
| `OPERATEREVE` | 最新财务报表的营业收入 |
| `RCHANGE1DC` | - |
| `RCHANGE20DC` | - |
| `ZSNDYYSRBL` | 占上年度营业收入比例 |

---

## 11. `RPT_BILLBOARD_TRADEALL`

- **akshare 入口**: `stock_lhb_stock_statistic_em(symbol: str = "近一月")`
- **源码**: `stock_feature/stock_lhb_em.py:136`
- **用途**: 东方财富网-数据中心-龙虎榜单-个股上榜统计

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `sortColumns` | `"BILLBOARD_TIMES,LATEST_TDATE,SECURITY_CODE"` | 排序字段 |
| `sortTypes` | `"-1,-1,1"` | -1降序 1升序 |
| `pageSize` | `"5000"` | 每页条数 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `reportName` | `"RPT_BILLBOARD_TRADEALL"` | 数据集标识 |
| `columns` | `"ALL"` | 返回字段，ALL=全部 |
| `source` | `"WEB"` | 客户端标识 |
| `client` | `"WEB"` | 客户端标识 |
| `filter` | `f'(STATISTICS_CYCLE="{symbol_map[symbol]}")'` | 过滤表达式 |

**返回字段**（按列序，共 25 列）

| 列序 | 字段含义 |
|---|---|
| 0 | 序号 |
| 2 | 代码 |
| 3 | 最近上榜日 |
| 4 | 名称 |
| 5 | 近1个月涨跌幅 |
| 6 | 近3个月涨跌幅 |
| 7 | 近6个月涨跌幅 |
| 8 | 近1年涨跌幅 |
| 9 | 涨跌幅 |
| 10 | 收盘价 |
| 12 | 龙虎榜总成交额 |
| 13 | 龙虎榜净买额 |
| 16 | 机构买入净额 |
| 17 | 上榜次数 |
| 18 | 龙虎榜买入额 |
| 19 | 龙虎榜卖出额 |
| 20 | 机构买入总额 |
| 21 | 机构卖出总额 |
| 22 | 买方机构次数 |
| 23 | 卖方机构次数 |

---

## 12. `RPT_BLOCKTRADE_ACSTA`

- **akshare 入口**: `stock_dzjy_hygtj(symbol: str = "近三月")`
- **源码**: `stock/stock_dzjy_em.py:294`
- **用途**: 东方财富网-数据中心-大宗交易-活跃 A 股统计

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `sortColumns` | `"DEAL_NUM,SECURITY_CODE"` | 排序字段 |
| `sortTypes` | `"-1,-1"` | -1降序 1升序 |
| `pageSize` | `"5000"` | 每页条数 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `reportName` | `"RPT_BLOCKTRADE_ACSTA"` | 数据集标识 |
| `columns` | `"SECURITY_CODE,SECUCODE,SECURITY_NAME_ABBR,CLOSE_PRICE,CHANGE_RATE,TRADE_DATE,"` | 返回字段，ALL=全部 |
| `source` | `"WEB"` | 客户端标识 |
| `client` | `"WEB"` | 客户端标识 |
| `filter` | `f"(DATE_TYPE_CODE={period_map[symbol]})"` | 过滤表达式 |

**返回字段**（按列序，共 18 列）

| 列序 | 字段含义 |
|---|---|
| 0 | 序号 |
| 1 | 证券代码 |
| 3 | 证券简称 |
| 4 | 最新价 |
| 5 | 涨跌幅 |
| 6 | 最近上榜日 |
| 7 | 总成交额 |
| 8 | 折溢率 |
| 9 | 成交总额/流通市值 |
| 10 | 上榜次数-总计 |
| 11 | 上榜次数-溢价 |
| 12 | 上榜次数-折价 |
| 13 | 上榜日后平均涨跌幅-1日 |
| 14 | 上榜日后平均涨跌幅-5日 |
| 15 | 上榜日后平均涨跌幅-10日 |
| 16 | 上榜日后平均涨跌幅-20日 |

---

## 13. `RPT_BLOCKTRADE_OPERATEDEPTSTATISTICS`

- **akshare 入口**: `stock_dzjy_hyyybtj(symbol: str = "近3日")`
- **源码**: `stock/stock_dzjy_em.py:401`
- **用途**: 东方财富网-数据中心-大宗交易-活跃营业部统计

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `sortColumns` | `"BUYER_NUM,TOTAL_BUYAMT"` | 排序字段 |
| `sortTypes` | `"-1,-1"` | -1降序 1升序 |
| `pageSize` | `"5000"` | 每页条数 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `reportName` | `"RPT_BLOCKTRADE_OPERATEDEPTSTATISTICS"` | 数据集标识 |
| `columns` | `"OPERATEDEPT_CODE,OPERATEDEPT_NAME,ONLIST_DATE,STOCK_DETAILS,"` | 返回字段，ALL=全部 |
| `source` | `"WEB"` | 客户端标识 |
| `client` | `"WEB"` | 客户端标识 |
| `filter` | `f"(N_DATE=-{period_map[symbol]})"` | 过滤表达式 |

**返回字段**（按列序，共 11 列）

| 列序 | 字段含义 |
|---|---|
| 0 | 序号 |
| 2 | 营业部名称 |
| 3 | 最近上榜日 |
| 4 | 买入的股票 |
| 5 | 次数总计-买入 |
| 6 | 次数总计-卖出 |
| 7 | 成交金额统计-买入 |
| 8 | 成交金额统计-卖出 |
| 9 | 成交金额统计-净买入额 |

---

## 14. `RPT_BLOCKTRADE_OPERATEDEPT_RANK`

- **akshare 入口**: `stock_dzjy_yybph(symbol: str = "近三月")`
- **源码**: `stock/stock_dzjy_em.py:483`
- **用途**: 东方财富网-数据中心-大宗交易-营业部排行

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `sortColumns` | `"D5_BUYER_NUM,D1_AVERAGE_INCREASE"` | 排序字段 |
| `sortTypes` | `"-1,-1"` | -1降序 1升序 |
| `pageSize` | `"5000"` | 每页条数 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `reportName` | `"RPT_BLOCKTRADE_OPERATEDEPT_RANK"` | 数据集标识 |
| `columns` | `"OPERATEDEPT_CODE,OPERATEDEPT_NAME,D1_BUYER_NUM,D1_AVERAGE_INCREASE,"` | 返回字段，ALL=全部 |
| `source` | `"WEB"` | 客户端标识 |
| `client` | `"WEB"` | 客户端标识 |
| `filter` | `f"(N_DATE=-{period_map[symbol]})"` | 过滤表达式 |

**返回字段**（按列序，共 17 列）

| 列序 | 字段含义 |
|---|---|
| 0 | 序号 |
| 2 | 营业部名称 |
| 3 | 上榜后1天-买入次数 |
| 4 | 上榜后1天-平均涨幅 |
| 5 | 上榜后1天-上涨概率 |
| 6 | 上榜后5天-买入次数 |
| 7 | 上榜后5天-平均涨幅 |
| 8 | 上榜后5天-上涨概率 |
| 9 | 上榜后10天-买入次数 |
| 10 | 上榜后10天-平均涨幅 |
| 11 | 上榜后10天-上涨概率 |
| 12 | 上榜后20天-买入次数 |
| 13 | 上榜后20天-平均涨幅 |
| 14 | 上榜后20天-上涨概率 |

---

## 15. `RPT_BLOCKTRADE_STA`

- **akshare 入口**: `stock_dzjy_mrtj(start_date: str = "20220105", end_date: str = "20220105")`
- **源码**: `stock/stock_dzjy_em.py:212`
- **用途**: 东方财富网-数据中心-大宗交易-每日统计

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `sortColumns` | `"TURNOVERRATE"` | 排序字段 |
| `sortTypes` | `"-1"` | -1降序 1升序 |
| `pageSize` | `"5000"` | 每页条数 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `reportName` | `"RPT_BLOCKTRADE_STA"` | 数据集标识 |
| `columns` | `"TRADE_DATE,SECURITY_CODE,SECUCODE,SECURITY_NAME_ABBR,CHANGE_RATE,"` | 返回字段，ALL=全部 |
| `source` | `"WEB"` | 客户端标识 |
| `client` | `"WEB"` | 客户端标识 |
| `filter` | `f"(TRADE_DATE>='{'-'.join([start_date[:4], start_date[4:6], start_date[6:]])}')(TRADE_DATE<="` | 过滤表达式 |

**返回字段**（按列序，共 17 列）

| 列序 | 字段含义 |
|---|---|
| 0 | 序号 |
| 1 | 交易日期 |
| 2 | 证券代码 |
| 4 | 证券简称 |
| 5 | 涨跌幅 |
| 6 | 收盘价 |
| 7 | 成交价 |
| 8 | 折溢率 |
| 9 | 成交笔数 |
| 10 | 成交总量 |
| 11 | 成交总额 |
| 12 | 成交总额/流通市值 |

---

## 16. `RPT_BOND_CB_LIST`

- **akshare 入口**: `bond_zh_cov()`
- **源码**: `bond/bond_zh_cov.py:308`
- **用途**: 东方财富网-数据中心-新股数据-可转债数据

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `sortColumns` | `"PUBLIC_START_DATE"` | 排序字段 |
| `sortTypes` | `"-1"` | -1降序 1升序 |
| `pageSize` | `"500"` | 每页条数 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `reportName` | `"RPT_BOND_CB_LIST"` | 数据集标识 |
| `columns` | `"ALL"` | 返回字段，ALL=全部 |
| `quoteColumns` | `"f2~01~CONVERT_STOCK_CODE~CONVERT_STOCK_PRICE,"` | 行情字段注入 |
| `source` | `"WEB"` | 客户端标识 |
| `client` | `"WEB"` | 客户端标识 |

**返回字段**（按列序，共 72 列）

| 列序 | 字段含义 |
|---|---|
| 0 | 债券代码 |
| 3 | 债券简称 |
| 5 | 上市时间 |
| 6 | 正股代码 |
| 8 | 信用评级 |
| 16 | 发行规模 |
| 17 | 申购上限 |
| 31 | 申购代码 |
| 33 | 申购日期 |
| 36 | 中签号发布日 |
| 37 | 原股东配售-股权登记日 |
| 38 | 正股简称 |
| 39 | 原股东配售-每股配售额 |
| 41 | 中签率 |
| 48 | 正股价 |
| 49 | 转股价 |
| 50 | 转股价值 |
| 51 | 债现价 |
| 52 | 转股溢价率 |

---

## 17. `RPT_COOPFREEHOLDER`

- **akshare 入口**: `stock_gdfx_free_holding_teamwork_em(symbol: str = "社保")`
- **源码**: `stock_feature/stock_gdfx_em.py:891`
- **用途**: 东方财富网-数据中心-股东分析-股东协同-十大流通股东

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `sortColumns` | `"COOPERAT_NUM,HOLDER_NEW,COOPERAT_HOLDER_NEW"` | 排序字段 |
| `sortTypes` | `"-1,-1,-1"` | -1降序 1升序 |
| `pageSize` | `"500"` | 每页条数 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `reportName` | `"RPT_COOPFREEHOLDER"` | 数据集标识 |
| `columns` | `"ALL"` | 返回字段，ALL=全部 |
| `source` | `"WEB"` | 客户端标识 |
| `client` | `"WEB"` | 客户端标识 |

**返回字段**（按列序，共 10 列）

| 列序 | 字段含义 |
|---|---|
| 0 | 序号 |
| 2 | 股东名称 |
| 3 | 股东类型 |
| 5 | 协同股东名称 |
| 6 | 协同股东类型 |
| 7 | 协同次数 |
| 9 | 个股详情 |

---

## 18. `RPT_COOPFREEHOLDERS_ANALYSIS`

- **akshare 入口**: `stock_gdfx_free_holding_statistics_em(date: str = "20210630",)`
- **源码**: `stock_feature/stock_gdfx_em.py:14`
- **用途**: 东方财富网-数据中心-股东分析-股东持股统计-十大流通股东

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `sortColumns` | `"STATISTICS_TIMES,COOPERATION_HOLDER_MARK"` | 排序字段 |
| `sortTypes` | `"-1,-1"` | -1降序 1升序 |
| `pageSize` | `"500"` | 每页条数 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `reportName` | `"RPT_COOPFREEHOLDERS_ANALYSIS"` | 数据集标识 |
| `columns` | `"ALL"` | 返回字段，ALL=全部 |
| `source` | `"WEB"` | 客户端标识 |
| `client` | `"WEB"` | 客户端标识 |
| `filter` | `f"""(HOLDNUM_CHANGE_TYPE="001")(END_DATE='{"-".join([date[:4], date[4:6], date[6:]])}')"""` | 过滤表达式 |

**返回字段**（按列序，共 17 列）

| 列序 | 字段含义 |
|---|---|
| 0 | 序号 |
| 3 | 股东名称 |
| 4 | 股东类型 |
| 6 | 统计次数 |
| 7 | 公告日后涨幅统计-10个交易日-平均涨幅 |
| 8 | 公告日后涨幅统计-10个交易日-最大涨幅 |
| 9 | 公告日后涨幅统计-10个交易日-最小涨幅 |
| 10 | 公告日后涨幅统计-30个交易日-平均涨幅 |
| 11 | 公告日后涨幅统计-30个交易日-最大涨幅 |
| 12 | 公告日后涨幅统计-30个交易日-最小涨幅 |
| 13 | 公告日后涨幅统计-60个交易日-平均涨幅 |
| 14 | 公告日后涨幅统计-60个交易日-最大涨幅 |
| 15 | 公告日后涨幅统计-60个交易日-最小涨幅 |
| 16 | 持有个股 |

---

## 19. `RPT_COOPHOLDERS_ANALYSIS`

- **akshare 入口**: `stock_gdfx_holding_statistics_em(date: str = "20210930")`
- **源码**: `stock_feature/stock_gdfx_em.py:118`
- **用途**: 东方财富网-数据中心-股东分析-股东持股统计-十大股东

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `sortColumns` | `"STATISTICS_TIMES,COOPERATION_HOLDER_MARK"` | 排序字段 |
| `sortTypes` | `"-1,-1"` | -1降序 1升序 |
| `pageSize` | `"500"` | 每页条数 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `reportName` | `"RPT_COOPHOLDERS_ANALYSIS"` | 数据集标识 |
| `columns` | `"ALL"` | 返回字段，ALL=全部 |
| `source` | `"WEB"` | 客户端标识 |
| `client` | `"WEB"` | 客户端标识 |
| `filter` | `f"""(HOLDNUM_CHANGE_TYPE="001")(END_DATE='{"-".join([date[:4], date[4:6], date[6:]])}')"""` | 过滤表达式 |

**返回字段**（按列序，共 17 列）

| 列序 | 字段含义 |
|---|---|
| 0 | 序号 |
| 3 | 股东名称 |
| 4 | 股东类型 |
| 6 | 统计次数 |
| 7 | 公告日后涨幅统计-10个交易日-平均涨幅 |
| 8 | 公告日后涨幅统计-10个交易日-最大涨幅 |
| 9 | 公告日后涨幅统计-10个交易日-最小涨幅 |
| 10 | 公告日后涨幅统计-30个交易日-平均涨幅 |
| 11 | 公告日后涨幅统计-30个交易日-最大涨幅 |
| 12 | 公告日后涨幅统计-30个交易日-最小涨幅 |
| 13 | 公告日后涨幅统计-60个交易日-平均涨幅 |
| 14 | 公告日后涨幅统计-60个交易日-最大涨幅 |
| 15 | 公告日后涨幅统计-60个交易日-最小涨幅 |
| 16 | 持有个股 |

---

## 20. `RPT_CSDC_INDUSTRY_STATISTICS`

- **akshare 入口**: `stock_gpzy_industry_data_em()`
- **源码**: `stock_feature/stock_gpzy_em.py:449`
- **用途**: 东方财富网-数据中心-特色数据-股权质押-上市公司质押比例-行业数据

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `sortColumns` | `"AVERAGE_PLEDGE_RATIO"` | 排序字段 |
| `sortTypes` | `"-1"` | -1降序 1升序 |
| `pageSize` | `"500"` | 每页条数 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `reportName` | `"RPT_CSDC_INDUSTRY_STATISTICS"` | 数据集标识 |
| `columns` | `"INDUSTRY_CODE,INDUSTRY,TRADE_DATE,AVERAGE_PLEDGE_RATIO,ORG_NUM,PLEDGE_TOTAL_NUM,"` | 返回字段，ALL=全部 |
| `quoteColumns` | `""` | 行情字段注入 |
| `source` | `"WEB"` | 客户端标识 |
| `client` | `"WEB"` | 客户端标识 |

**返回字段**（按列序，共 9 列）

| 列序 | 字段含义 |
|---|---|
| 0 | 序号 |
| 2 | 行业 |
| 3 | 统计时间 |
| 4 | 平均质押比例 |
| 5 | 公司家数 |
| 6 | 质押总笔数 |
| 7 | 质押总股本 |
| 8 | 最新质押市值 |

---

## 21. `RPT_CSDC_LIST`

- **akshare 入口**: `stock_gpzy_pledge_ratio_em(date: str = "20240906")`
- **源码**: `stock_feature/stock_gpzy_em.py:87`
- **用途**: 东方财富网-数据中心-特色数据-股权质押-上市公司质押比例

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `sortColumns` | `"PLEDGE_RATIO"` | 排序字段 |
| `sortTypes` | `"-1"` | -1降序 1升序 |
| `pageSize` | `"500"` | 每页条数 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `reportName` | `"RPT_CSDC_LIST"` | 数据集标识 |
| `columns` | `"ALL"` | 返回字段，ALL=全部 |
| `quoteColumns` | `""` | 行情字段注入 |
| `source` | `"WEB"` | 客户端标识 |
| `client` | `"WEB"` | 客户端标识 |
| `filter` | `f"(TRADE_DATE='{trade_date}')"` | 过滤表达式 |

**返回字段**（按列序，共 15 列）

| 列序 | 字段含义 |
|---|---|
| 0 | 序号 |
| 2 | 股票代码 |
| 3 | 股票简称 |
| 4 | 交易日期 |
| 5 | 质押比例 |
| 6 | 质押股数 |
| 7 | 质押笔数 |
| 8 | 无限售股质押数 |
| 9 | 限售股质押数 |
| 10 | 质押市值 |
| 11 | 所属行业 |
| 12 | 近一年涨跌幅 |
| 13 | 所属行业代码 |

---

## 22. `RPT_CSDC_STATISTICS`

- **akshare 入口**: `stock_gpzy_profile_em()`
- **源码**: `stock_feature/stock_gpzy_em.py:20`
- **用途**: 东方财富网-数据中心-特色数据-股权质押-股权质押市场概况

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `sortColumns` | `"TRADE_DATE"` | 排序字段 |
| `sortTypes` | `"-1"` | -1降序 1升序 |
| `pageSize` | `"500"` | 每页条数 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `reportName` | `"RPT_CSDC_STATISTICS"` | 数据集标识 |
| `columns` | `"ALL"` | 返回字段，ALL=全部 |
| `quoteColumns` | `""` | 行情字段注入 |
| `source` | `"WEB"` | 客户端标识 |
| `client` | `"WEB"` | 客户端标识 |

**返回字段**（按列序，共 8 列）

| 列序 | 字段含义 |
|---|---|
| 0 | 交易日期 |
| 1 | 质押总股数 |
| 2 | 质押总市值 |
| 3 | 沪深300指数 |
| 4 | 涨跌幅 |
| 5 | A股质押总比例 |
| 6 | 质押公司数量 |
| 7 | 质押笔数 |

---

## 23. `RPT_CUSTOM_DMSK_HOLDERS_JOIN_HOLDER_SHAREANALYSIS`

- **akshare 入口**: `stock_gdfx_holding_analyse_em(date: str = "20230331")`
- **源码**: `stock_feature/stock_gdfx_em.py:788`
- **用途**: 东方财富网-数据中心-股东分析-股东持股分析-十大股东

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `sortColumns` | `"NOTICE_DATE,SECURITY_CODE,RANK"` | 排序字段 |
| `sortTypes` | `"-1,1,1"` | -1降序 1升序 |
| `pageSize` | `"500"` | 每页条数 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `reportName` | `"RPT_CUSTOM_DMSK_HOLDERS_JOIN_HOLDER_SHAREANALYSIS"` | 数据集标识 |
| `columns` | `"ALL;D10_ADJCHRATE,D30_ADJCHRATE,D60_ADJCHRATE"` | 返回字段，ALL=全部 |
| `source` | `"WEB"` | 客户端标识 |
| `client` | `"WEB"` | 客户端标识 |
| `filter` | `f"(END_DATE='{'-'.join([date[:4], date[4:6], date[6:]])}')"` | 过滤表达式 |

**字段重命名**（英文原始名 → 中文含义）

| 原始字段 | 含义 |
|---|---|
| `index` | 序号 |
| `SECUCODE` | - |
| `SECURITY_CODE` | 股票代码 |
| `ORG_CODE` | - |
| `SECURITY_TYPE_CODE` | - |
| `END_DATE` | 报告期 |
| `HOLDER_CODE` | - |
| `HOLDER_NAME` | 股东名称 |
| `HOLD_NUM` | 期末持股-数量 |
| `HOLD_RATIO` | - |
| `HOLD_NUM_CHANGE` | 期末持股-数量变化 |
| `HOLD_RATIO_CHANGE` | 期末持股-数量变化比例 |
| `NOTICE_DATE` | 公告日 |
| `SECURITY_NAME_ABBR` | 股票简称 |
| `HOLDER_MARKET_CAP` | 期末持股-流通市值 |
| `HOLDNUM_CHANGE_NAME` | 期末持股-持股变动 |
| `HOLDER_TYPE_ORG` | 股东类型 |
| `D10_ADJCHRATE` | 公告日后涨跌幅-10个交易日 |
| `D30_ADJCHRATE` | 公告日后涨跌幅-30个交易日 |
| `D60_ADJCHRATE` | 公告日后涨跌幅-60个交易日 |

---

## 24. `RPT_CUSTOM_F10_EH_FREEHOLDERS_JOIN_FREEHOLDER_SHAREANALYSIS`

- **akshare 入口**: `stock_gdfx_free_holding_analyse_em(date: str = "20230930")`
- **源码**: `stock_feature/stock_gdfx_em.py:690`
- **用途**: 东方财富网-数据中心-股东分析-股东持股分析-十大流通股东

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `sortColumns` | `"UPDATE_DATE,SECURITY_CODE,HOLDER_RANK"` | 排序字段 |
| `sortTypes` | `"-1,1,1"` | -1降序 1升序 |
| `pageSize` | `"500"` | 每页条数 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `reportName` | `"RPT_CUSTOM_F10_EH_FREEHOLDERS_JOIN_FREEHOLDER_SHAREANALYSIS"` | 数据集标识 |
| `columns` | `"ALL;D10_ADJCHRATE,D30_ADJCHRATE,D60_ADJCHRATE"` | 返回字段，ALL=全部 |
| `source` | `"WEB"` | 客户端标识 |
| `client` | `"WEB"` | 客户端标识 |
| `filter` | `f"(END_DATE='{'-'.join([date[:4], date[4:6], date[6:]])}')"` | 过滤表达式 |

**字段重命名**（英文原始名 → 中文含义）

| 原始字段 | 含义 |
|---|---|
| `index` | 序号 |
| `HOLDER_NAME` | 股东名称 |
| `HOLDER_TYPE` | 股东类型 |
| `SECURITY_CODE` | 股票代码 |
| `SECURITY_NAME_ABBR` | 股票简称 |
| `END_DATE` | 报告期 |
| `HOLD_NUM` | 期末持股-数量 |
| `XZCHANGE` | 期末持股-数量变化 |
| `HOLD_RATIO_CHANGE` | 期末持股-数量变化比例 |
| `HOLDNUM_CHANGE_NAME` | 期末持股-持股变动 |
| `HOLDER_MARKET_CAP` | 期末持股-流通市值 |
| `UPDATE_DATE` | 公告日 |
| `D10_ADJCHRATE` | 公告日后涨跌幅-10个交易日 |
| `D30_ADJCHRATE` | 公告日后涨跌幅-30个交易日 |
| `D60_ADJCHRATE` | 公告日后涨跌幅-60个交易日 |

---

## 25. `RPT_CUSTOM_SUSPEND_DATA_INTERFACE`

- **akshare 入口**: `stock_tfp_em(date: str = "20240426")`
- **源码**: `stock_feature/stock_tfp_em.py:12`
- **用途**: 东方财富网-数据中心-特色数据-停复牌信息

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `sortColumns` | `"SUSPEND_START_DATE"` | 排序字段 |
| `sortTypes` | `"-1"` | -1降序 1升序 |
| `pageSize` | `"500"` | 每页条数 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `reportName` | `"RPT_CUSTOM_SUSPEND_DATA_INTERFACE"` | 数据集标识 |
| `columns` | `"ALL"` | 返回字段，ALL=全部 |
| `source` | `"WEB"` | 客户端标识 |
| `client` | `"WEB"` | 客户端标识 |
| `filter` | `f"""(MARKET="全部")(DATETIME='{"-".join([date[:4], date[4:6], date[6:]])}')"""` | 过滤表达式 |

**返回字段**（按列序，共 13 列）

| 列序 | 字段含义 |
|---|---|
| 0 | 序号 |
| 1 | 代码 |
| 2 | 名称 |
| 3 | 停牌时间 |
| 4 | 停牌截止时间 |
| 5 | 停牌期限 |
| 6 | 停牌原因 |
| 7 | 所属市场 |
| 8 | 停牌开始日期 |
| 9 | 预计复牌时间 |

---

## 26. `RPT_DAILYBILLBOARD_DETAILSNEW`

- **akshare 入口**: `stock_lhb_detail_em(start_date: str = "20230403", end_date: str = "20230417")`
- **源码**: `stock_feature/stock_lhb_em.py:13`
- **用途**: 东方财富网-数据中心-龙虎榜单-龙虎榜详情

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `sortColumns` | `"SECURITY_CODE,TRADE_DATE"` | 排序字段 |
| `sortTypes` | `"1,-1"` | -1降序 1升序 |
| `pageSize` | `"5000"` | 每页条数 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `reportName` | `"RPT_DAILYBILLBOARD_DETAILSNEW"` | 数据集标识 |
| `columns` | `"SECURITY_CODE,SECUCODE,SECURITY_NAME_ABBR,TRADE_DATE,EXPLAIN,CLOSE_PRICE,CHANGE_RATE,"` | 返回字段，ALL=全部 |
| `source` | `"WEB"` | 客户端标识 |
| `client` | `"WEB"` | 客户端标识 |
| `filter` | `f"(TRADE_DATE<='{end_date}')(TRADE_DATE>='{start_date}')"` | 过滤表达式 |

**字段重命名**（英文原始名 → 中文含义）

| 原始字段 | 含义 |
|---|---|
| `index` | 序号 |
| `SECURITY_CODE` | 代码 |
| `SECUCODE` | - |
| `SECURITY_NAME_ABBR` | 名称 |
| `TRADE_DATE` | 上榜日 |
| `EXPLAIN` | 解读 |
| `CLOSE_PRICE` | 收盘价 |
| `CHANGE_RATE` | 涨跌幅 |
| `BILLBOARD_NET_AMT` | 龙虎榜净买额 |
| `BILLBOARD_BUY_AMT` | 龙虎榜买入额 |
| `BILLBOARD_SELL_AMT` | 龙虎榜卖出额 |
| `BILLBOARD_DEAL_AMT` | 龙虎榜成交额 |
| `ACCUM_AMOUNT` | 市场总成交额 |
| `DEAL_NET_RATIO` | 净买额占总成交比 |
| `DEAL_AMOUNT_RATIO` | 成交额占总成交比 |
| `TURNOVERRATE` | 换手率 |
| `FREE_MARKET_CAP` | 流通市值 |
| `EXPLANATION` | 上榜原因 |
| `D1_CLOSE_ADJCHRATE` | 上榜后1日 |
| `D2_CLOSE_ADJCHRATE` | 上榜后2日 |
| `D5_CLOSE_ADJCHRATE` | 上榜后5日 |
| `D10_CLOSE_ADJCHRATE` | 上榜后10日 |

---

## 27. `RPT_DATA_BLOCKTRADE`

- **akshare 入口**: `stock_dzjy_mrmx(symbol: str = "基金", start_date: str = "20220104", end_date: str = "20220104")`
- **源码**: `stock/stock_dzjy_em.py:71`
- **用途**: 东方财富网-数据中心-大宗交易-每日明细

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `sortColumns` | `"SECURITY_CODE"` | 排序字段 |
| `sortTypes` | `"1"` | -1降序 1升序 |
| `pageSize` | `"5000"` | 每页条数 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `reportName` | `"RPT_DATA_BLOCKTRADE"` | 数据集标识 |
| `columns` | `"TRADE_DATE,SECURITY_CODE,SECUCODE,SECURITY_NAME_ABBR,CHANGE_RATE,CLOSE_PRICE,"` | 返回字段，ALL=全部 |
| `source` | `"WEB"` | 客户端标识 |
| `client` | `"WEB"` | 客户端标识 |
| `filter` | `f"""(SECURITY_TYPE_WEB={symbol_map[symbol]})(TRADE_DATE>=` | 过滤表达式 |

**返回字段**（按列序，共 20 列）

| 列序 | 字段含义 |
|---|---|
| 0 | 序号 |
| 1 | 交易日期 |
| 2 | 证券代码 |
| 4 | 证券简称 |
| 5 | 涨跌幅 |
| 6 | 收盘价 |
| 7 | 成交价 |
| 8 | 折溢率 |
| 9 | 成交量 |
| 10 | 成交额 |
| 11 | 成交额/流通市值 |
| 12 | 买方营业部 |
| 13 | 卖方营业部 |

---

## 28. `RPT_DMSK_FN_BALANCE`

- **akshare 入口**: `stock_zcfz_em(date: str = "20240331")`
- **源码**: `stock_feature/stock_report_em.py:19`
- **用途**: 东方财富-数据中心-年报季报-业绩快报-资产负债表

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `sortColumns` | `"NOTICE_DATE,SECURITY_CODE"` | 排序字段 |
| `sortTypes` | `"-1,-1"` | -1降序 1升序 |
| `pageSize` | `"500"` | 每页条数 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `reportName` | `"RPT_DMSK_FN_BALANCE"` | 数据集标识 |
| `columns` | `"ALL"` | 返回字段，ALL=全部 |
| `filter` | `f"""(SECURITY_TYPE_CODE in ("058001001","058001008"))(TRADE_MARKET_CODE!="069001017")` | 过滤表达式 |

**返回字段**（按列序，共 58 列）

| 列序 | 字段含义 |
|---|---|
| 0 | 序号 |
| 2 | 股票代码 |
| 5 | 股票简称 |
| 13 | 公告日期 |
| 15 | 资产-总资产 |
| 17 | 资产-货币资金 |
| 19 | 资产-应收账款 |
| 21 | 资产-存货 |
| 23 | 负债-总负债 |
| 24 | 负债-应付账款 |
| 26 | 负债-预收账款 |
| 28 | 股东权益合计 |
| 30 | 资产-总资产同比 |
| 31 | 负债-总负债同比 |
| 33 | 资产负债率 |

---

## 29. `RPT_DMSK_FN_CASHFLOW`

- **akshare 入口**: `stock_xjll_em(date: str = "20240331")`
- **源码**: `stock_feature/stock_report_em.py:437`
- **用途**: 东方财富-数据中心-年报季报-业绩快报-现金流量表

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `sortColumns` | `"NOTICE_DATE,SECURITY_CODE"` | 排序字段 |
| `sortTypes` | `"-1,-1"` | -1降序 1升序 |
| `pageSize` | `"500"` | 每页条数 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `reportName` | `"RPT_DMSK_FN_CASHFLOW"` | 数据集标识 |
| `columns` | `"ALL"` | 返回字段，ALL=全部 |
| `filter` | `f"""(SECURITY_TYPE_CODE in ("058001001","058001008"))(TRADE_MARKET_CODE!="069001017")` | 过滤表达式 |

**返回字段**（按列序，共 49 列）

| 列序 | 字段含义 |
|---|---|
| 0 | 序号 |
| 2 | 股票代码 |
| 5 | 股票简称 |
| 13 | 公告日期 |
| 15 | 经营性现金流-现金流量净额 |
| 16 | 经营性现金流-净现金流占比 |
| 21 | 投资性现金流-现金流量净额 |
| 22 | 投资性现金流-净现金流占比 |
| 27 | 融资性现金流-现金流量净额 |
| 28 | 融资性现金流-净现金流占比 |
| 29 | 净现金流-净现金流 |
| 30 | 净现金流-同比增长 |

---

## 30. `RPT_DMSK_FN_INCOME`

- **akshare 入口**: `stock_lrb_em(date: str = "20240331")`
- **源码**: `stock_feature/stock_report_em.py:301`
- **用途**: 东方财富-数据中心-年报季报-业绩快报-利润表

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `sortColumns` | `"NOTICE_DATE,SECURITY_CODE"` | 排序字段 |
| `sortTypes` | `"-1,-1"` | -1降序 1升序 |
| `pageSize` | `"500"` | 每页条数 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `reportName` | `"RPT_DMSK_FN_INCOME"` | 数据集标识 |
| `columns` | `"ALL"` | 返回字段，ALL=全部 |
| `filter` | `f"""(SECURITY_TYPE_CODE in ("058001001","058001008"))(TRADE_MARKET_CODE!="069001017")` | 过滤表达式 |

**返回字段**（按列序，共 47 列）

| 列序 | 字段含义 |
|---|---|
| 0 | 序号 |
| 2 | 股票代码 |
| 5 | 股票简称 |
| 13 | 公告日期 |
| 15 | 净利润 |
| 16 | 营业总收入 |
| 17 | 营业总支出-营业总支出 |
| 19 | 营业总支出-营业支出 |
| 22 | 营业总支出-销售费用 |
| 23 | 营业总支出-管理费用 |
| 24 | 营业总支出-财务费用 |
| 25 | 营业利润 |
| 26 | 利润总额 |
| 42 | 营业总收入同比 |
| 44 | 净利润同比 |

---

## 31. `RPT_DMSK_HOLDERS`

- **akshare 入口**: `stock_gdfx_holding_detail_em(date: str = "20230331", indicator: str = "个人", symbol: str = "新进")`
- **源码**: `stock_feature/stock_gdfx_em.py:594`
- **用途**: 东方财富网-数据中心-股东分析-股东持股明细-十大股东

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `sortColumns` | `"NOTICE_DATE,SECURITY_CODE,RANK"` | 排序字段 |
| `sortTypes` | `"-1,1,1"` | -1降序 1升序 |
| `pageSize` | `"50"` | 每页条数 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `reportName` | `"RPT_DMSK_HOLDERS"` | 数据集标识 |
| `columns` | `"ALL"` | 返回字段，ALL=全部 |
| `source` | `"WEB"` | 客户端标识 |
| `client` | `"WEB"` | 客户端标识 |
| `filter` | `f"""(HOLDER_NEWTYPE="{indicator}")(HOLDNUM_CHANGE_NAME="{symbol}")(END_DATE='{"-".join([date[:4], da` | 过滤表达式 |

**字段重命名**（英文原始名 → 中文含义）

| 原始字段 | 含义 |
|---|---|
| `index` | 序号 |
| `HOLDER_NAME` | 股东名称 |
| `HOLDER_NEWTYPE` | 股东类型 |
| `RANK` | 股东排名 |
| `SECURITY_CODE` | 股票代码 |
| `SECURITY_NAME_ABBR` | 股票简称 |
| `END_DATE` | 报告期 |
| `HOLD_NUM` | 期末持股-数量 |
| `HOLD_NUM_CHANGE` | 期末持股-数量变化 |
| `HOLD_RATIO_CHANGE` | 期末持股-数量变化比例 |
| `HOLDNUM_CHANGE_NAME` | 期末持股-持股变动 |
| `HOLDER_MARKET_CAP` | 期末持股-流通市值 |
| `NOTICE_DATE` | 公告日 |

---

## 32. `RPT_DMSK_TS_STOCKEVALUATE`

- **akshare 入口**: `stock_comment_detail_zlkp_jgcyd_em(symbol: str = "600000")`
- **源码**: `stock_feature/stock_comment_em.py:119`
- **用途**: 东方财富网-数据中心-特色数据-千股千评-主力控盘-机构参与度

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `reportName` | `"RPT_DMSK_TS_STOCKEVALUATE"` | 数据集标识 |
| `filter` | `f'(SECURITY_CODE="{symbol}")'` | 过滤表达式 |
| `columns` | `"ALL"` | 返回字段，ALL=全部 |
| `source` | `"WEB"` | 客户端标识 |
| `client` | `"WEB"` | 客户端标识 |
| `sortColumns` | `"TRADE_DATE"` | 排序字段 |
| `sortTypes` | `"-1"` | -1降序 1升序 |

---

## 33. `RPT_DMSK_TS_STOCKNEW`

- **akshare 入口**: `stock_comment_em()`
- **源码**: `stock_feature/stock_comment_em.py:18`
- **用途**: 东方财富网-数据中心-特色数据-千股千评

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `sortColumns` | `"SECURITY_CODE"` | 排序字段 |
| `sortTypes` | `"1"` | -1降序 1升序 |
| `pageSize` | `"500"` | 每页条数 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `reportName` | `"RPT_DMSK_TS_STOCKNEW"` | 数据集标识 |
| `quoteColumns` | `"f2~01~SECURITY_CODE~CLOSE_PRICE,f8~01~SECURITY_CODE~TURNOVERRATE,"` | 行情字段注入 |
| `columns` | `"ALL"` | 返回字段，ALL=全部 |
| `filter` | `""` | 过滤表达式 |
| `token` | `"894050c76af8597a853f5b408b759f5d"` | 固定令牌 |

**返回字段**（按列序，共 32 列）

| 列序 | 字段含义 |
|---|---|
| 0 | 序号 |
| 2 | 代码 |
| 4 | 交易日 |
| 5 | 名称 |
| 9 | 最新价 |
| 10 | 涨跌幅 |
| 12 | 换手率 |
| 13 | 主力成本 |
| 14 | 市盈率 |
| 17 | 机构参与度 |
| 26 | 综合得分 |
| 27 | 上升 |
| 28 | 目前排名 |
| 29 | 关注指数 |

---

## 34. `RPT_ECONOMICVALUE_AUSTRALIA`

- **akshare 入口**: `macro_australia_retail_rate_monthly()`
- **源码**: `economic/macro_australia.py:13`
- **用途**: 东方财富-经济数据-澳大利亚-零售销售月率

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `reportName` | `"RPT_ECONOMICVALUE_AUSTRALIA"` | 数据集标识 |
| `columns` | `"ALL"` | 返回字段，ALL=全部 |
| `filter` | `'(INDICATOR_ID="EMG00152903")'` | 过滤表达式 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `pageSize` | `"2000"` | 每页条数 |
| `sortColumns` | `"REPORT_DATE"` | 排序字段 |
| `sortTypes` | `"-1"` | -1降序 1升序 |
| `source` | `"WEB"` | 客户端标识 |
| `client` | `"WEB"` | 客户端标识 |
| `p` | `"1"` |  |
| `pageNo` | `"1"` |  |
| `pageNum` | `"1"` |  |

**返回字段**（按列序，共 8 列）

| 列序 | 字段含义 |
|---|---|
| 3 | 时间 |
| 5 | 发布日期 |
| 6 | 现值 |
| 7 | 前值 |

---

## 35. `RPT_ECONOMICVALUE_BRITAIN`

- **akshare 入口**: `macro_uk_core(symbol: str = "EMG00010348")`
- **源码**: `economic/macro_uk.py:12`
- **用途**: 东方财富-数据中心-经济数据一览-宏观经济-英国-核心代码

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `reportName` | `"RPT_ECONOMICVALUE_BRITAIN"` | 数据集标识 |
| `columns` | `"ALL"` | 返回字段，ALL=全部 |
| `filter` | `f'(INDICATOR_ID="{symbol}")'` | 过滤表达式 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `pageSize` | `"5000"` | 每页条数 |
| `sortColumns` | `"REPORT_DATE"` | 排序字段 |
| `sortTypes` | `"-1"` | -1降序 1升序 |
| `source` | `"WEB"` | 客户端标识 |
| `client` | `"WEB"` | 客户端标识 |
| `p` | `"1"` |  |
| `pageNo` | `"1"` |  |
| `pageNum` | `"1"` |  |

**字段重命名**（英文原始名 → 中文含义）

| 原始字段 | 含义 |
|---|---|
| `COUNTRY` | - |
| `INDICATOR_ID` | - |
| `INDICATOR_NAME` | - |
| `REPORT_DATE_CH` | 时间 |
| `REPORT_DATE` | - |
| `PUBLISH_DATE` | 发布日期 |
| `VALUE` | 现值 |
| `PRE_VALUE` | 前值 |
| `INDICATOR_IDOLD` | - |

---

## 36. `RPT_ECONOMICVALUE_CA`

- **akshare 入口**: `macro_canada_new_house_rate()`
- **源码**: `economic/macro_canada.py:13`
- **用途**: 东方财富-经济数据-加拿大-新屋开工

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `reportName` | `"RPT_ECONOMICVALUE_CA"` | 数据集标识 |
| `columns` | `"ALL"` | 返回字段，ALL=全部 |
| `filter` | `'(INDICATOR_ID="EMG00342247")'` | 过滤表达式 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `pageSize` | `"2000"` | 每页条数 |
| `sortColumns` | `"REPORT_DATE"` | 排序字段 |
| `sortTypes` | `"-1"` | -1降序 1升序 |
| `source` | `"WEB"` | 客户端标识 |
| `client` | `"WEB"` | 客户端标识 |
| `p` | `"1"` |  |
| `pageNo` | `"1"` |  |
| `pageNum` | `"1"` |  |

**返回字段**（按列序，共 9 列）

| 列序 | 字段含义 |
|---|---|
| 4 | 时间 |
| 6 | 发布日期 |
| 7 | 现值 |
| 8 | 前值 |

---

## 37. `RPT_ECONOMICVALUE_CH`

- **akshare 入口**: `macro_swiss_core(symbol: str = "EMG00341602")`
- **源码**: `economic/macro_swiss.py:12`
- **用途**: 东方财富-数据中心-经济数据一览-宏观经济-瑞士-核心代码

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `reportName` | `"RPT_ECONOMICVALUE_CH"` | 数据集标识 |
| `columns` | `"ALL"` | 返回字段，ALL=全部 |
| `filter` | `f'(INDICATOR_ID="{symbol}")'` | 过滤表达式 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `pageSize` | `"5000"` | 每页条数 |
| `sortColumns` | `"REPORT_DATE"` | 排序字段 |
| `sortTypes` | `"-1"` | -1降序 1升序 |
| `source` | `"WEB"` | 客户端标识 |
| `client` | `"WEB"` | 客户端标识 |
| `p` | `"1"` |  |
| `pageNo` | `"1"` |  |
| `pageNum` | `"1"` |  |

**字段重命名**（英文原始名 → 中文含义）

| 原始字段 | 含义 |
|---|---|
| `COUNTRY` | - |
| `INDICATOR_ID` | - |
| `INDICATOR_NAME` | - |
| `REPORT_DATE_CH` | 时间 |
| `REPORT_DATE` | - |
| `PUBLISH_DATE` | 发布日期 |
| `VALUE` | 现值 |
| `PRE_VALUE` | 前值 |
| `INDICATOR_IDOLD` | - |

---

## 38. `RPT_ECONOMICVALUE_GER`

- **akshare 入口**: `macro_germany_core(symbol: str = "EMG00179154")`
- **源码**: `economic/macro_germany.py:11`
- **用途**: 东方财富-数据中心-经济数据一览-宏观经济-德国-核心代码

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `reportName` | `"RPT_ECONOMICVALUE_GER"` | 数据集标识 |
| `columns` | `"ALL"` | 返回字段，ALL=全部 |
| `filter` | `f'(INDICATOR_ID="{symbol}")'` | 过滤表达式 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `pageSize` | `"5000"` | 每页条数 |
| `sortColumns` | `"REPORT_DATE"` | 排序字段 |
| `sortTypes` | `"-1"` | -1降序 1升序 |
| `source` | `"WEB"` | 客户端标识 |
| `client` | `"WEB"` | 客户端标识 |
| `p` | `"1"` |  |
| `pageNo` | `"1"` |  |
| `pageNum` | `"1"` |  |

**字段重命名**（英文原始名 → 中文含义）

| 原始字段 | 含义 |
|---|---|
| `COUNTRY` | - |
| `INDICATOR_ID` | - |
| `INDICATOR_NAME` | - |
| `REPORT_DATE_CH` | 时间 |
| `REPORT_DATE` | - |
| `PUBLISH_DATE` | 发布日期 |
| `VALUE` | 现值 |
| `PRE_VALUE` | 前值 |
| `INDICATOR_IDOLD` | - |

---

## 39. `RPT_ECONOMICVALUE_HK`

- **akshare 入口**: `macro_china_hk_core(symbol: str = "EMG00341602")`
- **源码**: `economic/macro_china_hk.py:12`
- **用途**: 东方财富-数据中心-经济数据一览-宏观经济-日本-核心代码

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `reportName` | `"RPT_ECONOMICVALUE_HK"` | 数据集标识 |
| `columns` | `"ALL"` | 返回字段，ALL=全部 |
| `filter` | `f'(INDICATOR_ID="{symbol}")'` | 过滤表达式 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `pageSize` | `"5000"` | 每页条数 |
| `sortColumns` | `"REPORT_DATE"` | 排序字段 |
| `sortTypes` | `"-1"` | -1降序 1升序 |
| `source` | `"WEB"` | 客户端标识 |
| `client` | `"WEB"` | 客户端标识 |
| `p` | `"1"` |  |
| `pageNo` | `"1"` |  |
| `pageNum` | `"1"` |  |

**字段重命名**（英文原始名 → 中文含义）

| 原始字段 | 含义 |
|---|---|
| `COUNTRY` | - |
| `INDICATOR_ID` | - |
| `INDICATOR_NAME` | - |
| `REPORT_DATE_CH` | 时间 |
| `REPORT_DATE` | - |
| `PUBLISH_DATE` | 发布日期 |
| `VALUE` | 现值 |
| `PRE_VALUE` | 前值 |
| `INDICATOR_IDOLD` | - |

---

## 40. `RPT_ECONOMICVALUE_JPAN`

- **akshare 入口**: `macro_japan_core(symbol: str = "EMG00341602")`
- **源码**: `economic/macro_japan.py:12`
- **用途**: 东方财富-数据中心-经济数据一览-宏观经济-日本-核心代码

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `reportName` | `"RPT_ECONOMICVALUE_JPAN"` | 数据集标识 |
| `columns` | `"ALL"` | 返回字段，ALL=全部 |
| `filter` | `f'(INDICATOR_ID="{symbol}")'` | 过滤表达式 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `pageSize` | `"5000"` | 每页条数 |
| `sortColumns` | `"REPORT_DATE"` | 排序字段 |
| `sortTypes` | `"-1"` | -1降序 1升序 |
| `source` | `"WEB"` | 客户端标识 |
| `client` | `"WEB"` | 客户端标识 |
| `p` | `"1"` |  |
| `pageNo` | `"1"` |  |
| `pageNum` | `"1"` |  |

**字段重命名**（英文原始名 → 中文含义）

| 原始字段 | 含义 |
|---|---|
| `COUNTRY` | - |
| `INDICATOR_ID` | - |
| `INDICATOR_NAME` | - |
| `REPORT_DATE_CH` | 时间 |
| `REPORT_DATE` | - |
| `PUBLISH_DATE` | 发布日期 |
| `VALUE` | 现值 |
| `PRE_VALUE` | 前值 |
| `INDICATOR_IDOLD` | - |

---

## 41. `RPT_ECONOMICVALUE_USA`

- **akshare 入口**: `macro_usa_phs()`
- **源码**: `economic/macro_usa.py:78`
- **用途**: 东方财富-经济数据一览-美国-未决房屋销售月率

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `reportName` | `"RPT_ECONOMICVALUE_USA"` | 数据集标识 |
| `columns` | `"ALL"` | 返回字段，ALL=全部 |
| `filter` | `'(INDICATOR_ID="EMG00342249")'` | 过滤表达式 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `pageSize` | `"2000"` | 每页条数 |
| `sortColumns` | `"REPORT_DATE"` | 排序字段 |
| `sortTypes` | `"-1"` | -1降序 1升序 |
| `source` | `"WEB"` | 客户端标识 |
| `client` | `"WEB"` | 客户端标识 |
| `p` | `"1"` |  |
| `pageNo` | `"1"` |  |
| `pageNum` | `"1"` |  |

**返回字段**（按列序，共 8 列）

| 列序 | 字段含义 |
|---|---|
| 3 | 时间 |
| 5 | 发布日期 |
| 6 | 现值 |
| 7 | 前值 |

---

## 42. `RPT_ECONOMY_ASSET_INVEST`

- **akshare 入口**: `macro_china_gdzctz()`
- **源码**: `economic/macro_china.py:2673`
- **用途**: 东方财富-中国城镇固定资产投资

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `columns` | `"REPORT_DATE,TIME,BASE,BASE_SAME,BASE_SEQUENTIAL,BASE_ACCUMULATE"` | 返回字段，ALL=全部 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `pageSize` | `"2000"` | 每页条数 |
| `sortColumns` | `"REPORT_DATE"` | 排序字段 |
| `sortTypes` | `"-1"` | -1降序 1升序 |
| `source` | `"WEB"` | 客户端标识 |
| `client` | `"WEB"` | 客户端标识 |
| `reportName` | `"RPT_ECONOMY_ASSET_INVEST"` | 数据集标识 |
| `p` | `"1"` |  |
| `pageNo` | `"1"` |  |
| `pageNum` | `"1"` |  |

**返回字段**（按列序，共 6 列）

| 列序 | 字段含义 |
|---|---|
| 1 | 月份 |
| 2 | 当月 |
| 3 | 同比增长 |
| 4 | 环比增长 |
| 5 | 自年初累计 |

---

## 43. `RPT_ECONOMY_BOOM_INDEX`

- **akshare 入口**: `macro_china_enterprise_boom_index()`
- **源码**: `economic/macro_china.py:1137`
- **用途**: https://data.eastmoney.com/cjsj/qyjqzs.html

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `columns` | `"REPORT_DATE,TIME,BOOM_INDEX,FAITH_INDEX,BOOM_INDEX_SAME,BOOM_INDEX_SEQUENTIAL,"` | 返回字段，ALL=全部 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `pageSize` | `"500"` | 每页条数 |
| `sortColumns` | `"REPORT_DATE"` | 排序字段 |
| `sortTypes` | `"-1"` | -1降序 1升序 |
| `source` | `"WEB"` | 客户端标识 |
| `client` | `"WEB"` | 客户端标识 |
| `reportName` | `"RPT_ECONOMY_BOOM_INDEX"` | 数据集标识 |
| `p` | `"1"` |  |
| `pageNo` | `"1"` |  |
| `pageNum` | `"1"` |  |

**返回字段**（按列序，共 8 列）

| 列序 | 字段含义 |
|---|---|
| 1 | 季度 |
| 2 | 企业景气指数-指数 |
| 3 | 企业家信心指数-指数 |
| 4 | 企业景气指数-同比 |
| 5 | 企业景气指数-环比 |
| 6 | 企业家信心指数-同比 |
| 7 | 企业家信心指数-环比 |

---

## 44. `RPT_ECONOMY_CPI`

- **akshare 入口**: `macro_china_cpi()`
- **源码**: `economic/macro_china.py:2424`
- **用途**: 东方财富-中国居民消费价格指数

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `columns` | `"REPORT_DATE,TIME,NATIONAL_SAME,NATIONAL_BASE,NATIONAL_SEQUENTIAL,NATIONAL_ACCUMULATE,"` | 返回字段，ALL=全部 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `pageSize` | `"2000"` | 每页条数 |
| `sortColumns` | `"REPORT_DATE"` | 排序字段 |
| `sortTypes` | `"-1"` | -1降序 1升序 |
| `source` | `"WEB"` | 客户端标识 |
| `client` | `"WEB"` | 客户端标识 |
| `reportName` | `"RPT_ECONOMY_CPI"` | 数据集标识 |
| `p` | `"1"` |  |
| `pageNo` | `"1"` |  |
| `pageNum` | `"1"` |  |

**返回字段**（按列序，共 14 列）

| 列序 | 字段含义 |
|---|---|
| 1 | 月份 |
| 2 | 全国-同比增长 |
| 3 | 全国-当月 |
| 4 | 全国-环比增长 |
| 5 | 全国-累计 |
| 6 | 城市-同比增长 |
| 7 | 城市-当月 |
| 8 | 城市-环比增长 |
| 9 | 城市-累计 |
| 10 | 农村-同比增长 |
| 11 | 农村-当月 |
| 12 | 农村-环比增长 |
| 13 | 农村-累计 |

---

## 45. `RPT_ECONOMY_CURRENCY_SUPPLY`

- **akshare 入口**: `macro_china_money_supply()`
- **源码**: `economic/macro_china.py:2341`
- **用途**: 东方财富-货币供应量

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `columns` | `"REPORT_DATE,TIME,BASIC_CURRENCY,BASIC_CURRENCY_SAME,BASIC_CURRENCY_SEQUENTIAL,CURRENCY,"` | 返回字段，ALL=全部 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `pageSize` | `"2000"` | 每页条数 |
| `sortColumns` | `"REPORT_DATE"` | 排序字段 |
| `sortTypes` | `"-1"` | -1降序 1升序 |
| `source` | `"WEB"` | 客户端标识 |
| `client` | `"WEB"` | 客户端标识 |
| `reportName` | `"RPT_ECONOMY_CURRENCY_SUPPLY"` | 数据集标识 |
| `p` | `"1"` |  |
| `pageNo` | `"1"` |  |
| `pageNum` | `"1"` |  |

**返回字段**（按列序，共 11 列）

| 列序 | 字段含义 |
|---|---|
| 1 | 月份 |
| 2 | 货币和准货币(M2)-数量(亿元) |
| 3 | 货币和准货币(M2)-同比增长 |
| 4 | 货币和准货币(M2)-环比增长 |
| 5 | 货币(M1)-数量(亿元) |
| 6 | 货币(M1)-同比增长 |
| 7 | 货币(M1)-环比增长 |
| 8 | 流通中的现金(M0)-数量(亿元) |
| 9 | 流通中的现金(M0)-同比增长 |
| 10 | 流通中的现金(M0)-环比增长 |

---

## 46. `RPT_ECONOMY_CUSTOMS`

- **akshare 入口**: `macro_china_hgjck()`
- **源码**: `economic/macro_china.py:2722`
- **用途**: 东方财富-海关进出口增减情况一览表

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `columns` | `"REPORT_DATE,TIME,EXIT_BASE,IMPORT_BASE,EXIT_BASE_SAME,IMPORT_BASE_SAME,"` | 返回字段，ALL=全部 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `pageSize` | `"2000"` | 每页条数 |
| `sortColumns` | `"REPORT_DATE"` | 排序字段 |
| `sortTypes` | `"-1"` | -1降序 1升序 |
| `source` | `"WEB"` | 客户端标识 |
| `client` | `"WEB"` | 客户端标识 |
| `reportName` | `"RPT_ECONOMY_CUSTOMS"` | 数据集标识 |
| `p` | `"1"` |  |
| `pageNo` | `"1"` |  |
| `pageNum` | `"1"` |  |

**字段重命名**（英文原始名 → 中文含义）

| 原始字段 | 含义 |
|---|---|
| `REPORT_DATE` | - |
| `TIME` | 月份 |
| `EXIT_BASE` | 当月出口额-金额 |
| `IMPORT_BASE` | 当月进口额-金额 |
| `EXIT_BASE_SAME` | 当月出口额-同比增长 |
| `IMPORT_BASE_SAME` | 当月进口额-同比增长 |
| `EXIT_BASE_SEQUENTIAL` | 当月出口额-环比增长 |
| `IMPORT_BASE_SEQUENTIAL` | 当月进口额-环比增长 |
| `EXIT_ACCUMULATE` | 累计出口额-金额 |
| `IMPORT_ACCUMULATE` | 累计进口额-金额 |
| `EXIT_ACCUMULATE_SAME` | 累计出口额-同比增长 |
| `IMPORT_ACCUMULATE_SAME` | 累计进口额-同比增长 |

---

## 47. `RPT_ECONOMY_DEPOSIT_RESERVE`

- **akshare 入口**: `macro_china_reserve_requirement_ratio()`
- **源码**: `economic/macro_china.py:3095`
- **用途**: 存款准备金率

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `columns` | `"REPORT_DATE,PUBLISH_DATE,TRADE_DATE,INTEREST_RATE_BB,INTEREST_RATE_BA,CHANGE_RATE_B,"` | 返回字段，ALL=全部 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `pageSize` | `"2000"` | 每页条数 |
| `sortColumns` | `"PUBLISH_DATE,TRADE_DATE"` | 排序字段 |
| `sortTypes` | `"-1,-1"` | -1降序 1升序 |
| `source` | `"WEB"` | 客户端标识 |
| `client` | `"WEB"` | 客户端标识 |
| `reportName` | `"RPT_ECONOMY_DEPOSIT_RESERVE"` | 数据集标识 |
| `p` | `"1"` |  |
| `pageNo` | `"1"` |  |
| `pageNum` | `"1"` |  |

**返回字段**（按列序，共 12 列）

| 列序 | 字段含义 |
|---|---|
| 1 | 公布时间 |
| 2 | 生效时间 |
| 3 | 大型金融机构-调整前 |
| 4 | 大型金融机构-调整后 |
| 5 | 大型金融机构-调整幅度 |
| 6 | 中小金融机构-调整前 |
| 7 | 中小金融机构-调整后 |
| 8 | 中小金融机构-调整幅度 |
| 9 | 消息公布次日指数涨跌-上证 |
| 10 | 消息公布次日指数涨跌-深证 |
| 11 | 备注 |

---

## 48. `RPT_ECONOMY_FAITH_INDEX`

- **akshare 入口**: `macro_china_xfzxx()`
- **源码**: `economic/macro_china.py:2965`
- **用途**: 东方财富网-经济数据一览-消费者信心指数

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `columns` | `"REPORT_DATE,TIME,CONSUMERS_FAITH_INDEX,FAITH_INDEX_SAME,FAITH_INDEX_SEQUENTIAL,"` | 返回字段，ALL=全部 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `pageSize` | `"2000"` | 每页条数 |
| `sortColumns` | `"REPORT_DATE"` | 排序字段 |
| `sortTypes` | `"-1"` | -1降序 1升序 |
| `source` | `"WEB"` | 客户端标识 |
| `client` | `"WEB"` | 客户端标识 |
| `reportName` | `"RPT_ECONOMY_FAITH_INDEX"` | 数据集标识 |
| `p` | `"1"` |  |
| `pageNo` | `"1"` |  |
| `pageNum` | `"1"` |  |

**返回字段**（按列序，共 11 列）

| 列序 | 字段含义 |
|---|---|
| 1 | 月份 |
| 2 | 消费者信心指数-指数值 |
| 3 | 消费者信心指数-同比增长 |
| 4 | 消费者信心指数-环比增长 |
| 5 | 消费者满意指数-指数值 |
| 6 | 消费者满意指数-同比增长 |
| 7 | 消费者满意指数-环比增长 |
| 8 | 消费者预期指数-指数值 |
| 9 | 消费者预期指数-同比增长 |
| 10 | 消费者预期指数-环比增长 |

---

## 49. `RPT_ECONOMY_FDI`

- **akshare 入口**: `macro_china_fdi()`
- **源码**: `economic/macro_china.py:202`
- **用途**: 东方财富-经济数据一览-中国-外商直接投资数据

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `columns` | `"REPORT_DATE,TIME,ACTUAL_FOREIGN,ACTUAL_FOREIGN_SAME,ACTUAL_FOREIGN_SEQUENTIAL,"` | 返回字段，ALL=全部 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `pageSize` | `"2000"` | 每页条数 |
| `sortColumns` | `"REPORT_DATE"` | 排序字段 |
| `sortTypes` | `"-1"` | -1降序 1升序 |
| `source` | `"WEB"` | 客户端标识 |
| `client` | `"WEB"` | 客户端标识 |
| `reportName` | `"RPT_ECONOMY_FDI"` | 数据集标识 |
| `p` | `"1"` |  |
| `pageNo` | `"1"` |  |
| `pageNum` | `"1"` |  |

**返回字段**（按列序，共 7 列）

| 列序 | 字段含义 |
|---|---|
| 1 | 月份 |
| 2 | 当月 |
| 3 | 当月-同比增长 |
| 4 | 当月-环比增长 |
| 5 | 累计 |
| 6 | 累计-同比增长 |

---

## 50. `RPT_ECONOMY_FOREX_DEPOSIT`

- **akshare 入口**: `macro_china_wbck()`
- **源码**: `economic/macro_china.py:2916`
- **用途**: 东方财富-本外币存款

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `columns` | `"REPORT_DATE,TIME,BASE,BASE_SAME,BASE_SEQUENTIAL,BASE_ACCUMULATE"` | 返回字段，ALL=全部 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `pageSize` | `"2000"` | 每页条数 |
| `sortColumns` | `"REPORT_DATE"` | 排序字段 |
| `sortTypes` | `"-1"` | -1降序 1升序 |
| `source` | `"WEB"` | 客户端标识 |
| `client` | `"WEB"` | 客户端标识 |
| `reportName` | `"RPT_ECONOMY_FOREX_DEPOSIT"` | 数据集标识 |
| `p` | `"1"` |  |
| `pageNo` | `"1"` |  |
| `pageNum` | `"1"` |  |

**返回字段**（按列序，共 6 列）

| 列序 | 字段含义 |
|---|---|
| 1 | 月份 |
| 2 | 当月 |
| 3 | 同比增长 |
| 4 | 环比增长 |
| 5 | 累计 |

---

## 51. `RPT_ECONOMY_FOREX_LOAN`

- **akshare 入口**: `macro_china_whxd()`
- **源码**: `economic/macro_china.py:2866`
- **用途**: 东方财富-外汇贷款数据

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `columns` | `"REPORT_DATE,TIME,BASE,BASE_SAME,BASE_SEQUENTIAL,BASE_ACCUMULATE"` | 返回字段，ALL=全部 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `pageSize` | `"2000"` | 每页条数 |
| `sortColumns` | `"REPORT_DATE"` | 排序字段 |
| `sortTypes` | `"-1"` | -1降序 1升序 |
| `source` | `"WEB"` | 客户端标识 |
| `client` | `"WEB"` | 客户端标识 |
| `reportName` | `"RPT_ECONOMY_FOREX_LOAN"` | 数据集标识 |
| `p` | `"1"` |  |
| `pageNo` | `"1"` |  |
| `pageNum` | `"1"` |  |

**返回字段**（按列序，共 6 列）

| 列序 | 字段含义 |
|---|---|
| 1 | 月份 |
| 2 | 当月 |
| 3 | 同比增长 |
| 4 | 环比增长 |
| 5 | 累计 |

---

## 52. `RPT_ECONOMY_GDP`

- **akshare 入口**: `macro_china_gdp()`
- **源码**: `economic/macro_china.py:2499`
- **用途**: 东方财富-中国国内生产总值

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `columns` | `"REPORT_DATE,TIME,DOMESTICL_PRODUCT_BASE,FIRST_PRODUCT_BASE,SECOND_PRODUCT_BASE,"` | 返回字段，ALL=全部 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `pageSize` | `"2000"` | 每页条数 |
| `sortColumns` | `"REPORT_DATE"` | 排序字段 |
| `sortTypes` | `"-1"` | -1降序 1升序 |
| `source` | `"WEB"` | 客户端标识 |
| `client` | `"WEB"` | 客户端标识 |
| `reportName` | `"RPT_ECONOMY_GDP"` | 数据集标识 |
| `p` | `"1"` |  |
| `pageNo` | `"1"` |  |
| `pageNum` | `"1"` |  |

**返回字段**（按列序，共 10 列）

| 列序 | 字段含义 |
|---|---|
| 1 | 季度 |
| 2 | 国内生产总值-绝对值 |
| 3 | 第一产业-绝对值 |
| 4 | 第二产业-绝对值 |
| 5 | 第三产业-绝对值 |
| 6 | 国内生产总值-同比增长 |
| 7 | 第一产业-同比增长 |
| 8 | 第二产业-同比增长 |
| 9 | 第三产业-同比增长 |

---

## 53. `RPT_ECONOMY_GOLD_CURRENCY`

- **akshare 入口**: `macro_china_fx_gold()`
- **源码**: `economic/macro_china.py:2189`
- **用途**: 东方财富-外汇和黄金储备

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `columns` | `"REPORT_DATE,TIME,GOLD_RESERVES,GOLD_RESERVES_SAME,"` | 返回字段，ALL=全部 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `pageSize` | `"1000"` | 每页条数 |
| `sortColumns` | `"REPORT_DATE"` | 排序字段 |
| `sortTypes` | `"-1"` | -1降序 1升序 |
| `source` | `"WEB"` | 客户端标识 |
| `client` | `"WEB"` | 客户端标识 |
| `reportName` | `"RPT_ECONOMY_GOLD_CURRENCY"` | 数据集标识 |
| `p` | `"1"` |  |
| `pageNo` | `"1"` |  |
| `pageNum` | `"1"` |  |

**返回字段**（按列序，共 8 列）

| 列序 | 字段含义 |
|---|---|
| 1 | 月份 |
| 2 | 黄金储备-数值 |
| 3 | 黄金储备-同比 |
| 4 | 黄金储备-环比 |
| 5 | 国家外汇储备-数值 |
| 6 | 国家外汇储备-同比 |
| 7 | 国家外汇储备-环比 |

---

## 54. `RPT_ECONOMY_GOODS_INDEX`

- **akshare 入口**: `macro_china_qyspjg()`
- **源码**: `economic/macro_china.py:107`
- **用途**: 东方财富-经济数据一览-中国-企业商品价格指数

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `columns` | `"REPORT_DATE,TIME,BASE,BASE_SAME,BASE_SEQUENTIAL,FARM_BASE,FARM_BASE_SAME,"` | 返回字段，ALL=全部 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `pageSize` | `"2000"` | 每页条数 |
| `sortColumns` | `"REPORT_DATE"` | 排序字段 |
| `sortTypes` | `"-1"` | -1降序 1升序 |
| `source` | `"WEB"` | 客户端标识 |
| `client` | `"WEB"` | 客户端标识 |
| `reportName` | `"RPT_ECONOMY_GOODS_INDEX"` | 数据集标识 |
| `p` | `"1"` |  |
| `pageNo` | `"1"` |  |
| `pageNum` | `"1"` |  |

**字段重命名**（英文原始名 → 中文含义）

| 原始字段 | 含义 |
|---|---|
| `REPORT_DATE` | - |
| `TIME` | 月份 |
| `BASE` | 总指数-指数值 |
| `BASE_SAME` | 总指数-同比增长 |
| `BASE_SEQUENTIAL` | 总指数-环比增长 |
| `FARM_BASE` | 农产品-指数值 |
| `FARM_BASE_SAME` | 农产品-同比增长 |
| `FARM_BASE_SEQUENTIAL` | 农产品-环比增长 |
| `MINERAL_BASE` | 矿产品-指数值 |
| `MINERAL_BASE_SAME` | 矿产品-同比增长 |
| `MINERAL_BASE_SEQUENTIAL` | 矿产品-环比增长 |
| `ENERGY_BASE` | 煤油电-指数值 |
| `ENERGY_BASE_SAME` | 煤油电-同比增长 |
| `ENERGY_BASE_SEQUENTIAL` | 煤油电-环比增长 |

---

## 55. `RPT_ECONOMY_HOUSE_PRICE`

- **akshare 入口**: `macro_china_new_house_price(city_first: str = "北京", city_second: str = "上海")`
- **源码**: `economic/macro_china.py:1058`
- **用途**: 中国-新房价指数

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `reportName` | `"RPT_ECONOMY_HOUSE_PRICE"` | 数据集标识 |
| `columns` | `"REPORT_DATE,CITY,FIRST_COMHOUSE_SAME,FIRST_COMHOUSE_SEQUENTIAL,FIRST_COMHOUSE_BASE,"` | 返回字段，ALL=全部 |
| `filter` | `f'(CITY in ("{city_first}","{city_second}"))'` | 过滤表达式 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `pageSize` | `"500"` | 每页条数 |
| `sortColumns` | `"REPORT_DATE,CITY"` | 排序字段 |
| `sortTypes` | `"-1,-1"` | -1降序 1升序 |
| `source` | `"WEB"` | 客户端标识 |
| `client` | `"WEB"` | 客户端标识 |
| `p` | `"1"` |  |
| `pageNo` | `"1"` |  |
| `pageNum` | `"1"` |  |

**返回字段**（按列序，共 9 列）

| 列序 | 字段含义 |
|---|---|
| 0 | 日期 |
| 1 | 城市 |
| 2 | 新建商品住宅价格指数-同比 |
| 3 | 新建商品住宅价格指数-环比 |
| 4 | 新建商品住宅价格指数-定基 |
| 5 | 二手住宅价格指数-同比 |
| 6 | 二手住宅价格指数-环比 |
| 7 | 二手住宅价格指数-定基 |

---

## 56. `RPT_ECONOMY_INCOME`

- **akshare 入口**: `macro_china_czsr()`
- **源码**: `economic/macro_china.py:2813`
- **用途**: 东方财富-财政收入

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `columns` | `"REPORT_DATE,TIME,BASE,BASE_SAME,BASE_SEQUENTIAL,BASE_ACCUMULATE,ACCUMULATE_SAME"` | 返回字段，ALL=全部 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `pageSize` | `"2000"` | 每页条数 |
| `sortColumns` | `"REPORT_DATE"` | 排序字段 |
| `sortTypes` | `"-1"` | -1降序 1升序 |
| `source` | `"WEB"` | 客户端标识 |
| `client` | `"WEB"` | 客户端标识 |
| `reportName` | `"RPT_ECONOMY_INCOME"` | 数据集标识 |
| `p` | `"1"` |  |
| `pageNo` | `"1"` |  |
| `pageNum` | `"1"` |  |

**返回字段**（按列序，共 7 列）

| 列序 | 字段含义 |
|---|---|
| 1 | 月份 |
| 2 | 当月 |
| 3 | 当月-同比增长 |
| 4 | 当月-环比增长 |
| 5 | 累计 |
| 6 | 累计-同比增长 |

---

## 57. `RPT_ECONOMY_INDUS_GROW`

- **akshare 入口**: `macro_china_gyzjz()`
- **源码**: `economic/macro_china.py:3050`
- **用途**: 东方财富网-经济数据-工业增加值增长

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `columns` | `"REPORT_DATE,TIME,BASE_SAME,BASE_ACCUMULATE"` | 返回字段，ALL=全部 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `pageSize` | `"2000"` | 每页条数 |
| `sortColumns` | `"REPORT_DATE"` | 排序字段 |
| `sortTypes` | `"-1"` | -1降序 1升序 |
| `source` | `"WEB"` | 客户端标识 |
| `client` | `"WEB"` | 客户端标识 |
| `reportName` | `"RPT_ECONOMY_INDUS_GROW"` | 数据集标识 |
| `p` | `"1"` |  |
| `pageNo` | `"1"` |  |
| `pageNum` | `"1"` |  |

**返回字段**（按列序，共 4 列）

| 列序 | 字段含义 |
|---|---|
| 0 | 发布时间 |
| 1 | 月份 |
| 2 | 同比增长 |
| 3 | 累计增长 |

---

## 58. `RPT_ECONOMY_PMI`

- **akshare 入口**: `macro_china_pmi()`
- **源码**: `economic/macro_china.py:2621`
- **用途**: 东方财富-中国采购经理人指数

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `columns` | `"REPORT_DATE,TIME,MAKE_INDEX,MAKE_SAME,NMAKE_INDEX,NMAKE_SAME"` | 返回字段，ALL=全部 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `pageSize` | `"2000"` | 每页条数 |
| `sortColumns` | `"REPORT_DATE"` | 排序字段 |
| `sortTypes` | `"-1"` | -1降序 1升序 |
| `source` | `"WEB"` | 客户端标识 |
| `client` | `"WEB"` | 客户端标识 |
| `reportName` | `"RPT_ECONOMY_PMI"` | 数据集标识 |
| `p` | `"1"` |  |
| `pageNo` | `"1"` |  |
| `pageNum` | `"1"` |  |

**返回字段**（按列序，共 6 列）

| 列序 | 字段含义 |
|---|---|
| 1 | 月份 |
| 2 | 制造业-指数 |
| 3 | 制造业-同比增长 |
| 4 | 非制造业-指数 |
| 5 | 非制造业-同比增长 |

---

## 59. `RPT_ECONOMY_PPI`

- **akshare 入口**: `macro_china_ppi()`
- **源码**: `economic/macro_china.py:2576`
- **用途**: 东方财富-中国工业品出厂价格指数

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `columns` | `"REPORT_DATE,TIME,BASE,BASE_SAME,BASE_ACCUMULATE"` | 返回字段，ALL=全部 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `pageSize` | `"2000"` | 每页条数 |
| `sortColumns` | `"REPORT_DATE"` | 排序字段 |
| `sortTypes` | `"-1"` | -1降序 1升序 |
| `source` | `"WEB"` | 客户端标识 |
| `client` | `"WEB"` | 客户端标识 |
| `reportName` | `"RPT_ECONOMY_PPI"` | 数据集标识 |
| `p` | `"1"` |  |
| `pageNo` | `"1"` |  |
| `pageNum` | `"1"` |  |

**返回字段**（按列序，共 5 列）

| 列序 | 字段含义 |
|---|---|
| 1 | 月份 |
| 2 | 当月 |
| 3 | 当月同比增长 |
| 4 | 累计 |

---

## 60. `RPT_ECONOMY_RMB_LOAN`

- **akshare 入口**: `macro_china_new_financial_credit()`
- **源码**: `economic/macro_china.py:2141`
- **用途**: 中国-新增信贷数据

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `columns` | `"REPORT_DATE,TIME,RMB_LOAN,RMB_LOAN_SAME,RMB_LOAN_SEQUENTIAL,"` | 返回字段，ALL=全部 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `pageSize` | `"2000"` | 每页条数 |
| `sortColumns` | `"REPORT_DATE"` | 排序字段 |
| `sortTypes` | `"-1"` | -1降序 1升序 |
| `source` | `"WEB"` | 客户端标识 |
| `client` | `"WEB"` | 客户端标识 |
| `reportName` | `"RPT_ECONOMY_RMB_LOAN"` | 数据集标识 |
| `p` | `"1"` |  |
| `pageNo` | `"1"` |  |
| `pageNum` | `"1"` |  |

**返回字段**（按列序，共 7 列）

| 列序 | 字段含义 |
|---|---|
| 1 | 月份 |
| 2 | 当月 |
| 3 | 当月-同比增长 |
| 4 | 当月-环比增长 |
| 5 | 累计 |
| 6 | 累计-同比增长 |

---

## 61. `RPT_ECONOMY_STOCK_STATISTICS`

- **akshare 入口**: `macro_china_stock_market_cap()`
- **源码**: `economic/macro_china.py:2255`
- **用途**: 东方财富-全国股票交易统计表

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `reportName` | `"RPT_ECONOMY_STOCK_STATISTICS"` | 数据集标识 |
| `columns` | `"REPORT_DATE,TIME,TOTAL_SHARES_SH,TOTAL_MARKE_SH,DEAL_AMOUNT_SH,VOLUME_SH,HIGH_INDEX_SH,"` | 返回字段，ALL=全部 |
| `sortColumns` | `"REPORT_DATE"` | 排序字段 |
| `sortTypes` | `"-1"` | -1降序 1升序 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `pageSize` | `"1000"` | 每页条数 |
| `source` | `"WEB"` | 客户端标识 |
| `client` | `"WEB"` | 客户端标识 |

**返回字段**（按列序，共 14 列）

| 列序 | 字段含义 |
|---|---|
| 1 | 数据日期 |
| 2 | 发行总股本-上海 |
| 3 | 市价总值-上海 |
| 4 | 成交金额-上海 |
| 5 | 成交量-上海 |
| 6 | A股最高综合股价指数-上海 |
| 7 | A股最低综合股价指数-上海 |
| 8 | 发行总股本-深圳 |
| 9 | 市价总值-深圳 |
| 10 | 成交金额-深圳 |
| 11 | 成交量-深圳 |
| 12 | A股最高综合股价指数-深圳 |
| 13 | A股最低综合股价指数-深圳 |

---

## 62. `RPT_ECONOMY_TAX`

- **akshare 入口**: `macro_china_national_tax_receipts()`
- **源码**: `economic/macro_china.py:1205`
- **用途**: 中国-全国税收收入

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `columns` | `"REPORT_DATE,TIME,TAX_INCOME,TAX_INCOME_SAME,TAX_INCOME_SEQUENTIAL"` | 返回字段，ALL=全部 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `pageSize` | `"500"` | 每页条数 |
| `sortColumns` | `"REPORT_DATE"` | 排序字段 |
| `sortTypes` | `"-1"` | -1降序 1升序 |
| `source` | `"WEB"` | 客户端标识 |
| `client` | `"WEB"` | 客户端标识 |
| `reportName` | `"RPT_ECONOMY_TAX"` | 数据集标识 |
| `p` | `"1"` |  |
| `pageNo` | `"1"` |  |
| `pageNum` | `"1"` |  |

---

## 63. `RPT_ECONOMY_TOTAL_RETAIL`

- **akshare 入口**: `macro_china_consumer_goods_retail()`
- **源码**: `economic/macro_china.py:3179`
- **用途**: 东方财富-经济数据-社会消费品零售总额

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `columns` | `"REPORT_DATE,TIME,RETAIL_TOTAL,RETAIL_TOTAL_SAME,RETAIL_TOTAL_SEQUENTIAL,"` | 返回字段，ALL=全部 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `pageSize` | `"1000"` | 每页条数 |
| `sortColumns` | `"REPORT_DATE"` | 排序字段 |
| `sortTypes` | `"-1"` | -1降序 1升序 |
| `source` | `"WEB"` | 客户端标识 |
| `client` | `"WEB"` | 客户端标识 |
| `reportName` | `"RPT_ECONOMY_TOTAL_RETAIL"` | 数据集标识 |
| `p` | `"1"` |  |
| `pageNo` | `"1"` |  |
| `pageNum` | `"1"` |  |

**返回字段**（按列序，共 7 列）

| 列序 | 字段含义 |
|---|---|
| 1 | 月份 |
| 2 | 当月 |
| 3 | 同比增长 |
| 4 | 环比增长 |
| 5 | 累计 |
| 6 | 累计-同比增长 |

---

## 64. `RPT_EXECUTIVE_HOLD_DETAILS`

- **akshare 入口**: `stock_hold_management_detail_em()`
- **源码**: `stock/stock_hold_control_em.py:13`
- **用途**: 东方财富网-数据中心-特色数据-高管持股-董监高及相关人员持股变动明细

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `reportName` | `"RPT_EXECUTIVE_HOLD_DETAILS"` | 数据集标识 |
| `columns` | `"ALL"` | 返回字段，ALL=全部 |
| `quoteColumns` | `""` | 行情字段注入 |
| `filter` | `""` | 过滤表达式 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `pageSize` | `"5000"` | 每页条数 |
| `sortTypes` | `"-1,1,1"` | -1降序 1升序 |
| `sortColumns` | `"CHANGE_DATE,SECURITY_CODE,PERSON_NAME"` | 排序字段 |
| `source` | `"WEB"` | 客户端标识 |
| `client` | `"WEB"` | 客户端标识 |
| `p` | `"1"` |  |
| `pageNo` | `"1"` |  |
| `pageNum` | `"1"` |  |

**字段重命名**（英文原始名 → 中文含义）

| 原始字段 | 含义 |
|---|---|
| `SECURITY_CODE` | 代码 |
| `DERIVE_SECURITY_CODE` | - |
| `SECURITY_NAME` | 名称 |
| `CHANGE_DATE` | 日期 |
| `PERSON_NAME` | 变动人 |
| `CHANGE_SHARES` | 变动股数 |
| `AVERAGE_PRICE` | 成交均价 |
| `CHANGE_AMOUNT` | 变动金额 |
| `CHANGE_REASON` | 变动原因 |
| `CHANGE_RATIO` | 变动比例 |
| `CHANGE_AFTER_HOLDNUM` | 变动后持股数 |
| `HOLD_TYPE` | 持股种类 |
| `DSE_PERSON_NAME` | 董监高人员姓名 |
| `POSITION_NAME` | 职务 |
| `PERSON_DSE_RELATION` | 变动人与董监高的关系 |
| `ORG_CODE` | - |
| `GGEID` | - |
| `BEGIN_HOLD_NUM` | 开始时持有 |
| `END_HOLD_NUM` | 结束后持有 |

---

## 65. `RPT_F10_EH_FREEHOLDERS`

- **akshare 入口**: `stock_gdfx_free_holding_detail_em(date: str = "20210930")`
- **源码**: `stock_feature/stock_gdfx_em.py:504`
- **用途**: 东方财富网-数据中心-股东分析-股东持股明细-十大流通股东

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `sortColumns` | `"UPDATE_DATE,SECURITY_CODE,HOLDER_RANK"` | 排序字段 |
| `sortTypes` | `"-1,1,1"` | -1降序 1升序 |
| `pageSize` | `"2000"` | 每页条数 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `reportName` | `"RPT_F10_EH_FREEHOLDERS"` | 数据集标识 |
| `columns` | `"ALL"` | 返回字段，ALL=全部 |
| `source` | `"WEB"` | 客户端标识 |
| `client` | `"WEB"` | 客户端标识 |
| `filter` | `f"(END_DATE='{'-'.join([date[:4], date[4:6], date[6:]])}')"` | 过滤表达式 |

**字段重命名**（英文原始名 → 中文含义）

| 原始字段 | 含义 |
|---|---|
| `index` | 序号 |
| `HOLDER_NAME` | 股东名称 |
| `HOLDER_TYPE` | 股东类型 |
| `SHARES_TYPE` | 股份类型 |
| `HOLDER_RANK` | 股东排名 |
| `SECURITY_CODE` | 股票代码 |
| `SECURITY_NAME_ABBR` | 股票简称 |
| `HOLD_NUM` | 期末持股-数量 |
| `FREE_HOLDNUM_RATIO` | 期末持股-持股占流通股比 |
| `XZCHANGE` | 期末持股-数量变化 |
| `CHANGE_RATIO` | 期末持股-数量变化比例 |
| `HOLDNUM_CHANGE_NAME` | 期末持股-持股变动 |
| `HOLDER_MARKET_CAP` | 期末持股-流通市值 |
| `END_DATE` | 报告期 |
| `UPDATE_DATE` | 公告日 |
| `REPORT_DATE_NAME` | 报告名称 |

---

## 66. `RPT_FCI_PERFORMANCEE`

- **akshare 入口**: `stock_yjkb_em(date: str = "20211231")`
- **源码**: `stock_feature/stock_yjyg_em.py:16`
- **用途**: 东方财富-数据中心-年报季报-业绩快报

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `sortColumns` | `"UPDATE_DATE,SECURITY_CODE"` | 排序字段 |
| `sortTypes` | `"-1,-1"` | -1降序 1升序 |
| `pageSize` | `"500"` | 每页条数 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `reportName` | `"RPT_FCI_PERFORMANCEE"` | 数据集标识 |
| `columns` | `"ALL"` | 返回字段，ALL=全部 |
| `filter` | `f"""(SECURITY_TYPE_CODE in ("058001001","058001008"))(TRADE_MARKET_CODE!="069001017")` | 过滤表达式 |

**返回字段**（按列序，共 29 列）

| 列序 | 字段含义 |
|---|---|
| 0 | 序号 |
| 1 | 股票代码 |
| 2 | 股票简称 |
| 3 | 市场板块 |
| 5 | 证券类型 |
| 7 | 公告日期 |
| 9 | 每股收益 |
| 10 | 营业收入-营业收入 |
| 11 | 营业收入-去年同期 |
| 12 | 净利润-净利润 |
| 13 | 净利润-去年同期 |
| 14 | 每股净资产 |
| 15 | 净资产收益率 |
| 16 | 营业收入-同比增长 |
| 17 | 净利润-同比增长 |
| 18 | 营业收入-季度环比增长 |
| 19 | 净利润-季度环比增长 |
| 20 | 所处行业 |

---

## 67. `RPT_FREEHOLDERS_BASIC_INFO`

- **akshare 入口**: `stock_gdfx_free_holding_change_em(date: str = "20210930")`
- **源码**: `stock_feature/stock_gdfx_em.py:221`
- **用途**: 东方财富网-数据中心-股东分析-股东持股变动统计-十大流通股东

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `sortColumns` | `"HOLDER_NUM,HOLDER_NEW"` | 排序字段 |
| `sortTypes` | `"-1,-1"` | -1降序 1升序 |
| `pageSize` | `"500"` | 每页条数 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `reportName` | `"RPT_FREEHOLDERS_BASIC_INFO"` | 数据集标识 |
| `columns` | `"ALL"` | 返回字段，ALL=全部 |
| `source` | `"WEB"` | 客户端标识 |
| `client` | `"WEB"` | 客户端标识 |
| `filter` | `f"(END_DATE='{'-'.join([date[:4], date[4:6], date[6:]])}')"` | 过滤表达式 |

**返回字段**（按列序，共 21 列）

| 列序 | 字段含义 |
|---|---|
| 0 | 序号 |
| 3 | 股东名称 |
| 5 | 股东类型 |
| 9 | 期末持股只数统计-总持有 |
| 10 | 期末持股只数统计-新进 |
| 11 | 期末持股只数统计-增加 |
| 12 | 期末持股只数统计-减少 |
| 13 | 期末持股只数统计-不变 |
| 15 | 流通市值统计 |
| 16 | 持有个股 |

---

## 68. `RPT_FUTUOPT_GOLDSIL`

- **akshare 入口**: `futures_comex_inventory(symbol: str = "黄金")`
- **源码**: `futures/futures_comex_em.py:14`
- **用途**: 东方财富网-数据中心-期货期权-COMEX库存数据

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `sortColumns` | `"REPORT_DATE"` | 排序字段 |
| `sortTypes` | `"-1"` | -1降序 1升序 |
| `pageSize` | `"500"` | 每页条数 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `reportName` | `"RPT_FUTUOPT_GOLDSIL"` | 数据集标识 |
| `columns` | `"ALL"` | 返回字段，ALL=全部 |
| `quoteColumns` | `""` | 行情字段注入 |
| `source` | `"WEB"` | 客户端标识 |
| `client` | `"WEB"` | 客户端标识 |
| `filter` | `f'(INDICATOR_ID1="{symbol_map[symbol]}")(@STORAGE_TON<>"NULL")'` | 过滤表达式 |

**字段重命名**（英文原始名 → 中文含义）

| 原始字段 | 含义 |
|---|---|
| `index` | 序号 |
| `REPORT_DATE` | 日期 |
| `INDICATOR_NAME` | - |
| `INDICATOR_ID1` | - |

---

## 69. `RPT_FUTU_POSITIONCODE`

- **akshare 入口**: `futures_inventory_em(symbol: str = "a")`
- **源码**: `futures/futures_inventory_em.py:13`
- **用途**: 东方财富网-数据中心-期货库存数据

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `reportName` | `"RPT_FUTU_POSITIONCODE"` | 数据集标识 |
| `columns` | `"TRADE_MARKET_CODE,TRADE_CODE,TRADE_TYPE"` | 返回字段，ALL=全部 |
| `filter` | `'(IS_MAINCODE="1")'` | 过滤表达式 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `pageSize` | `"500"` | 每页条数 |
| `source` | `"WEB"` | 客户端标识 |
| `client` | `"WEB"` | 客户端标识 |

---

## 70. `RPT_GDZY_ZYJG_SUM`

- **akshare 入口**: `stock_gpzy_distribute_statistics_company_em()`
- **源码**: `stock_feature/stock_gpzy_em.py:311`
- **用途**: 东方财富网-数据中心-特色数据-股权质押-质押机构分布统计-证券公司

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `sortColumns` | `"ORG_NUM"` | 排序字段 |
| `sortTypes` | `"-1"` | -1降序 1升序 |
| `pageSize` | `"500"` | 每页条数 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `reportName` | `"RPT_GDZY_ZYJG_SUM"` | 数据集标识 |
| `columns` | `"ALL"` | 返回字段，ALL=全部 |
| `quoteColumns` | `""` | 行情字段注入 |
| `source` | `"WEB"` | 客户端标识 |
| `client` | `"WEB"` | 客户端标识 |
| `filter` | `'(PFORG_TYPE="证券")'` | 过滤表达式 |

**返回字段**（按列序，共 15 列）

| 列序 | 字段含义 |
|---|---|
| 0 | 序号 |
| 5 | 质押机构 |
| 7 | 质押公司数量 |
| 8 | 质押笔数 |
| 9 | 质押数量 |
| 10 | 未达预警线比例 |
| 11 | 达到预警线未达平仓线比例 |
| 12 | 达到平仓线比例 |

---

## 71. `RPT_GENERALMEETING_DETAIL`

- **akshare 入口**: `stock_gddh_em()`
- **源码**: `stock_feature/stock_gddh_em.py:13`
- **用途**: 东方财富网-数据中心-股东大会

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `sortColumns` | `"NOTICE_DATE"` | 排序字段 |
| `sortTypes` | `"-1"` | -1降序 1升序 |
| `pageSize` | `"500"` | 每页条数 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `reportName` | `"RPT_GENERALMEETING_DETAIL"` | 数据集标识 |
| `columns` | `"SECURITY_CODE,SECURITY_NAME_ABBR,MEETING_TITLE,START_ADJUST_DATE,EQUITY_RECORD_DATE,"` | 返回字段，ALL=全部 |
| `filter` | `'(IS_LASTDATE="1")'` | 过滤表达式 |
| `source` | `"WEB"` | 客户端标识 |
| `client` | `"WEB"` | 客户端标识 |

**字段重命名**（英文原始名 → 中文含义）

| 原始字段 | 含义 |
|---|---|
| `SECURITY_CODE` | 代码 |
| `SECURITY_NAME_ABBR` | 简称 |
| `MEETING_TITLE` | 股东大会名称 |
| `START_ADJUST_DATE` | 召开开始日 |
| `EQUITY_RECORD_DATE` | 股权登记日 |
| `ONSITE_RECORD_DATE` | 现场登记日 |
| `DECISION_NOTICE_DATE` | 决议公告日 |
| `NOTICE_DATE` | 公告日 |
| `WEB_START_DATE` | 网络投票时间-开始日 |
| `WEB_END_DATE` | 网络投票时间-结束日 |
| `SERIAL_NUM` | 序列号 |
| `PROPOSAL` | 提案 |

---

## 72. `RPT_GOODWILL_INDUSTATISTICS`

- **akshare 入口**: `stock_sy_hy_em(date: str = "20240930")`
- **源码**: `stock_feature/stock_sy_em.py:385`
- **用途**: 东方财富网-数据中心-特色数据-商誉-行业商誉

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `sortColumns` | `"SUMSHEQUITY_RATIO"` | 排序字段 |
| `sortTypes` | `"-1"` | -1降序 1升序 |
| `pageSize` | `"5000"` | 每页条数 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `columns` | `"ALL"` | 返回字段，ALL=全部 |
| `token` | `"894050c76af8597a853f5b408b759f5d"` | 固定令牌 |
| `reportName` | `"RPT_GOODWILL_INDUSTATISTICS"` | 数据集标识 |
| `filter` | `f"""(REPORT_DATE='{"-".join([date[:4], date[4:6], date[6:]])}')"""` | 过滤表达式 |

**字段重命名**（英文原始名 → 中文含义）

| 原始字段 | 含义 |
|---|---|
| `REPORT_DATE` | 数据日期 |
| `INDUSTRY_NAME` | 行业名称 |
| `INDUSTRY_CODE` | - |
| `ORG_NUM` | 公司家数 |
| `GOODWILL` | 商誉规模 |
| `GOODWILL_CHANGE` | - |
| `SUMSHEQUITY` | 净资产 |
| `SUMSHEQUITY_RATIO` | 商誉规模占净资产规模比例 |
| `SE_CHANGE_RATIO` | - |
| `PARENTNETPROFIT` | 净利润规模 |
| `PNP_CHANGE_RATIO` | - |

---

## 73. `RPT_GOODWILL_MARKETSTATISTICS`

- **akshare 入口**: `stock_sy_profile_em()`
- **源码**: `stock_feature/stock_sy_em.py:18`
- **用途**: 东方财富网-数据中心-特色数据-商誉-A股商誉市场概况

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `sortColumns` | `"REPORT_DATE"` | 排序字段 |
| `sortTypes` | `"-1"` | -1降序 1升序 |
| `pageSize` | `"5000"` | 每页条数 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `reportName` | `"RPT_GOODWILL_MARKETSTATISTICS"` | 数据集标识 |
| `token` | `"894050c76af8597a853f5b408b759f5d"` | 固定令牌 |
| `columns` | `"ALL"` | 返回字段，ALL=全部 |
| `filter` | `"""((GOODWILL_STATE="1")( | IMPAIRMENT_STATE="1"))(TRADE_BOARD="all")"""` | 过滤表达式 |

**返回字段**（按列序，共 11 列）

| 列序 | 字段含义 |
|---|---|
| 1 | 报告期 |
| 2 | 商誉 |
| 3 | 商誉减值 |
| 4 | 净资产 |
| 5 | 商誉占净资产比例 |
| 6 | 商誉减值占净资产比例 |
| 7 | 净利润规模 |
| 8 | 商誉减值占净利润比例 |

---

## 74. `RPT_GOODWILL_STOCKDETAILS`

- **akshare 入口**: `stock_sy_jz_em(date: str = "20240630")`
- **源码**: `stock_feature/stock_sy_em.py:192`
- **用途**: 东方财富网-数据中心-特色数据-商誉-个股商誉减值明细

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `sortColumns` | `"GOODWILL_CHANGE"` | 排序字段 |
| `sortTypes` | `"-1"` | -1降序 1升序 |
| `pageSize` | `"5000"` | 每页条数 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `columns` | `"ALL"` | 返回字段，ALL=全部 |
| `token` | `"894050c76af8597a853f5b408b759f5d"` | 固定令牌 |
| `reportName` | `"RPT_GOODWILL_STOCKDETAILS"` | 数据集标识 |
| `filter` | `f"""(REPORT_DATE='{"-".join([date[:4], date[4:6], date[6:]])}')"""` | 过滤表达式 |

**字段重命名**（英文原始名 → 中文含义）

| 原始字段 | 含义 |
|---|---|
| `index` | 序号 |
| `SECUCODE` | - |
| `SECURITY_CODE` | 股票代码 |
| `SECURITY_NAME_ABBR` | 股票简称 |
| `ORG_CODE` | - |
| `LISTING_DATE` | - |
| `LISTING_STATE` | - |
| `TRADE_BOARD` | 交易市场 |
| `GOODWILL` | 商誉 |
| `DATE_TYPE` | - |
| `REPORT_TYPE_CODE` | - |
| `DATA_ADJUST_TYPE` | - |
| `NOTICE_DATE` | 公告日期 |
| `REPORT_DATE` | 数据日期 |
| `GOODWILL_PRE` | - |
| `GOODWILL_CHANGE` | 商誉减值 |
| `SUMSHEQUITY` | - |
| `SUMSHEQUITY_RATIO` | 商誉占净资产比例 |
| `SE_CHANGE_RATIO` | 商誉减值占净资产比例 |
| `PARENTNETPROFIT` | 净利润 |
| `PNP_CHANGE_RATIO` | 商誉减值占净利润比例 |
| `PNP_YOY_RATIO` | - |
| `INDUSTRY_CFT` | - |
| `INDUSTRY_CFTCODE` | - |
| `IS_SHOW` | - |
| `MAXREPORTDATE` | - |

---

## 75. `RPT_GOODWILL_STOCKPREDICT`

- **akshare 入口**: `stock_sy_yq_em(date: str = "20240630")`
- **源码**: `stock_feature/stock_sy_em.py:83`
- **用途**: 东方财富网-数据中心-特色数据-商誉-商誉减值预期明细

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `sortColumns` | `"NOTICE_DATE,SECURITY_CODE"` | 排序字段 |
| `sortTypes` | `"-1,-1"` | -1降序 1升序 |
| `pageSize` | `"5000"` | 每页条数 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `columns` | `"ALL"` | 返回字段，ALL=全部 |
| `token` | `"894050c76af8597a853f5b408b759f5d"` | 固定令牌 |
| `reportName` | `"RPT_GOODWILL_STOCKPREDICT"` | 数据集标识 |
| `filter` | `f"""(REPORT_DATE='{"-".join([date[:4], date[4:6], date[6:]])}')"""` | 过滤表达式 |

**字段重命名**（英文原始名 → 中文含义）

| 原始字段 | 含义 |
|---|---|
| `index` | 序号 |
| `SECUCODE` | - |
| `SECURITY_CODE` | 股票代码 |
| `ORG_CODE` | - |
| `SECURITY_NAME_ABBR` | 股票简称 |
| `TRADE_MARKET` | 交易市场 |
| `INDUSTRY_NAME` | - |
| `INDUSTRY_CODE` | - |
| `NOTICE_DATE` | 公告日期 |
| `REPORT_DATE` | 数据日期 |
| `PE_REPORT_DATE` | - |
| `PREDICT_NETPROFIT_LOWER` | 预计净利润-下限 |
| `PREDICT_NETPROFIT_UPPER` | 预计净利润-上限 |
| `PERFORM_CHANGE_UPPER` | 业绩变动幅度-上限 |
| `PERFORM_CHANGE_LOWER` | 业绩变动幅度-下限 |
| `PERFORM_CHANGE` | - |
| `PERFORM_CHANGE_EXPLAIN` | 业绩变动原因 |
| `PREDICT_TYPE` | - |
| `PREDICT_INDICATOR_CODE` | - |
| `PREDICT_PERIOD` | - |
| `PE_SAMEREPORT_NETPROFIT` | 上年度同期净利润 |
| `NETPROFIT` | - |
| `PE_GOODWILL` | 上年商誉 |
| `NEWEST_REPORT_DATE` | 最新商誉报告期 |
| `NEWEST_GOODWILL` | 最新一期商誉 |
| `PE_SAMEREPORT_DATE` | - |

---

## 76. `RPT_HOLDERNUMLATEST`

- **akshare 入口**: `stock_zh_a_gdhs(symbol: str = "20230930")`
- **源码**: `stock_feature/stock_gdhs.py:14`
- **用途**: 东方财富网-数据中心-特色数据-股东户数

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `sortColumns` | `"HOLD_NOTICE_DATE,SECURITY_CODE"` | 排序字段 |
| `sortTypes` | `"-1,-1"` | -1降序 1升序 |
| `pageSize` | `"500"` | 每页条数 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `reportName` | `"RPT_HOLDERNUMLATEST"` | 数据集标识 |
| `columns` | `"SECURITY_CODE,SECURITY_NAME_ABBR,END_DATE,INTERVAL_CHRATE,AVG_MARKET_CAP,AVG_HOLD_NUM,"` | 返回字段，ALL=全部 |
| `quoteColumns` | `"f2,f3"` | 行情字段注入 |
| `source` | `"WEB"` | 客户端标识 |
| `client` | `"WEB"` | 客户端标识 |

**返回字段**（按列序，共 16 列）

| 列序 | 字段含义 |
|---|---|
| 0 | 代码 |
| 1 | 名称 |
| 2 | 股东户数统计截止日-本次 |
| 3 | 区间涨跌幅 |
| 4 | 户均持股市值 |
| 5 | 户均持股数量 |
| 6 | 总市值 |
| 7 | 总股本 |
| 8 | 公告日期 |
| 9 | 股东户数-本次 |
| 10 | 股东户数-上次 |
| 11 | 股东户数-增减 |
| 12 | 股东户数-增减比例 |
| 13 | 股东户数统计截止日-上次 |
| 14 | 最新价 |
| 15 | 涨跌幅 |

---

## 77. `RPT_HOLDERNUM_DET`

- **akshare 入口**: `stock_zh_a_gdhs_detail_em(symbol: str = "000001")`
- **源码**: `stock_feature/stock_gdhs.py:129`
- **用途**: 东方财富网-数据中心-特色数据-股东户数详情

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `sortColumns` | `"END_DATE"` | 排序字段 |
| `sortTypes` | `"-1"` | -1降序 1升序 |
| `pageSize` | `"500"` | 每页条数 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `reportName` | `"RPT_HOLDERNUM_DET"` | 数据集标识 |
| `columns` | `"SECURITY_CODE,SECURITY_NAME_ABBR,CHANGE_SHARES,CHANGE_REASON,END_DATE,INTERVAL_CHRATE,"` | 返回字段，ALL=全部 |
| `quoteColumns` | `"f2,f3"` | 行情字段注入 |
| `filter` | `f'(SECURITY_CODE="{symbol}")'` | 过滤表达式 |
| `source` | `"WEB"` | 客户端标识 |
| `client` | `"WEB"` | 客户端标识 |

**返回字段**（按列序，共 18 列）

| 列序 | 字段含义 |
|---|---|
| 0 | 代码 |
| 1 | 名称 |
| 2 | 股本变动 |
| 3 | 股本变动原因 |
| 4 | 股东户数统计截止日 |
| 5 | 区间涨跌幅 |
| 6 | 户均持股市值 |
| 7 | 户均持股数量 |
| 8 | 总市值 |
| 9 | 总股本 |
| 10 | 股东户数公告日期 |
| 11 | 股东户数-本次 |
| 12 | 股东户数-上次 |
| 13 | 股东户数-增减 |
| 14 | 股东户数-增减比例 |

---

## 78. `RPT_HOLDERS_BASIC_INFO`

- **akshare 入口**: `stock_gdfx_holding_change_em(date: str = "20210930")`
- **源码**: `stock_feature/stock_gdfx_em.py:312`
- **用途**: 东方财富网-数据中心-股东分析-股东持股变动统计-十大股东

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `sortColumns` | `"HOLDER_NUM,HOLDER_NEW"` | 排序字段 |
| `sortTypes` | `"-1,-1"` | -1降序 1升序 |
| `pageSize` | `"500"` | 每页条数 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `reportName` | `"RPT_HOLDERS_BASIC_INFO"` | 数据集标识 |
| `columns` | `"ALL"` | 返回字段，ALL=全部 |
| `source` | `"WEB"` | 客户端标识 |
| `client` | `"WEB"` | 客户端标识 |
| `filter` | `f"(END_DATE='{'-'.join([date[:4], date[4:6], date[6:]])}')"` | 过滤表达式 |

**返回字段**（按列序，共 20 列）

| 列序 | 字段含义 |
|---|---|
| 0 | 序号 |
| 3 | 股东名称 |
| 5 | 股东类型 |
| 9 | 期末持股只数统计-总持有 |
| 10 | 期末持股只数统计-新进 |
| 11 | 期末持股只数统计-增加 |
| 12 | 期末持股只数统计-减少 |
| 13 | 期末持股只数统计-不变 |
| 16 | 持有个股 |
| 17 | 流通市值统计 |

---

## 79. `RPT_IMP_INTRESTRATEN`

- **akshare 入口**: `rate_interbank(market: str = "上海银行同业拆借市场",
    symbol: str = "Shibor人民币",
    indicator: str = "隔夜",)`
- **源码**: `interest_rate/interbank_rate_em.py:13`
- **用途**: 东方财富-拆借利率一览-具体市场的具体品种的具体指标的拆借利率数据

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `reportName` | `"RPT_IMP_INTRESTRATEN"` | 数据集标识 |
| `columns` | `"REPORT_DATE,REPORT_PERIOD,IR_RATE,CHANGE_RATE,INDICATOR_ID,"` | 返回字段，ALL=全部 |
| `quoteColumns` | `""` | 行情字段注入 |
| `filter` | `f"""(MARKET_CODE="{market_map[market]}")(CURRENCY_CODE="{symbol_map[symbol]}")` | 过滤表达式 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `pageSize` | `"500"` | 每页条数 |
| `sortTypes` | `"-1"` | -1降序 1升序 |
| `sortColumns` | `"REPORT_DATE"` | 排序字段 |
| `source` | `"WEB"` | 客户端标识 |
| `client` | `"WEB"` | 客户端标识 |
| `p` | `"1"` |  |
| `pageNo` | `"1"` |  |
| `pageNum` | `"1"` |  |

**返回字段**（按列序，共 10 列）

| 列序 | 字段含义 |
|---|---|
| 0 | 报告日 |
| 2 | 利率 |
| 3 | 涨跌 |

---

## 80. `RPT_INDUSTRY_INDEX`

- **akshare 入口**: `macro_china_bank_financing()`
- **源码**: `economic/macro_china.py:1240`
- **用途**: 银行理财产品发行数量

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `sortColumns` | `"REPORT_DATE"` | 排序字段 |
| `sortTypes` | `"-1"` | -1降序 1升序 |
| `pageSize` | `"1000"` | 每页条数 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `reportName` | `"RPT_INDUSTRY_INDEX"` | 数据集标识 |
| `columns` | `"REPORT_DATE,INDICATOR_VALUE,CHANGE_RATE,CHANGERATE_3M,CHANGERATE_6M,CHANGERATE_1Y,"` | 返回字段，ALL=全部 |
| `filter` | `'(INDICATOR_ID="EMI01516267")'` | 过滤表达式 |
| `source` | `"WEB"` | 客户端标识 |
| `client` | `"WEB"` | 客户端标识 |

**返回字段**（按列序，共 8 列）

| 列序 | 字段含义 |
|---|---|
| 0 | 日期 |
| 1 | 最新值 |
| 2 | 涨跌幅 |
| 3 | 近3月涨跌幅 |
| 4 | 近6月涨跌幅 |
| 5 | 近1年涨跌幅 |
| 6 | 近2年涨跌幅 |
| 7 | 近3年涨跌幅 |

---

## 81. `RPT_IPO_ALLOTMENT`

- **akshare 入口**: `stock_pg_em()`
- **源码**: `stock_feature/stock_zf_pg.py:98`
- **用途**: 东方财富网-数据中心-新股数据-配股

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `sortColumns` | `"EQUITY_RECORD_DATE"` | 排序字段 |
| `sortTypes` | `"-1"` | -1降序 1升序 |
| `pageSize` | `"50000"` | 每页条数 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `reportName` | `"RPT_IPO_ALLOTMENT"` | 数据集标识 |
| `columns` | `"ALL"` | 返回字段，ALL=全部 |
| `quoteColumns` | `"f2~01~SECURITY_CODE~NEW_PRICE"` | 行情字段注入 |
| `quoteType` | `"0"` |  |
| `source` | `"WEB"` | 客户端标识 |
| `client` | `"WEB"` | 客户端标识 |

**返回字段**（按列序，共 23 列）

| 列序 | 字段含义 |
|---|---|
| 2 | 股票代码 |
| 4 | 股票简称 |
| 5 | 配售代码 |
| 7 | 配股比例 |
| 8 | 配股价 |
| 9 | 配股前总股本 |
| 10 | 配股数量 |
| 11 | 配股后总股本 |
| 12 | 股权登记日 |
| 13 | 缴款起始日期 |
| 14 | 缴款截止日期 |
| 15 | 上市日 |
| 22 | 最新价 |

---

## 82. `RPT_IPO_DECORGNEWEST`

- **akshare 入口**: `stock_ipo_declare_em()`
- **源码**: `stock_fundamental/stock_ipo_declare.py:15`
- **用途**: 东方财富网-数据中心-新股数据-首发申报企业信息

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `sortColumns` | `"END_DATE,SECURITY_CODE"` | 排序字段 |
| `sortTypes` | `"-1,-1"` | -1降序 1升序 |
| `pageSize` | `"500"` | 每页条数 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `reportName` | `"RPT_IPO_DECORGNEWEST"` | 数据集标识 |
| `columns` | `"DECLARE_ORG,STATE,REG_ADDRESS,RECOMMEND_ORG,LAW_FIRM,ACCOUNT_FIRM,IS_SUBMIT,"` | 返回字段，ALL=全部 |
| `source` | `"WEB"` | 客户端标识 |
| `client` | `"WEB"` | 客户端标识 |

**字段重命名**（英文原始名 → 中文含义）

| 原始字段 | 含义 |
|---|---|
| `index` | 序号 |
| `DECLARE_ORG` | 企业名称 |
| `STATE` | 最新状态 |
| `REG_ADDRESS` | 注册地 |
| `RECOMMEND_ORG` | 保荐机构 |
| `LAW_FIRM` | 律师事务所 |
| `ACCOUNT_FIRM` | 会计师事务所 |
| `PREDICT_LISTING_MARKET` | 拟上市地点 |
| `END_DATE` | 更新日期 |
| `INFO_CODE` | 招股说明书 |

---

## 83. `RPT_IPO_INFOALLNEW`

- **akshare 入口**: `stock_register_all_em()`
- **源码**: `stock_fundamental/stock_register_em.py:15`
- **用途**: 东方财富网-数据中心-新股数据-IPO审核信息-全部

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `sortColumns` | `"UPDATE_DATE,ORG_CODE"` | 排序字段 |
| `sortTypes` | `"-1,-1"` | -1降序 1升序 |
| `pageSize` | `"500"` | 每页条数 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `reportName` | `"RPT_IPO_INFOALLNEW"` | 数据集标识 |
| `columns` | `"SECURITY_CODE,STATE,REG_ADDRESS,INFO_CODE,CSRC_INDUSTRY,ACCEPT_DATE,DECLARE_ORG,"` | 返回字段，ALL=全部 |
| `source` | `"WEB"` | 客户端标识 |
| `client` | `"WEB"` | 客户端标识 |

**字段重命名**（英文原始名 → 中文含义）

| 原始字段 | 含义 |
|---|---|
| `index` | 序号 |
| `DECLARE_ORG` | 企业名称 |
| `STATE` | 最新状态 |
| `REG_ADDRESS` | 注册地 |
| `CSRC_INDUSTRY` | 行业 |
| `RECOMMEND_ORG` | 保荐机构 |
| `LAW_FIRM` | 律师事务所 |
| `ACCOUNT_FIRM` | 会计师事务所 |
| `UPDATE_DATE` | 更新日期 |
| `ACCEPT_DATE` | 受理日期 |
| `PREDICT_LISTING_MARKET` | 拟上市地点 |
| `INFO_CODE` | 招股说明书 |

---

## 84. `RPT_IPO_REVIEW`

- **akshare 入口**: `stock_ipo_review_em()`
- **源码**: `stock_fundamental/stock_ipo_review.py:17`
- **用途**: 东方财富网-数据中心-新股申购-新股上会信息

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `sortColumns` | `"REVIEW_DATE,ORG_CODE"` | 排序字段 |
| `sortTypes` | `"-1,-1"` | -1降序 1升序 |
| `pageSize` | `"500"` | 每页条数 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `reportName` | `"RPT_IPO_REVIEW"` | 数据集标识 |
| `columns` | `"ALL"` | 返回字段，ALL=全部 |
| `source` | `"WEB"` | 客户端标识 |
| `client` | `"WEB"` | 客户端标识 |

**字段重命名**（英文原始名 → 中文含义）

| 原始字段 | 含义 |
|---|---|
| `ORG_NAME` | 企业名称 |
| `SECURITY_NAME_ABBR` | 股票简称 |
| `SECURITY_CODE` | 股票代码 |
| `TRADE_MARKET` | 上市板块 |
| `REVIEW_DATE` | 上会日期 |
| `REVIEW_STATE` | 审核状态 |
| `REVIEW_MEMBER` | 发审委委员 |
| `LEAD_UNDERWRITER` | 主承销商 |
| `ISSUE_NUM` | 发行数量(股) |
| `FINANCE_AMT_UPPER` | 拟融资额(元) |
| `NOTICE_DATE` | 公告日期 |
| `LISTING_DATE` | 上市日期 |

---

## 85. `RPT_IPO_TUTRECORD`

- **akshare 入口**: `stock_ipo_tutor_em()`
- **源码**: `stock_fundamental/stock_ipo_tutor.py:17`
- **用途**: 东方财富网-数据中心-新股数据-IPO辅导信息

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `sortColumns` | `"RECORD_DATE,TUTOR_OBJECT"` | 排序字段 |
| `sortTypes` | `"-1,-1"` | -1降序 1升序 |
| `pageSize` | `"500"` | 每页条数 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `reportName` | `"RPT_IPO_TUTRECORD"` | 数据集标识 |
| `columns` | `"TUTOR_OBJECT,ORG_CODE,TUTOR_ORG_CODE,TUTOR_ORG,TUTOR_PROCESS_STATE,REPORT_TYPE,"` | 返回字段，ALL=全部 |
| `source` | `"WEB"` | 客户端标识 |
| `client` | `"WEB"` | 客户端标识 |

**字段重命名**（英文原始名 → 中文含义）

| 原始字段 | 含义 |
|---|---|
| `TUTOR_OBJECT` | 企业名称 |
| `TUTOR_ORG` | 辅导机构 |
| `TUTOR_PROCESS_STATE` | 辅导状态 |
| `REPORT_TYPE` | 报告类型 |
| `DISPATCH_ORG` | 派出机构 |
| `REPORT_TITLE` | 报告标题 |
| `RECORD_DATE` | 备案日期 |

---

## 86. `RPT_KCB_IPO`

- **akshare 入口**: `stock_register_db()`
- **源码**: `stock_fundamental/stock_register_em.py:458`
- **用途**: 东方财富网-数据中心-新股数据-IPO审核信息-达标企业

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `sortColumns` | `"NOTICE_DATE,SECURITY_CODE"` | 排序字段 |
| `sortTypes` | `"-1,-1"` | -1降序 1升序 |
| `pageSize` | `"500"` | 每页条数 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `reportName` | `"RPT_KCB_IPO"` | 数据集标识 |
| `columns` | `"KCB_LB"` | 返回字段，ALL=全部 |
| `source` | `"WEB"` | 客户端标识 |
| `client` | `"WEB"` | 客户端标识 |
| `filter` | `'(ORG_TYPE_CODE="03")'` | 过滤表达式 |

**字段重命名**（英文原始名 → 中文含义）

| 原始字段 | 含义 |
|---|---|
| `index` | 序号 |
| `ORG_NAME` | 企业名称 |

---

## 87. `RPT_LHB_BOARDDATE`

- **akshare 入口**: `stock_lhb_stock_detail_date_em(symbol: str = "600077")`
- **源码**: `stock_feature/stock_lhb_em.py:722`
- **用途**: 东方财富网-数据中心-龙虎榜单-个股龙虎榜详情-日期

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `reportName` | `"RPT_LHB_BOARDDATE"` | 数据集标识 |
| `columns` | `"SECURITY_CODE,TRADE_DATE,TR_DATE"` | 返回字段，ALL=全部 |
| `filter` | `f'(SECURITY_CODE="{symbol}")'` | 过滤表达式 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `pageSize` | `"1000"` | 每页条数 |
| `sortTypes` | `"-1"` | -1降序 1升序 |
| `sortColumns` | `"TRADE_DATE"` | 排序字段 |
| `source` | `"WEB"` | 客户端标识 |
| `client` | `"WEB"` | 客户端标识 |

**返回字段**（按列序，共 4 列）

| 列序 | 字段含义 |
|---|---|
| 0 | 序号 |
| 1 | 股票代码 |
| 2 | 交易日 |

---

## 88. `RPT_LICO_FN_CPD`

- **akshare 入口**: `stock_yjbb_em(date: str = "20200331")`
- **源码**: `stock_feature/stock_yjbb_em.py:15`
- **用途**: 东方财富-数据中心-年报季报-业绩快报-业绩报表

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `sortColumns` | `"UPDATE_DATE,SECURITY_CODE"` | 排序字段 |
| `sortTypes` | `"-1,-1"` | -1降序 1升序 |
| `pageSize` | `"500"` | 每页条数 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `reportName` | `"RPT_LICO_FN_CPD"` | 数据集标识 |
| `columns` | `"ALL"` | 返回字段，ALL=全部 |
| `filter` | `f"(REPORTDATE='{'-'.join([date[:4], date[4:6], date[6:]])}')"` | 过滤表达式 |

**返回字段**（按列序，共 38 列）

| 列序 | 字段含义 |
|---|---|
| 0 | 序号 |
| 1 | 股票代码 |
| 2 | 股票简称 |
| 7 | 最新公告日期 |
| 9 | 每股收益 |
| 11 | 营业总收入-营业总收入 |
| 12 | 净利润-净利润 |
| 13 | 净资产收益率 |
| 14 | 营业总收入-同比增长 |
| 15 | 净利润-同比增长 |
| 16 | 每股净资产 |
| 17 | 每股经营现金流量 |
| 18 | 销售毛利率 |
| 19 | 营业总收入-季度环比增长 |
| 20 | 净利润-季度环比增长 |
| 23 | 所处行业 |

---

## 89. `RPT_LIFTDAY_STA`

- **akshare 入口**: `stock_restricted_release_summary_em(symbol: str = "全部股票", start_date: str = "20221101", end_date: str = "20221209")`
- **源码**: `stock_fundamental/stock_restricted_em.py:13`
- **用途**: 东方财富网-数据中心-特色数据-限售股解禁

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `sortColumns` | `"FREE_DATE"` | 排序字段 |
| `sortTypes` | `"1"` | -1降序 1升序 |
| `pageSize` | `"500"` | 每页条数 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `columns` | `"ALL"` | 返回字段，ALL=全部 |
| `quoteColumns` | `"f2~03~INDEX_CODE,f3~03~INDEX_CODE,f124~03~INDEX_CODE"` | 行情字段注入 |
| `quoteType` | `"0"` |  |
| `source` | `"WEB"` | 客户端标识 |
| `client` | `"WEB"` | 客户端标识 |
| `filter` | `f"""(INDEX_CODE="{symbol_map[symbol]}")(FREE_DATE>=` | 过滤表达式 |
| `reportName` | `"RPT_LIFTDAY_STA"` | 数据集标识 |

**返回字段**（按列序，共 15 列）

| 列序 | 字段含义 |
|---|---|
| 0 | 序号 |
| 1 | 解禁时间 |
| 2 | 当日解禁股票家数 |
| 3 | 实际解禁数量 |
| 4 | 实际解禁市值 |
| 5 | 沪深300指数 |
| 6 | 沪深300指数涨跌幅 |
| 7 | 解禁数量 |

---

## 90. `RPT_LIFT_GD`

- **akshare 入口**: `stock_restricted_release_stockholder_em(symbol: str = "600000", date: str = "20200904")`
- **源码**: `stock_fundamental/stock_restricted_em.py:300`
- **用途**: 东方财富网-数据中心-个股限售解禁-解禁股东

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `sortColumns` | `"ADD_LISTING_SHARES"` | 排序字段 |
| `sortTypes` | `"-1"` | -1降序 1升序 |
| `pageSize` | `"500"` | 每页条数 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `reportName` | `"RPT_LIFT_GD"` | 数据集标识 |
| `filter` | `f"""(SECURITY_CODE="{symbol}")(FREE_DATE='{date_str}')"""` | 过滤表达式 |
| `columns` | `"LIMITED_HOLDER_NAME,ADD_LISTING_SHARES,ACTUAL_LISTED_SHARES,ADD_LISTING_CAP,LOCK_MONTH,"` | 返回字段，ALL=全部 |
| `source` | `"WEB"` | 客户端标识 |
| `client` | `"WEB"` | 客户端标识 |

**返回字段**（按列序，共 9 列）

| 列序 | 字段含义 |
|---|---|
| 0 | 序号 |
| 1 | 股东名称 |
| 2 | 解禁数量 |
| 3 | 实际解禁数量 |
| 4 | 解禁市值 |
| 5 | 锁定期 |
| 6 | 剩余未解禁数量 |
| 7 | 限售股类型 |
| 8 | 进度 |

---

## 91. `RPT_LIFT_STAGE`

- **akshare 入口**: `stock_restricted_release_detail_em(start_date: str = "20221202", end_date: str = "20241202")`
- **源码**: `stock_fundamental/stock_restricted_em.py:105`
- **用途**: 东方财富网-数据中心-限售股解禁-解禁详情一览

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `sortColumns` | `"FREE_DATE,CURRENT_FREE_SHARES"` | 排序字段 |
| `sortTypes` | `"1,1"` | -1降序 1升序 |
| `pageSize` | `"500"` | 每页条数 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `reportName` | `"RPT_LIFT_STAGE"` | 数据集标识 |
| `columns` | `"SECURITY_CODE,SECURITY_NAME_ABBR,FREE_DATE,CURRENT_FREE_SHARES,ABLE_FREE_SHARES,"` | 返回字段，ALL=全部 |
| `source` | `"WEB"` | 客户端标识 |
| `client` | `"WEB"` | 客户端标识 |
| `filter` | `f"""(FREE_DATE>='{start_date_str}')(FREE_DATE<='{end_date_str}')"""` | 过滤表达式 |

**返回字段**（按列序，共 15 列）

| 列序 | 字段含义 |
|---|---|
| 0 | 序号 |
| 1 | 股票代码 |
| 2 | 股票简称 |
| 3 | 解禁时间 |
| 4 | 实际解禁数量 |
| 5 | 解禁数量 |
| 6 | 实际解禁市值 |
| 7 | 占解禁前流通市值比例 |
| 8 | 解禁前一交易日收盘价 |
| 9 | 解禁前20日涨跌幅 |
| 10 | 解禁后20日涨跌幅 |
| 11 | 限售股类型 |

---

## 92. `RPT_MAINDATA_MAIN_POSITIONDETAILS`

- **akshare 入口**: `stock_report_fund_hold_detail(symbol: str = "008286", date: str = "20220331")`
- **源码**: `stock/stock_fund_hold.py:109`
- **用途**: 东方财富网-数据中心-主力数据-基金持仓-明细

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `sortColumns` | `"SECURITY_CODE"` | 排序字段 |
| `sortTypes` | `"-1"` | -1降序 1升序 |
| `pageSize` | `"500"` | 每页条数 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `reportName` | `"RPT_MAINDATA_MAIN_POSITIONDETAILS"` | 数据集标识 |
| `columns` | `"ALL"` | 返回字段，ALL=全部 |
| `quoteColumns` | `""` | 行情字段注入 |
| `filter` | `f"""(HOLDER_CODE="{symbol}")(REPORT_DATE='{date}')"""` | 过滤表达式 |
| `source` | `"WEB"` | 客户端标识 |
| `client` | `"WEB"` | 客户端标识 |

**返回字段**（按列序，共 19 列）

| 列序 | 字段含义 |
|---|---|
| 0 | 序号 |
| 2 | 股票代码 |
| 4 | 股票简称 |
| 13 | 持股数 |
| 14 | 持股市值 |
| 15 | 占总股本比例 |
| 16 | 占流通股本比例 |

---

## 93. `RPT_MUTUAL_BOARD_HOLDRANK_WEB`

- **akshare 入口**: `stock_hsgt_board_rank_em(symbol: str = "北向资金增持行业板块排行", indicator: str = "今日")`
- **源码**: `stock_feature/stock_hsgt_em.py:1189`
- **用途**: 东方财富网-数据中心-沪深港通持股-行业板块排行-北向资金增持行业板块排行

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `sortColumns` | `"ADD_MARKET_CAP"` | 排序字段 |
| `sortTypes` | `"-1"` | -1降序 1升序 |
| `pageSize` | `"500"` | 每页条数 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `reportName` | `"RPT_MUTUAL_BOARD_HOLDRANK_WEB"` | 数据集标识 |
| `columns` | `"ALL"` | 返回字段，ALL=全部 |
| `quoteColumns` | `"f3~05~SECURITY_CODE~INDEX_CHANGE_RATIO"` | 行情字段注入 |
| `source` | `"WEB"` | 客户端标识 |
| `client` | `"WEB"` | 客户端标识 |
| `filter` | `f"""(BOARD_TYPE="{symbol_map[symbol]}")(TRADE_DATE='{current_date}')(INTERVAL_TYPE="{indicator_map[i` | 过滤表达式 |

**返回字段**（按列序，共 36 列）

| 列序 | 字段含义 |
|---|---|
| 0 | 序号 |
| 3 | 名称 |
| 5 | 最新涨跌幅 |
| 6 | 报告时间 |
| 9 | 北向资金今日增持估计-股票只数 |
| 10 | 北向资金今日持股-股票只数 |
| 11 | 北向资金今日增持估计-市值 |
| 12 | 北向资金今日增持估计-市值增幅 |
| 14 | 北向资金今日增持估计-占板块比 |
| 15 | 北向资金今日增持估计-占北向资金比 |
| 16 | 北向资金今日持股-市值 |
| 17 | 北向资金今日持股-占北向资金比 |
| 18 | 北向资金今日持股-占板块比 |
| 21 | 今日增持最大股-市值 |
| 24 | 今日减持最大股-市值 |
| 25 | 今日增持最大股-占总市值比 |
| 28 | 今日减持最大股-占总市值比 |

---

## 94. `RPT_MUTUAL_DEAL_HISTORY`

- **akshare 入口**: `stock_hsgt_hist_em(symbol: str = "北向资金")`
- **源码**: `stock_feature/stock_hsgt_em.py:1069`
- **用途**: 东方财富网-数据中心-资金流向-沪深港通资金流向-沪深港通历史数据

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `sortColumns` | `"TRADE_DATE"` | 排序字段 |
| `sortTypes` | `"-1"` | -1降序 1升序 |
| `pageSize` | `"1000"` | 每页条数 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `reportName` | `"RPT_MUTUAL_DEAL_HISTORY"` | 数据集标识 |
| `columns` | `"ALL"` | 返回字段，ALL=全部 |
| `source` | `"WEB"` | 客户端标识 |
| `client` | `"WEB"` | 客户端标识 |
| `filter` | `f'(MUTUAL_TYPE="00{symbol_map[symbol]}")'` | 过滤表达式 |

**字段重命名**（英文原始名 → 中文含义）

| 原始字段 | 含义 |
|---|---|
| `MUTUAL_TYPE` | - |
| `TRADE_DATE` | 日期 |
| `FUND_INFLOW` | 当日资金流入 |
| `NET_DEAL_AMT` | 当日成交净买额 |
| `QUOTA_BALANCE` | 当日余额 |
| `ACCUM_DEAL_AMT` | 历史累计净买额 |
| `BUY_AMT` | 买入成交额 |
| `SELL_AMT` | 卖出成交额 |
| `LEAD_STOCKS_CODE` | 领涨股-代码 |
| `LEAD_STOCKS_NAME` | 领涨股 |
| `LS_CHANGE_RATE` | 领涨股-涨跌幅 |

---

## 95. `RPT_MUTUAL_HOLDSTOCKNDATE_STA`

- **akshare 入口**: `__stock_hsgt_individual_zh_a_em(symbol: str = "002008")`
- **源码**: `stock_feature/stock_hsgt_em.py:1422`
- **用途**: 东方财富-数据中心-沪深港通-沪深港通持股-具体股票

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `sortColumns` | `"TRADE_DATE"` | 排序字段 |
| `sortTypes` | `"-1"` | -1降序 1升序 |
| `pageSize` | `"500"` | 每页条数 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `reportName` | `"RPT_MUTUAL_HOLDSTOCKNDATE_STA"` | 数据集标识 |
| `columns` | `"ALL"` | 返回字段，ALL=全部 |
| `source` | `"WEB"` | 客户端标识 |
| `client` | `"WEB"` | 客户端标识 |
| `filter` | `f"""(SECURITY_CODE="{symbol}")(INTERVAL_TYPE="1")"""` | 过滤表达式 |

**字段重命名**（英文原始名 → 中文含义）

| 原始字段 | 含义 |
|---|---|
| `SECURITY_INNER_CODE` | - |
| `SECUCODE` | - |
| `TRADE_DATE` | 持股日期 |
| `SECURITY_CODE` | - |
| `SECURITY_NAME` | - |
| `MUTUAL_TYPE` | - |
| `CHANGE_RATE` | 当日涨跌幅 |
| `CLOSE_PRICE` | 当日收盘价 |
| `HOLD_SHARES` | 持股数量 |
| `HOLD_MARKET_CAP` | 持股市值 |
| `A_SHARES_RATIO` | - |
| `HOLD_SHARES_RATIO` | 持股数量占A股百分比 |
| `FREE_SHARES_RATIO` | - |
| `TOTAL_SHARES_RATIO` | - |
| `HMC_CHANGE` | 今日持股市值变化 |
| `ADD_SHARES_REPAIR` | 今日增持股数 |
| `PREDICT_AMC` | 今日增持资金 |

---

## 96. `RPT_MUTUAL_HOLD_DET`

- **akshare 入口**: `stock_hsgt_individual_detail_em(symbol: str = "002008",
    start_date: str = "20220130",
    end_date: str = "20220330",)`
- **源码**: `stock_feature/stock_hsgt_em.py:1526`
- **用途**: 东方财富-数据中心-沪深港通-沪深港通持股-具体股票详情

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `sortColumns` | `"HOLD_DATE"` | 排序字段 |
| `sortTypes` | `"-1"` | -1降序 1升序 |
| `pageSize` | `"500"` | 每页条数 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `reportName` | `"RPT_MUTUAL_HOLD_DET"` | 数据集标识 |
| `columns` | `"ALL"` | 返回字段，ALL=全部 |
| `source` | `"WEB"` | 客户端标识 |
| `client` | `"WEB"` | 客户端标识 |
| `filter` | `f"""(SECURITY_CODE="{symbol}")(MARKET_CODE="003")(HOLD_DATE` | 过滤表达式 |

**字段重命名**（英文原始名 → 中文含义）

| 原始字段 | 含义 |
|---|---|
| `SECUCODE` | - |
| `SECURITY_CODE` | - |
| `SECURITY_INNER_CODE` | - |
| `SECURITY_NAME_ABBR` | - |
| `HOLD_DATE` | 持股日期 |
| `ORG_CODE` | - |
| `ORG_NAME` | 机构名称 |
| `HOLD_NUM` | 持股数量 |
| `MARKET_CODE` | - |
| `HOLD_SHARES_RATIO` | 持股数量占A股百分比 |
| `HOLD_MARKET_CAP` | 持股市值 |
| `CLOSE_PRICE` | 当日收盘价 |
| `CHANGE_RATE` | 当日涨跌幅 |
| `HOLD_MARKET_CAPONE` | 持股市值变化-1日 |
| `HOLD_MARKET_CAPFIVE` | 持股市值变化-5日 |
| `HOLD_MARKET_CAPTEN` | 持股市值变化-10日 |
| `PARTICIPANT_CODE` | - |

---

## 97. `RPT_MUTUAL_QUOTA`

- **akshare 入口**: `stock_hsgt_fund_flow_summary_em()`
- **源码**: `stock_feature/stock_hsgt_em.py:17`
- **用途**: 东方财富网-数据中心-资金流向-沪深港通资金流向

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `reportName` | `"RPT_MUTUAL_QUOTA"` | 数据集标识 |
| `columns` | `"TRADE_DATE,MUTUAL_TYPE,BOARD_TYPE,MUTUAL_TYPE_NAME,FUNDS_DIRECTION,"` | 返回字段，ALL=全部 |
| `quoteColumns` | `"status~07~BOARD_CODE,dayNetAmtIn~07~BOARD_CODE,dayAmtRemain~07~BOARD_CODE,"` | 行情字段注入 |
| `quoteType` | `"0"` |  |
| `pageNumber` | `"1"` | 页码，从1起 |
| `pageSize` | `"2000"` | 每页条数 |
| `sortTypes` | `"1"` | -1降序 1升序 |
| `sortColumns` | `"MUTUAL_TYPE"` | 排序字段 |
| `source` | `"WEB"` | 客户端标识 |
| `client` | `"WEB"` | 客户端标识 |

**返回字段**（按列序，共 17 列）

| 列序 | 字段含义 |
|---|---|
| 0 | 交易日 |
| 2 | 类型 |
| 3 | 板块 |
| 4 | 资金方向 |
| 6 | 相关指数 |
| 8 | 交易状态 |
| 9 | 资金净流入 |
| 10 | 当日资金余额 |
| 12 | 上涨数 |
| 13 | 下跌数 |
| 14 | 持平数 |
| 15 | 指数涨跌幅 |
| 16 | 成交净买额 |

---

## 98. `RPT_MUTUAL_STOCK_HOLDRANKS`

- **akshare 入口**: `stock_hsgt_stock_statistics_em(symbol: str = "北向持股",
    start_date: str = "20240110",
    end_date: str = "20240110",)`
- **源码**: `stock_feature/stock_hsgt_em.py:335`
- **用途**: 东方财富网-数据中心-沪深港通-沪深港通持股-每日个股统计

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `sortColumns` | `"TRADE_DATE"` | 排序字段 |
| `sortTypes` | `"-1"` | -1降序 1升序 |
| `pageSize` | `"1000"` | 每页条数 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `columns` | `"ALL"` | 返回字段，ALL=全部 |
| `source` | `"WEB"` | 客户端标识 |
| `client` | `"WEB"` | 客户端标识 |
| `filter` | `f"""(INTERVAL_TYPE="1")(RN=1)(TRADE_DATE>='{start_date}')(TRADE_DATE<='{end_date}')"""` | 过滤表达式 |
| `rt` | `"53160469"` |  |
| `reportName` | `"RPT_MUTUAL_STOCK_HOLDRANKS"` | 数据集标识 |

**返回字段**（按列序，共 29 列）

| 列序 | 字段含义 |
|---|---|
| 1 | 持股日期 |
| 4 | 股票简称 |
| 5 | 股票代码 |
| 10 | 持股市值 |
| 11 | 持股数量 |
| 16 | 当日收盘价 |
| 17 | 当日涨跌幅 |
| 23 | 持股数量占发行股百分比 |
| 25 | 持股市值变化-1日 |
| 26 | 持股市值变化-5日 |
| 27 | 持股市值变化-10日 |

---

## 99. `RPT_MUTUAL_STOCK_NORTHSTA`

- **akshare 入口**: `stock_hsgt_hold_stock_em(market: str = "沪股通", indicator: str = "5日排行")`
- **源码**: `stock_feature/stock_hsgt_em.py:170`
- **用途**: 东方财富-数据中心-沪深港通持股-个股排行

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `sortColumns` | `"ADD_MARKET_CAP"` | 排序字段 |
| `sortTypes` | `"-1"` | -1降序 1升序 |
| `pageSize` | `"50000"` | 每页条数 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `reportName` | `"RPT_MUTUAL_STOCK_NORTHSTA"` | 数据集标识 |
| `columns` | `"ALL"` | 返回字段，ALL=全部 |
| `source` | `"WEB"` | 客户端标识 |
| `client` | `"WEB"` | 客户端标识 |
| `filter` | `filter_str` | 过滤表达式 |

**返回字段**（按列序，共 44 列）

| 列序 | 字段含义 |
|---|---|
| 0 | 序号 |
| 3 | 日期 |
| 5 | 名称 |
| 8 | 代码 |
| 13 | 今日持股-股数 |
| 14 | 今日持股-市值 |
| 15 | 今日持股-占流通股比 |
| 16 | 今日持股-占总股本比 |
| 17 | 今日收盘价 |
| 18 | 今日涨跌幅 |
| 20 | 所属板块 |
| 31 | f"{indicator.split('排')[0]}增持估计-市值 |
| 32 | f"{indicator.split('排')[0]}增持估计-股数 |
| 33 | f"{indicator.split('排')[0]}增持估计-市值增幅 |
| 34 | f"{indicator.split('排')[0]}增持估计-占流通股比 |
| 35 | f"{indicator.split('排')[0]}增持估计-占总股本比 |

---

## 100. `RPT_NEEQ_ISSUEINFO_LIST`

- **akshare 入口**: `stock_xgsglb_em(symbol: str = "全部股票")`
- **源码**: `stock_feature/stock_dxsyl_em.py:127`
- **用途**: 新股申购与中签查询

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `sortColumns` | `"APPLY_DATE"` | 排序字段 |
| `sortTypes` | `"-1"` | -1降序 1升序 |
| `pageSize` | `"500"` | 每页条数 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `columns` | `"ALL"` | 返回字段，ALL=全部 |
| `reportName` | `"RPT_NEEQ_ISSUEINFO_LIST"` | 数据集标识 |
| `quoteColumns` | `"f14~01~SECURITY_CODE~SECURITY_NAME_ABBR"` | 行情字段注入 |
| `source` | `"NEEQSELECT"` | 客户端标识 |
| `client` | `"WEB"` | 客户端标识 |

**字段重命名**（英文原始名 → 中文含义）

| 原始字段 | 含义 |
|---|---|
| `ORG_CODE` | - |
| `SECURITY_CODE` | 代码 |
| `SECUCODE` | 带市场标识股票代码 |
| `SECURITY_NAME_ABBR` | 简称 |
| `APPLY_CODE` | 申购代码 |
| `EXPECT_ISSUE_NUM` | 发行总数 |
| `PRICE_WAY` | 定价方式 |
| `ISSUE_PRICE` | 发行价格 |
| `ISSUE_PE_RATIO` | 发行市盈率 |
| `APPLY_DATE` | 申购日 |
| `RESULT_NOTICE_DATE` | 发行结果公告日期 |
| `SELECT_LISTING_DATE` | 上市首日-上市日 |
| `ONLINE_ISSUE_NUM` | 网上-发行数量 |
| `APPLY_AMT_UPPER` | 网上-顶格所需资金 |
| `APPLY_NUM_UPPER` | 网上-申购上限 |
| `ONLINE_PAY_DATE` | 网上申购缴款日期 |
| `ONLINE_REFUND_DATE` | 网上申购资金退款日 |
| `INFO_CODE` | - |
| `ONLINE_ISSUE_LWR` | 中签率 |
| `NEWEST_PRICE` | 最新价格-价格 |
| `CLOSE_PRICE` | 首日收盘价 |
| `INITIAL_MULTIPLE` | - |
| `PER_SHARES_INCOME` | 上市首日-每百股获利 |
| `LD_CLOSE_CHANGE` | 上市首日-涨幅 |
| `TURNOVERRATE` | 首日换手率 |
| `AMPLITUDE` | 首日振幅 |
| `ONLINE_APPLY_LOWER` | - |
| `MAIN_BUSINESS` | 主营业务 |
| `INDUSTRY_PE_RATIO` | 行业市盈率 |
| `APPLY_AMT_100` | 稳获百股需配资金 |
| `TAKE_UP_TIME` | 资金占用时间 |
| `CAPTURE_PROFIT` | 上市首日-约合年化收益 |
| `APPLY_SHARE_100` | 每获配百股需配股数 |
| `AVERAGE_PRICE` | 上市首日-均价 |
| `ORG_VAN` | 参与申购人数 |
| `VA_AMT` | 参与申购资金 |
| `ISSUE_PRICE_ADJFACTOR` | - |

---

## 101. `RPT_OPERATEDEPT_ACTIVE`

- **akshare 入口**: `stock_lhb_hyyyb_em(start_date: str = "20220324", end_date: str = "20220324")`
- **源码**: `stock_feature/stock_lhb_em.py:432`
- **用途**: 东方财富网-数据中心-龙虎榜单-每日活跃营业部

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `sortColumns` | `"TOTAL_NETAMT,ONLIST_DATE,OPERATEDEPT_CODE"` | 排序字段 |
| `sortTypes` | `"-1,-1,1"` | -1降序 1升序 |
| `pageSize` | `"5000"` | 每页条数 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `reportName` | `"RPT_OPERATEDEPT_ACTIVE"` | 数据集标识 |
| `columns` | `"ALL"` | 返回字段，ALL=全部 |
| `source` | `"WEB"` | 客户端标识 |
| `client` | `"WEB"` | 客户端标识 |
| `filter` | `f"(ONLIST_DATE>='{start_date}')(ONLIST_DATE<='{end_date}')"` | 过滤表达式 |

**返回字段**（按列序，共 13 列）

| 列序 | 字段含义 |
|---|---|
| 0 | 序号 |
| 1 | 营业部名称 |
| 2 | 上榜日 |
| 3 | 买入个股数 |
| 4 | 卖出个股数 |
| 5 | 买入总金额 |
| 6 | 卖出总金额 |
| 7 | 总买卖净额 |
| 9 | 营业部代码 |
| 10 | 买入股票 |

---

## 102. `RPT_OPERATEDEPT_LIST_STATISTICS`

- **akshare 入口**: `stock_lhb_traderstatistic_em(symbol: str = "近一月")`
- **源码**: `stock_feature/stock_lhb_em.py:647`
- **用途**: 东方财富网-数据中心-龙虎榜单-营业部统计

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `sortColumns` | `"AMOUNT,OPERATEDEPT_CODE"` | 排序字段 |
| `sortTypes` | `"-1,1"` | -1降序 1升序 |
| `pageSize` | `"5000"` | 每页条数 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `reportName` | `"RPT_OPERATEDEPT_LIST_STATISTICS"` | 数据集标识 |
| `columns` | `"ALL"` | 返回字段，ALL=全部 |
| `source` | `"WEB"` | 客户端标识 |
| `client` | `"WEB"` | 客户端标识 |
| `filter` | `f'(STATISTICSCYCLE="{symbol_map[symbol]}")'` | 过滤表达式 |

**字段重命名**（英文原始名 → 中文含义）

| 原始字段 | 含义 |
|---|---|
| `index` | 序号 |
| `OPERATEDEPT_NAME` | 营业部名称 |
| `AMOUNT` | 龙虎榜成交金额 |
| `SALES_ONLIST_TIMES` | 上榜次数 |
| `ACT_BUY` | 买入额 |
| `TOTAL_BUYER_SALESTIMES` | 买入次数 |
| `ACT_SELL` | 卖出额 |
| `TOTAL_SELLER_SALESTIMES` | 卖出次数 |

---

## 103. `RPT_OPERATEDEPT_TRADE_DETAILSNEW`

- **akshare 入口**: `stock_lhb_yyb_detail_em(symbol: str = "10188715")`
- **源码**: `stock_feature/stock_lhb_em.py:903`
- **用途**: 东方财富网-数据中心-龙虎榜单-营业部历史交易明细-营业部交易明细

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `sortColumns` | `"TRADE_DATE,SECURITY_CODE"` | 排序字段 |
| `sortTypes` | `"-1,1"` | -1降序 1升序 |
| `pageSize` | `"100"` | 每页条数 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `reportName` | `"RPT_OPERATEDEPT_TRADE_DETAILSNEW"` | 数据集标识 |
| `columns` | `"ALL"` | 返回字段，ALL=全部 |
| `source` | `"WEB"` | 客户端标识 |
| `client` | `"WEB"` | 客户端标识 |
| `filter` | `f'(OPERATEDEPT_CODE="{symbol}")'` | 过滤表达式 |

---

## 104. `RPT_ORGANIZATION_SEATNEW`

- **akshare 入口**: `stock_lhb_jgstatistic_em(symbol: str = "近一月")`
- **源码**: `stock_feature/stock_lhb_em.py:334`
- **用途**: 东方财富网-数据中心-龙虎榜单-机构席位追踪

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `sortColumns` | `"ONLIST_TIMES,SECURITY_CODE"` | 排序字段 |
| `sortTypes` | `"-1,1"` | -1降序 1升序 |
| `pageSize` | `"5000"` | 每页条数 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `reportName` | `"RPT_ORGANIZATION_SEATNEW"` | 数据集标识 |
| `columns` | `"ALL"` | 返回字段，ALL=全部 |
| `source` | `"WEB"` | 客户端标识 |
| `client` | `"WEB"` | 客户端标识 |
| `filter` | `f'(STATISTICSCYCLE="{symbol_map[symbol]}")'` | 过滤表达式 |

**字段重命名**（英文原始名 → 中文含义）

| 原始字段 | 含义 |
|---|---|
| `index` | 序号 |
| `SECURITY_CODE` | 代码 |
| `SECURITY_NAME_ABBR` | 名称 |
| `CLOSE_PRICE` | 收盘价 |
| `CHANGE_RATE` | 涨跌幅 |
| `AMOUNT` | 龙虎榜成交金额 |
| `ONLIST_TIMES` | 上榜次数 |
| `BUY_AMT` | 机构买入额 |
| `BUY_TIMES` | 机构买入次数 |
| `SELL_AMT` | 机构卖出额 |
| `SELL_TIMES` | 机构卖出次数 |
| `NET_BUY_AMT` | 机构净买额 |
| `M1_CLOSE_ADJCHRATE` | 近1个月涨跌幅 |
| `M3_CLOSE_ADJCHRATE` | 近3个月涨跌幅 |
| `M6_CLOSE_ADJCHRATE` | 近6个月涨跌幅 |
| `Y1_CLOSE_ADJCHRATE` | 近1年涨跌幅 |

---

## 105. `RPT_ORGANIZATION_TRADE_DETAILS`

- **akshare 入口**: `stock_lhb_jgmmtj_em(start_date: str = "20240417", end_date: str = "20240430")`
- **源码**: `stock_feature/stock_lhb_em.py:225`
- **用途**: 东方财富网-数据中心-龙虎榜单-机构买卖每日统计

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `sortColumns` | `"NET_BUY_AMT,TRADE_DATE,SECURITY_CODE"` | 排序字段 |
| `sortTypes` | `"-1,-1,1"` | -1降序 1升序 |
| `pageSize` | `"500"` | 每页条数 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `reportName` | `"RPT_ORGANIZATION_TRADE_DETAILS"` | 数据集标识 |
| `columns` | `"ALL"` | 返回字段，ALL=全部 |
| `source` | `"WEB"` | 客户端标识 |
| `client` | `"WEB"` | 客户端标识 |
| `filter` | `f"(TRADE_DATE>='{start_date}')(TRADE_DATE<='{end_date}')"` | 过滤表达式 |

**返回字段**（按列序，共 26 列）

| 列序 | 字段含义 |
|---|---|
| 0 | 序号 |
| 2 | 名称 |
| 3 | 代码 |
| 4 | 上榜日期 |
| 5 | 收盘价 |
| 6 | 涨跌幅 |
| 7 | 买方机构数 |
| 8 | 卖方机构数 |
| 9 | 机构买入总额 |
| 10 | 机构卖出总额 |
| 11 | 机构买入净额 |
| 12 | 市场总成交额 |
| 13 | 机构净买额占总成交额比 |
| 14 | 换手率 |
| 15 | 流通市值 |
| 16 | 上榜原因 |

---

## 106. `RPT_ORGOP_ALL`

- **akshare 入口**: `stock_gsrl_gsdt_em(date: str = "20230808")`
- **源码**: `stock/stock_gsrl_em.py:12`
- **用途**: 东方财富网-数据中心-股市日历-公司动态

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `sortColumns` | `"SECURITY_CODE"` | 排序字段 |
| `sortTypes` | `"1"` | -1降序 1升序 |
| `pageSize` | `"5000"` | 每页条数 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `columns` | `"SECURITY_CODE,SECUCODE,SECURITY_NAME_ABBR,EVENT_TYPE,EVENT_CONTENT,TRADE_DATE"` | 返回字段，ALL=全部 |
| `source` | `"WEB"` | 客户端标识 |
| `client` | `"WEB"` | 客户端标识 |
| `reportName` | `"RPT_ORGOP_ALL"` | 数据集标识 |
| `filter` | `f"""(TRADE_DATE='{"-".join([date[:4], date[4:6], date[6:]])}')"""` | 过滤表达式 |

**字段重命名**（英文原始名 → 中文含义）

| 原始字段 | 含义 |
|---|---|
| `index` | 序号 |
| `SECURITY_CODE` | 代码 |
| `SECUCODE` | - |
| `SECURITY_NAME_ABBR` | 简称 |
| `EVENT_TYPE` | 事件类型 |
| `EVENT_CONTENT` | 具体事项 |
| `TRADE_DATE` | 交易日 |

---

## 107. `RPT_ORG_SURVEY`

- **akshare 入口**: `stock_jgdy_detail_em(date: str = "20241211")`
- **源码**: `stock_feature/stock_jgdy_em.py:107`
- **用途**: 东方财富网-数据中心-特色数据-机构调研-机构调研详细

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `sortColumns` | `"NOTICE_DATE,RECEIVE_START_DATE,SECURITY_CODE,NUMBERNEW"` | 排序字段 |
| `sortTypes` | `"-1,-1,1,-1"` | -1降序 1升序 |
| `pageSize` | `"50"` | 每页条数 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `reportName` | `"RPT_ORG_SURVEY"` | 数据集标识 |
| `columns` | `"SECUCODE,SECURITY_CODE,SECURITY_NAME_ABBR,NOTICE_DATE,RECEIVE_START_DATE,"` | 返回字段，ALL=全部 |
| `quoteColumns` | `"f2~01~SECURITY_CODE~CLOSE_PRICE,f3~01~SECURITY_CODE~CHANGE_RATE"` | 行情字段注入 |
| `quoteType` | `"0"` |  |
| `source` | `"WEB"` | 客户端标识 |
| `client` | `"WEB"` | 客户端标识 |
| `filter` | `f"""(IS_SOURCE="1")(RECEIVE_START_DATE>'{"-".join([date[:4], date[4:6], date[6:]])}')"""` | 过滤表达式 |

**返回字段**（按列序，共 14 列）

| 列序 | 字段含义 |
|---|---|
| 0 | 序号 |
| 2 | 代码 |
| 3 | 名称 |
| 4 | 公告日期 |
| 5 | 调研日期 |
| 6 | 调研机构 |
| 7 | 接待地点 |
| 8 | 接待方式 |
| 9 | 调研人员 |
| 10 | 接待人员 |
| 11 | 机构类型 |
| 12 | 最新价 |
| 13 | 涨跌幅 |

---

## 108. `RPT_ORG_SURVEYNEW`

- **akshare 入口**: `stock_jgdy_tj_em(date: str = "20220101")`
- **源码**: `stock_feature/stock_jgdy_em.py:15`
- **用途**: 东方财富网-数据中心-特色数据-机构调研-机构调研统计

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `sortColumns` | `"NOTICE_DATE,SUM,RECEIVE_START_DATE,SECURITY_CODE"` | 排序字段 |
| `sortTypes` | `"-1,-1,-1,1"` | -1降序 1升序 |
| `pageSize` | `"500"` | 每页条数 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `reportName` | `"RPT_ORG_SURVEYNEW"` | 数据集标识 |
| `columns` | `"ALL"` | 返回字段，ALL=全部 |
| `quoteColumns` | `"f2~01~SECURITY_CODE~CLOSE_PRICE,f3~01~SECURITY_CODE~CHANGE_RATE"` | 行情字段注入 |
| `source` | `"WEB"` | 客户端标识 |
| `client` | `"WEB"` | 客户端标识 |
| `filter` | `f"""(NUMBERNEW="1")(IS_SOURCE="1")(NOTICE_DATE>'{"-".join([date[:4], date[4:6], date[6:]])}')"""` | 过滤表达式 |

**返回字段**（按列序，共 33 列）

| 列序 | 字段含义 |
|---|---|
| 0 | 序号 |
| 2 | 代码 |
| 3 | 名称 |
| 5 | 公告日期 |
| 6 | 接待日期 |
| 14 | 接待地点 |
| 16 | 接待方式 |
| 18 | 接待人员 |
| 24 | 接待机构数量 |
| 31 | 最新价 |
| 32 | 涨跌幅 |

---

## 109. `RPT_PERFORMANCE`

- **akshare 入口**: `stock_qsjy_em(date: str = "20200731")`
- **源码**: `stock_feature/stock_qsjy_em.py:12`
- **用途**: 东方财富网-数据中心-特色数据-券商业绩月报

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `sortColumns` | `"END_DATE"` | 排序字段 |
| `sortTypes` | `"-1"` | -1降序 1升序 |
| `pageSize` | `"500"` | 每页条数 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `reportName` | `"RPT_PERFORMANCE"` | 数据集标识 |
| `columns` | `"SECURITY_CODE,SECURITY_NAME_ABBR,END_DATE,NETPROFIT,NP_YOY,NP_QOQ,ACCUMPROFIT,ACCUMPROFIT_YOY,OPERA` | 返回字段，ALL=全部 |
| `source` | `"WEB"` | 客户端标识 |
| `client` | `"WEB"` | 客户端标识 |
| `filter` | `f"(END_DATE='{'-'.join([date[:4], date[4:6], date[6:]])}')"` | 过滤表达式 |

**返回字段**（按列序，共 15 列）

| 列序 | 字段含义 |
|---|---|
| 0 | 代码 |
| 1 | 简称 |
| 3 | 当月净利润-净利润 |
| 4 | 当月净利润-同比增长 |
| 5 | 当月净利润-环比增长 |
| 6 | 当年累计净利润-累计净利润 |
| 7 | 当年累计净利润-同比增长 |
| 8 | 当月营业收入-营业收入 |
| 9 | 当月营业收入-环比增长 |
| 10 | 当月营业收入-同比增长 |
| 11 | 当年累计营业收入-累计营业收入 |
| 12 | 当年累计营业收入-同比增长 |
| 13 | 净资产-净资产 |
| 14 | 净资产-同比增长 |

---

## 110. `RPT_PUBLIC_BS_APPOIN`

- **akshare 入口**: `stock_yysj_em(symbol: str = "沪深A股", date: str = "20200331")`
- **源码**: `stock_feature/stock_yjyg_em.py:222`
- **用途**: 东方财富-数据中心-年报季报-预约披露时间

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `sortColumns` | `"FIRST_APPOINT_DATE,SECURITY_CODE"` | 排序字段 |
| `sortTypes` | `"1,1"` | -1降序 1升序 |
| `pageSize` | `"500"` | 每页条数 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `reportName` | `"RPT_PUBLIC_BS_APPOIN"` | 数据集标识 |
| `columns` | `"ALL"` | 返回字段，ALL=全部 |
| `filter` | `f"""(SECURITY_TYPE_CODE in ("058001001","058001008"))(TRADE_MARKET_CODE!="069001017")` | 过滤表达式 |

**字段重命名**（英文原始名 → 中文含义）

| 原始字段 | 含义 |
|---|---|
| `SECURITY_CODE` | 股票代码 |
| `SECURITY_NAME_ABBR` | 股票简称 |
| `FIRST_APPOINT_DATE` | 首次预约时间 |
| `FIRST_CHANGE_DATE` | 一次变更日期 |
| `SECOND_CHANGE_DATE` | 二次变更日期 |
| `THIRD_CHANGE_DATE` | 三次变更日期 |
| `ACTUAL_PUBLISH_DATE` | 实际披露时间 |

---

## 111. `RPT_PUBLIC_OP_NEWPREDICT`

- **akshare 入口**: `stock_yjyg_em(date: str = "20200331")`
- **源码**: `stock_feature/stock_yjyg_em.py:134`
- **用途**: 东方财富-数据中心-年报季报-业绩预告

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `sortColumns` | `"NOTICE_DATE,SECURITY_CODE"` | 排序字段 |
| `sortTypes` | `"-1,-1"` | -1降序 1升序 |
| `pageSize` | `"500"` | 每页条数 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `reportName` | `"RPT_PUBLIC_OP_NEWPREDICT"` | 数据集标识 |
| `columns` | `"ALL"` | 返回字段，ALL=全部 |
| `filter` | `f" (REPORT_DATE='{'-'.join([date[:4], date[4:6], date[6:]])}')"` | 过滤表达式 |

**返回字段**（按列序，共 28 列）

| 列序 | 字段含义 |
|---|---|
| 0 | 序号 |
| 2 | 股票代码 |
| 3 | 股票简称 |
| 5 | 公告日期 |
| 6 | 报告日期 |
| 8 | 预测指标 |
| 13 | 业绩变动 |
| 14 | 业绩变动原因 |
| 15 | 预告类型 |
| 16 | 上年同期值 |
| 21 | 业绩变动幅度 |
| 22 | 预测数值 |

---

## 112. `RPT_RATEDEPT_RETURNT_RANKING`

- **akshare 入口**: `stock_lhb_yybph_em(symbol: str = "近一月")`
- **源码**: `stock_feature/stock_lhb_em.py:511`
- **用途**: 东方财富网-数据中心-龙虎榜单-营业部排行

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `sortColumns` | `"TOTAL_BUYER_SALESTIMES_1DAY,OPERATEDEPT_CODE"` | 排序字段 |
| `sortTypes` | `"-1,1"` | -1降序 1升序 |
| `pageSize` | `"5000"` | 每页条数 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `reportName` | `"RPT_RATEDEPT_RETURNT_RANKING"` | 数据集标识 |
| `columns` | `"ALL"` | 返回字段，ALL=全部 |
| `source` | `"WEB"` | 客户端标识 |
| `client` | `"WEB"` | 客户端标识 |
| `filter` | `f'(STATISTICSCYCLE="{symbol_map[symbol]}")'` | 过滤表达式 |

**字段重命名**（英文原始名 → 中文含义）

| 原始字段 | 含义 |
|---|---|
| `index` | 序号 |
| `OPERATEDEPT_NAME` | 营业部名称 |
| `TOTAL_BUYER_SALESTIMES_1DAY` | 上榜后1天-买入次数 |
| `AVERAGE_INCREASE_1DAY` | 上榜后1天-平均涨幅 |
| `RISE_PROBABILITY_1DAY` | 上榜后1天-上涨概率 |
| `TOTAL_BUYER_SALESTIMES_2DAY` | 上榜后2天-买入次数 |
| `AVERAGE_INCREASE_2DAY` | 上榜后2天-平均涨幅 |
| `RISE_PROBABILITY_2DAY` | 上榜后2天-上涨概率 |
| `TOTAL_BUYER_SALESTIMES_3DAY` | 上榜后3天-买入次数 |
| `AVERAGE_INCREASE_3DAY` | 上榜后3天-平均涨幅 |
| `RISE_PROBABILITY_3DAY` | 上榜后3天-上涨概率 |
| `TOTAL_BUYER_SALESTIMES_5DAY` | 上榜后5天-买入次数 |
| `AVERAGE_INCREASE_5DAY` | 上榜后5天-平均涨幅 |
| `RISE_PROBABILITY_5DAY` | 上榜后5天-上涨概率 |
| `TOTAL_BUYER_SALESTIMES_10DAY` | 上榜后10天-买入次数 |
| `AVERAGE_INCREASE_10DAY` | 上榜后10天-平均涨幅 |
| `RISE_PROBABILITY_10DAY` | 上榜后10天-上涨概率 |

---

## 113. `RPT_SEO_DETAIL`

- **akshare 入口**: `stock_qbzf_em()`
- **源码**: `stock_feature/stock_zf_pg.py:17`
- **用途**: 东方财富网-数据中心-新股数据-增发-全部增发

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `sortColumns` | `"ISSUE_DATE"` | 排序字段 |
| `sortTypes` | `"-1"` | -1降序 1升序 |
| `pageSize` | `"500"` | 每页条数 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `reportName` | `"RPT_SEO_DETAIL"` | 数据集标识 |
| `columns` | `"ALL"` | 返回字段，ALL=全部 |
| `quoteColumns` | `"f2~01~SECURITY_CODE~NEW_PRICE"` | 行情字段注入 |
| `quoteType` | `"0"` |  |
| `source` | `"WEB"` | 客户端标识 |
| `client` | `"WEB"` | 客户端标识 |

**字段重命名**（英文原始名 → 中文含义）

| 原始字段 | 含义 |
|---|---|
| `SECURITY_NAME_ABBR` | 股票简称 |
| `SECURITY_CODE` | 股票代码 |
| `CORRECODE` | 增发代码 |
| `SEO_TYPE` | 发行方式 |
| `ISSUE_NUM` | 发行总数 |
| `ONLINE_ISSUE_NUM` | 网上发行 |
| `ISSUE_PRICE` | 发行价格 |
| `NEW_PRICE` | 最新价 |
| `ISSUE_DATE` | 发行日期 |
| `ISSUE_LISTING_DATE` | 增发上市日期 |
| `LOCKIN_PERIOD` | 锁定期 |

---

## 114. `RPT_SHAREBONUS_DET`

- **akshare 入口**: `stock_fhps_em(date: str = "20231231")`
- **源码**: `stock_feature/stock_fhps_em.py:14`
- **用途**: 东方财富网-数据中心-年报季报-分红送配

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `sortColumns` | `"PLAN_NOTICE_DATE"` | 排序字段 |
| `sortTypes` | `"-1"` | -1降序 1升序 |
| `pageSize` | `"500"` | 每页条数 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `reportName` | `"RPT_SHAREBONUS_DET"` | 数据集标识 |
| `columns` | `"ALL"` | 返回字段，ALL=全部 |
| `quoteColumns` | `""` | 行情字段注入 |
| `js` | `'{"data":(x),"pages":(tp)}'` |  |
| `source` | `"WEB"` | 客户端标识 |
| `client` | `"WEB"` | 客户端标识 |
| `filter` | `f"""(REPORT_DATE='{"-".join([date[:4], date[4:6], date[6:]])}')"""` | 过滤表达式 |

**返回字段**（按列序，共 30 列）

| 列序 | 字段含义 |
|---|---|
| 1 | 名称 |
| 4 | 代码 |
| 5 | 送转股份-送转总比例 |
| 6 | 送转股份-送转比例 |
| 7 | 送转股份-转股比例 |
| 8 | 现金分红-现金分红比例 |
| 9 | 预案公告日 |
| 10 | 股权登记日 |
| 11 | 除权除息日 |
| 13 | 方案进度 |
| 15 | 最新公告日期 |
| 19 | 每股收益 |
| 20 | 每股净资产 |
| 21 | 每股公积金 |
| 22 | 每股未分配利润 |
| 23 | 净利润同比增长 |
| 24 | 总股本 |
| 26 | 现金分红-股息率 |

---

## 115. `RPT_SHARE_HOLDER_INCREASE`

- **akshare 入口**: `stock_ggcg_em(symbol: str = "全部")`
- **源码**: `stock_feature/stock_gdzjc_em.py:14`
- **用途**: 东方财富网-数据中心-特色数据-高管持股

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `sortColumns` | `"END_DATE,SECURITY_CODE,EITIME"` | 排序字段 |
| `sortTypes` | `"-1,-1,-1"` | -1降序 1升序 |
| `pageSize` | `"500"` | 每页条数 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `reportName` | `"RPT_SHARE_HOLDER_INCREASE"` | 数据集标识 |
| `quoteColumns` | `"f2~01~SECURITY_CODE~NEWEST_PRICE,f3~01~SECURITY_CODE~CHANGE_RATE_QUOTES"` | 行情字段注入 |
| `quoteType` | `"0"` |  |
| `columns` | `"ALL"` | 返回字段，ALL=全部 |
| `source` | `"WEB"` | 客户端标识 |
| `client` | `"WEB"` | 客户端标识 |
| `filter` | `symbol_map[symbol]` | 过滤表达式 |

**返回字段**（按列序，共 24 列）

| 列序 | 字段含义 |
|---|---|
| 0 | 持股变动信息-变动数量 |
| 1 | 公告日 |
| 2 | 代码 |
| 3 | 股东名称 |
| 4 | 持股变动信息-占总股本比例 |
| 7 | 变动截止日 |
| 9 | 变动后持股情况-持股总数 |
| 10 | 变动后持股情况-占总股本比例 |
| 12 | 变动后持股情况-占流通股比例 |
| 13 | 变动后持股情况-持流通股数 |
| 15 | 名称 |
| 16 | 持股变动信息-增减 |
| 18 | 持股变动信息-占流通股比例 |
| 19 | 变动开始日 |
| 21 | 最新价 |
| 22 | 涨跌幅 |

---

## 116. `RPT_STOCK_HISTORYMARK`

- **akshare 入口**: `stock_comment_detail_zhpj_lspf_em(symbol: str = "600000")`
- **源码**: `stock_feature/stock_comment_em.py:150`
- **用途**: 东方财富网-数据中心-特色数据-千股千评-综合评价-历史评分

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `filter` | `f'(SECURITY_CODE="{symbol}")'` | 过滤表达式 |
| `columns` | `"ALL"` | 返回字段，ALL=全部 |
| `source` | `"WEB"` | 客户端标识 |
| `client` | `"WEB"` | 客户端标识 |
| `reportName` | `"RPT_STOCK_HISTORYMARK"` | 数据集标识 |
| `sortColumns` | `"DIAGNOSE_DATE"` | 排序字段 |
| `sortTypes` | `"1"` | -1降序 1升序 |

**字段重命名**（英文原始名 → 中文含义）

| 原始字段 | 含义 |
|---|---|
| `TOTAL_SCORE` | 评分 |
| `DIAGNOSE_DATE` | 交易日 |

---

## 117. `RPT_STOCK_MARKETFOCUS`

- **akshare 入口**: `stock_comment_detail_scrd_focus_em(symbol: str = "600000")`
- **源码**: `stock_feature/stock_comment_em.py:187`
- **用途**: 东方财富网-数据中心-特色数据-千股千评-市场热度-用户关注指数

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `filter` | `f'(SECURITY_CODE="{symbol}")'` | 过滤表达式 |
| `columns` | `"ALL"` | 返回字段，ALL=全部 |
| `source` | `"WEB"` | 客户端标识 |
| `client` | `"WEB"` | 客户端标识 |
| `reportName` | `"RPT_STOCK_MARKETFOCUS"` | 数据集标识 |
| `sortColumns` | `"TRADE_DATE"` | 排序字段 |
| `sortTypes` | `"-1"` | -1降序 1升序 |
| `pageSize` | `"30"` | 每页条数 |

**字段重命名**（英文原始名 → 中文含义）

| 原始字段 | 含义 |
|---|---|
| `MARKET_FOCUS` | 用户关注指数 |
| `TRADE_DATE` | 交易日 |

---

## 118. `RPT_STOCK_OPEN_DATA`

- **akshare 入口**: `stock_account_statistics_em()`
- **源码**: `stock_feature/stock_account_em.py:13`
- **用途**: 东方财富网-数据中心-特色数据-股票账户统计

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `reportName` | `"RPT_STOCK_OPEN_DATA"` | 数据集标识 |
| `columns` | `"ALL"` | 返回字段，ALL=全部 |
| `pageSize` | `"500"` | 每页条数 |
| `sortColumns` | `"STATISTICS_DATE"` | 排序字段 |
| `sortTypes` | `"-1"` | -1降序 1升序 |
| `source` | `"WEB"` | 客户端标识 |
| `client` | `"WEB"` | 客户端标识 |
| `p` | `"1"` |  |
| `pageNo` | `"1"` |  |
| `pageNum` | `"1"` |  |
| `pageNumber` | `"1"` | 页码，从1起 |

**返回字段**（按列序，共 12 列）

| 列序 | 字段含义 |
|---|---|
| 0 | 数据日期 |
| 1 | 新增投资者-数量 |
| 2 | 新增投资者-环比 |
| 3 | 新增投资者-同比 |
| 4 | 期末投资者-总量 |
| 5 | 期末投资者-A股账户 |
| 6 | 期末投资者-B股账户 |
| 7 | 上证指数-收盘 |
| 8 | 上证指数-涨跌幅 |
| 9 | 沪深总市值 |
| 10 | 沪深户均市值 |

---

## 119. `RPT_STOCK_PARTICIPATION`

- **akshare 入口**: `stock_comment_detail_scrd_desire_em(symbol: str = "600000",)`
- **源码**: `stock_feature/stock_comment_em.py:225`
- **用途**: 东方财富网-数据中心-特色数据-千股千评-市场热度-市场参与意愿

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `callback` | `f"jQuery11230899775623921407_{int(time.time() * 1000)}"` |  |
| `filter` | `f'(SECURITY_CODE="{symbol}")'` | 过滤表达式 |
| `columns` | `"ALL"` | 返回字段，ALL=全部 |
| `source` | `"WEB"` | 客户端标识 |
| `client` | `"WEB"` | 客户端标识 |
| `reportName` | `"RPT_STOCK_PARTICIPATION"` | 数据集标识 |
| `sortColumns` | `"TRADE_DATE"` | 排序字段 |
| `sortTypes` | `"-1"` | -1降序 1升序 |
| `pageSize` | `"30"` | 每页条数 |
| `_` | `int(time.time() * 1000)` |  |

---

## 120. `RPT_TENHOLDERS_COOPHOLDERS`

- **akshare 入口**: `stock_gdfx_holding_teamwork_em(symbol: str = "社保")`
- **源码**: `stock_feature/stock_gdfx_em.py:954`
- **用途**: 东方财富网-数据中心-股东分析-股东协同-十大股东

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `sortColumns` | `"COOPERAT_NUM,HOLDER_NEW,COOPERAT_HOLDER_NEW"` | 排序字段 |
| `sortTypes` | `"-1,-1,-1"` | -1降序 1升序 |
| `pageSize` | `"500"` | 每页条数 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `reportName` | `"RPT_TENHOLDERS_COOPHOLDERS"` | 数据集标识 |
| `columns` | `"ALL"` | 返回字段，ALL=全部 |
| `source` | `"WEB"` | 客户端标识 |
| `client` | `"WEB"` | 客户端标识 |

**返回字段**（按列序，共 10 列）

| 列序 | 字段含义 |
|---|---|
| 0 | 序号 |
| 2 | 股东名称 |
| 3 | 股东类型 |
| 5 | 协同股东名称 |
| 6 | 协同股东类型 |
| 7 | 协同次数 |
| 9 | 个股详情 |

---

## 121. `RPT_VALUEANALYSIS_DET`

- **akshare 入口**: `stock_value_em(symbol: str = "300766")`
- **源码**: `stock_feature/stock_value_em.py:13`
- **用途**: 东方财富网-数据中心-估值分析-每日互动-每日互动-估值分析

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `sortColumns` | `"TRADE_DATE"` | 排序字段 |
| `sortTypes` | `"-1"` | -1降序 1升序 |
| `pageSize` | `"5000"` | 每页条数 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `reportName` | `"RPT_VALUEANALYSIS_DET"` | 数据集标识 |
| `columns` | `"ALL"` | 返回字段，ALL=全部 |
| `quoteColumns` | `""` | 行情字段注入 |
| `source` | `"WEB"` | 客户端标识 |
| `client` | `"WEB"` | 客户端标识 |
| `filter` | `f'(SECURITY_CODE="{symbol}")'` | 过滤表达式 |

**字段重命名**（英文原始名 → 中文含义）

| 原始字段 | 含义 |
|---|---|
| `TRADE_DATE` | 数据日期 |
| `CLOSE_PRICE` | 当日收盘价 |
| `CHANGE_RATE` | 当日涨跌幅 |
| `TOTAL_MARKET_CAP` | 总市值 |
| `NOTLIMITED_MARKETCAP_A` | 流通市值 |
| `TOTAL_SHARES` | 总股本 |
| `FREE_SHARES_A` | 流通股本 |
| `PE_TTM` | PE(TTM) |
| `PE_LAR` | PE(静) |
| `PB_MRQ` | 市净率 |
| `PEG_CAR` | PEG值 |
| `PCF_OCF_TTM` | 市现率 |
| `PS_TTM` | 市销率 |

---

## 122. `RPT_WEB_RESPREDICT`

- **akshare 入口**: `stock_profit_forecast_em(symbol: str = "")`
- **源码**: `stock_fundamental/stock_profit_forecast_em.py:14`
- **用途**: 东方财富网-数据中心-研究报告-盈利预测

**请求参数**

| 参数 | 取值/表达式 | 说明 |
|---|---|---|
| `reportName` | `"RPT_WEB_RESPREDICT"` | 数据集标识 |
| `columns` | `"WEB_RESPREDICT"` | 返回字段，ALL=全部 |
| `pageNumber` | `"1"` | 页码，从1起 |
| `pageSize` | `"500"` | 每页条数 |
| `sortTypes` | `"-1"` | -1降序 1升序 |
| `sortColumns` | `"RATING_ORG_NUM"` | 排序字段 |
| `p` | `"1"` |  |
| `pageNo` | `"1"` |  |
| `pageNum` | `"1"` |  |

**返回字段**（按列序，共 32 列）

| 列序 | 字段含义 |
|---|---|
| 0 | 序号 |
| 2 | 代码 |
| 3 | 名称 |
| 4 | 研报数 |
| 5 | 机构投资评级(近六个月)-买入 |
| 6 | 机构投资评级(近六个月)-增持 |
| 7 | 机构投资评级(近六个月)-中性 |
| 8 | 机构投资评级(近六个月)-减持 |
| 9 | 机构投资评级(近六个月)-卖出 |
| 12 | f"{year1}预测每股收益 |
| 15 | f"{year2}预测每股收益 |
| 18 | f"{year3}预测每股收益 |
| 21 | f"{year4}预测每股收益 |
