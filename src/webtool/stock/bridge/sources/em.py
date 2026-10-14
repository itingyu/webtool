"""东方财富 (eastmoney) —— 32 个方法

端点: push2 / push2his / emweb / datacenter-web
反爬: push2 需固定 ut token; datacenter 需 source=WEB+client=PC; 公告一路走 curl 子进程

"""
from webtool.stock.bridge.sources._base import _err, _ok, SourceBase
from webtool.stock.bridge.sources import _symbol
import json
import re


from curl_cffi import requests as cffi

class EmSource(SourceBase):
    """东方财富 (eastmoney) 方法集 —— 由 sources/__init__.py 的 APIClient 混入"""

    def _em_get(self, url: str, params: dict) -> dict:
        try:
            # push2 必须带 ut token, 否则沙盒 IP 被 ban (RemoteDisconnected)
            params = dict(params)
            if "ut" not in params:
                params["ut"] = "13697a1cc677c8bfa9a496437bfef419"
            r = self._std.get(url, params=params, timeout=self.BASE_TIMEOUT)
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            j = r.json()
            return _ok(j.get("data") or j, len(r.text))
        except Exception as e:
            return _err(str(e))

    @staticmethod

    def _em_secid(code: str) -> str:
        """A 股代码 -> secid (1=沪, 0=深) —— 归一见 `_symbol.em_secid`

        原实现只认裸 6 位: 传 `SH600519` 会被当成深市打到 `0.SH600519`,
        拿回另一只票的数据 (HTTP 200, 信封 ok=True)。市场前缀现在统一在
        `_symbol` 判定, 北交所 (4/8/92 开头) 也正确归到 `0.`。
        """
        return _symbol.em_secid(code)


    def _em_f10(self, endpoint: str, code: str) -> dict:
        """emweb F10 (code 认 '600519' / 'SH600519' / '600519.SH')"""
        try:
            r = self._std.get(
                f"https://emweb.eastmoney.com/PC_HSF10/{endpoint}",
                params={"code": _symbol.em(code)},
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            text = r.text
            if text.startswith("{"):
                return _ok(r.json(), len(text))
            elif "<html" in text.lower()[:200]:
                return _ok({"html_len": len(text)}, len(text))
            else:
                return _err("未知响应格式")
        except Exception as e:
            return _err(str(e))

    def _em_f10_datacenter(self, report_name: str, code: str,
                           page_size: int = 3) -> dict:
        """F10 datacenter (code 认 '600519' / 'SH600519' / '600519.SH')"""
        try:
            r = self._std.get(
                "https://datacenter-web.eastmoney.com/api/data/v1/get",
                params={"reportName": report_name, "columns": "ALL",
                        "filter": f'(SECUCODE="{_symbol.em_secucode(code)}")',
                        "pageNumber": 1, "pageSize": page_size,
                        "sortTypes": -1, "source": "WEB", "client": "PC"},
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            j = r.json()
            if not j.get("success"):
                return _err(f"success=False msg={j.get('message','')[:50]}")
            data = j.get("result", {}).get("data", [])
            return _ok({"rows": data, "report": report_name}, len(r.text))
        except Exception as e:
            return _err(str(e))
    def em_stock_get(self, code: str = "688825") -> dict:
        """A 股实时行情 (价格字段已 /100)"""
        r = self._em_get(
            "https://push2.eastmoney.com/api/qt/stock/get",
            {"secid": self._em_secid(code),
             "fields": "f43,f44,f45,f46,f47,f48,f57,f58,f60,f168,f169,f170"},
        )
        if r["ok"] and isinstance(r["data"], dict):
            # /100 还原价格字段
            for k in ("f43", "f44", "f45", "f46", "f60", "f169"):
                if k in r["data"] and r["data"][k] is not None:
                    r["data"][k] = r["data"][k] / 100.0
        return r

    def em_kline(self, code: str = "688825", klt: int = 101,
                 beg: str = "0", end: str = "20500101", fqt: int = 1,
                 lmt: int = 60) -> dict:
        """K 线 (101日 / 102周 / 103月)"""
        r = self._em_get(
            "https://push2his.eastmoney.com/api/qt/stock/kline/get",
            {"secid": self._em_secid(code), "klt": klt, "beg": beg,
             "end": end, "fqt": fqt, "lmt": lmt},
        )
        if r["ok"]:
            klines = r["data"].get("klines", []) if isinstance(r["data"], dict) else []
            rows = []
            for line in klines:
                parts = line.split(",")
                if len(parts) >= 11:
                    rows.append({
                        "date": parts[0], "open": float(parts[1]),
                        "close": float(parts[2]), "high": float(parts[3]),
                        "low": float(parts[4]), "volume": int(parts[5]),
                        "amount": float(parts[6]),
                        "amplitude": float(parts[7]), "pct_change": float(parts[8]),
                        "chg": float(parts[9]), "turnover": float(parts[10]),
                    })
            r["data"] = {"rows": rows, "raw_count": len(klines)}
        return r

    def em_datacenter(self, report_name: str = "RPT_MUTUAL_STOCK_HOLDRANKS",
                      **kwargs) -> dict:
        """东财 datacenter 数据 (参数依 report_name 而异)"""
        params = {"reportName": report_name,
                  "columns": "all", "pageNumber": 1, "pageSize": 50,
                  "sortColumns": "", "sortTypes": -1, "source": "WEB",
                  "client": "PC", "p": 1, "pageNo": 1, "pageNum": 1}
        params.update(kwargs)
        return self._em_get("https://datacenter-web.eastmoney.com/api/data/v1/get", params)

    def em_f10_company(self, code: str = "SH688825") -> dict:
        """公司概况"""
        return self._em_get(
            "https://emweb.eastmoney.com/PC_HSF10/CompanySurvey/PageAjax",
            {"code": code},
        )

    def em_f10_profile(self, code: str = "SH688825") -> dict:
        """公司详细资料 (高管/股东/主营)"""
        return self._em_get(
            "https://emweb.eastmoney.com/PC_HSF10/CompanySurvey/CompanySurveyAjax",
            {"code": code},
        )

    def em_company_survey(self, code: str = "SH600519") -> dict:
        """公司基础信息 (东财 PC_HSF10/CompanySurvey/PageAjax)

        走 PC_HSF10/CompanySurvey/PageAjax size=1840~1953 (1718 占位符是误判)

        返回 jbzl (基本信息) + fxxg (风险相关):
        - ORG_NAME/ORG_NAME_EN/FORMERNAME/STR_NAMEA/SECURITY_TYPE
        - EM2016/INDUSTRYCSRC1/TRADE_MARKET
        - PRESIDENT/LEGAL_PERSON/SECRETARY/CHAIRMAN/INDEDIRECTORS
        - ORG_TEL/ORG_EMAIL/ORG_FAX/ORG_WEB
        - REG_CAPITAL/EMP_NUM/REG_NUM/REG_ADDRESS/PROVINCE
        - LAW_FIRM/ACCOUNTFIRM_NAME
        - ORG_PROFILE (公司简介)
        - BUSINESS_SCOPE (经营范围)
        - FOUND_DATE/LISTING_DATE/AFTER_ISSUE_PE
        """
        try:
            r = self._em_get(
                "https://emweb.eastmoney.com/PC_HSF10/CompanySurvey/PageAjax",
                {"code": code},
            )
            return r
        except Exception as e:
            return _err(str(e))

    def em_profit_forecast(self, code: str = "SH600519") -> dict:
        """盈利预测/综合评级 (东财 PC_HSF10/ProfitForecast/PageAjax)

        走 PC_HSF10/ProfitForecast/PageAjax size=37053 (1718 占位符是误判)

        已验证: 茅台 19-20 家机构评级 1月内买入(17)增持(2) 买入(18)增持(2)
        2月内, 3月内, 6月内, 1年内 综合评级

        返回 pjtj (评级统计) 含:
        - SECURITY_CODE / SECUCODE / SECURITY_NAME_ABBR
        - DATE_TYPE_CODE / DATE_TYPE (1月内/2月内/...)
        - COMPRE_RATING_NUM (综合评级分数 5分制)
        - COMPRE_RATING (买入/增持/中性/减持/卖出)
        - RATING_ORG_NUM / RATING_BUY_NUM / RATING_ADD_NUM
        - RATING_NEUTRAL_NUM / RATING_REDUCE_NUM / RATING_SALE_NUM
        """
        try:
            r = self._em_get(
                "https://emweb.eastmoney.com/PC_HSF10/ProfitForecast/PageAjax",
                {"code": code},
            )
            return r
        except Exception as e:
            return _err(str(e))

    # ------------------------------------------------------------------
    # 巨潮 (2 个)
    # ------------------------------------------------------------------

    def em_dmsk_balance(self, code: str = "600519.SH", page_size: int = 3) -> dict:
        """东财新版资产负债表 (RPT_DMSK_FN_BALANCE)

        走 RPT_DMSK_FN_BALANCE (3 rows 57 字段, 含 PARENT_NETPROFIT/TOTAL_OPERATE_INCOME);
        老 reportName RPT_DMSK_FN_DEBT 等报 "报表配置不存在"

        已验证: SH600519/SZ000858/SH688825/SZ300750 全股 3 rows
        """
        try:
            r = self._std.get(
                "https://datacenter-web.eastmoney.com/api/data/v1/get",
                params={"reportName": "RPT_DMSK_FN_BALANCE", "columns": "ALL",
                        "filter": f'(SECUCODE="{code}")',
                        "pageNumber": 1, "pageSize": page_size,
                        "sortTypes": -1, "source": "WEB", "client": "PC"},
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            j = r.json()
            data = j.get("result", {}).get("data", [])
            return _ok({
                "code": code, "rows": len(data), "data": data,
                "sample_fields": list(data[0].keys()) if data else [],
            }, len(r.text))
        except Exception as e:
            return _err(str(e))

    def em_dmsk_income(self, code: str = "600519.SH", page_size: int = 30) -> dict:
        """东财新版利润表 (RPT_DMSK_FN_INCOME)

        走 RPT_DMSK_FN_INCOME (30 rows 46 字段, 含 REPORT_DATE/NOTICE_DATE/
        TOTAL_OPERATE_INCOME/PARENT_NETPROFIT); 老 RPT_DMSK_FN_DEBT 不可用

        已验证: 600519 30 rows, 含近 10 年年报+半年报+季报
        """
        try:
            r = self._std.get(
                "https://datacenter-web.eastmoney.com/api/data/v1/get",
                params={"reportName": "RPT_DMSK_FN_INCOME", "columns": "ALL",
                        "filter": f'(SECUCODE="{code}")',
                        "pageNumber": 1, "pageSize": page_size,
                        "sortTypes": -1, "source": "WEB", "client": "PC"},
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            j = r.json()
            data = j.get("result", {}).get("data", [])
            return _ok({
                "code": code, "rows": len(data), "data": data,
                "sample_fields": list(data[0].keys()) if data else [],
            }, len(r.text))
        except Exception as e:
            return _err(str(e))

    # ===== 第15轮反爬: RPT_F10_FINANCE_B* 完整资产负债表/利润表/现金流量表 =====

    def em_f10_balance(self, code: str = "600519.SH", page_size: int = 3) -> dict:
        """东财新版资产负债表 (RPT_F10_FINANCE_BBALANCE)

        走 RPT_F10_FINANCE_BBALANCE size=9000+ 200+ 字段; 老接口报 "报表配置不存在"

        字段:
        - SECURITY_CODE/SECUCODE/SECURITY_NAME_ABBR
        - REPORT_DATE/REPORT_DATE_NAME/REPORT_TYPE
        - TOTAL_ASSETS/TOTAL_LIABILITIES/TOTAL_EQUITY
        - SHARE_CAPITAL/CAPITAL_RESERVE/SURPLUS_RESERVE/UNASSIGN_RPOFIT
        - LOAN_ADVANCE/FIXED_ASSET/CIP/GOODWILL
        - 等200+ 字段 (含 _YOY 同比增长)
        """
        return self._em_get(
            "https://datacenter-web.eastmoney.com/api/data/v1/get",
            {"reportName": "RPT_F10_FINANCE_BBALANCE",
             "columns": "ALL",
             "pageNumber": 1, "pageSize": page_size,
             "filter": f'(SECUCODE="{code}")',
             "sortTypes": -1, "source": "WEB", "client": "PC"},
        )

    def em_f10_income(self, code: str = "600519.SH", page_size: int = 3) -> dict:
        """东财新版利润表 (RPT_F10_FINANCE_BINCOME)"""
        return self._em_get(
            "https://datacenter-web.eastmoney.com/api/data/v1/get",
            {"reportName": "RPT_F10_FINANCE_BINCOME",
             "columns": "ALL",
             "pageNumber": 1, "pageSize": page_size,
             "filter": f'(SECUCODE="{code}")',
             "sortTypes": -1, "source": "WEB", "client": "PC"},
        )

    def em_f10_cashflow(self, code: str = "600519.SH", page_size: int = 3) -> dict:
        """东财新版现金流量表 (RPT_F10_FINANCE_BCASHFLOW)"""
        return self._em_get(
            "https://datacenter-web.eastmoney.com/api/data/v1/get",
            {"reportName": "RPT_F10_FINANCE_BCASHFLOW",
             "columns": "ALL",
             "pageNumber": 1, "pageSize": page_size,
             "filter": f'(SECUCODE="{code}")',
             "sortTypes": -1, "source": "WEB", "client": "PC"},
        )

    # ===== 第5轮反爬: emweb.eastmoney.com F10 不带 PageAjax =====

    def em_f10_html(self, section: str = "CapitalStockStructure",
                    code: str = "SH600519") -> dict:
        """东财 F10 不带 PageAjax 后缀 (反爬绕过)

        走 /PC_HSF10/{section} (不带 PageAjax) —— 4 个 section 通 (data 在 HTML);
        带 PageAjax 的 17 个 section 全返 1718 占位符

        真通 section:
          CapitalStockStructure size=45150 rows=41 (股本结构)
          ShareholderResearch size=46076 rows=26 (股东研究)
          BusinessAnalysis size=24190 rows=3 (业务分析)
          NewFinanceAnalysis size=472358 rows=1045 (财报分析, 含详细数据)

        其他 section (Dividend/Split/Executive/...) 仍 1718 占位符
        """
        try:
            r = self._std.get(
                f"https://emweb.eastmoney.com/PC_HSF10/{section}",
                params={"code": code},
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            sz = len(r.text)
            if sz == 1718:
                return _err(f"section {section} 返 1718 占位符 (无数据)")
            # 解析 HTML 找数据
            rows = re.findall(r'<tr[^>]*>(.*?)</tr>', r.text, re.DOTALL)
            # 找表格数据
            tables = re.findall(r'<table[^>]*>(.*?)</table>', r.text, re.DOTALL)
            return _ok({
                "section": section, "code": code,
                "size": sz,
                "rows_in_html": len(rows),
                "tables_count": len(tables),
                "html": r.text,  # 完整 HTML
            }, sz)
        except Exception as e:
            return _err(str(e))

    # ===== 第6轮反爬: stock.eastmoney.com JS 暴露的新真通 endpoint =====

    def em_open_data(self, page_size: int = 10) -> dict:
        """东财开盘数据/投资者统计 (datacenter-web RPT_STOCK_OPEN_DATA)

        返回 STATISTICS_DATE/ADD_INVESTOR/END_INVESTOR_A/B/CLOSE_PRICE/CHANGE_RATE/TOTAL_MARKET_CAP
        """
        try:
            r = self._std.get(
                "https://datacenter-web.eastmoney.com/api/data/v1/get",
                params={"reportName": "RPT_STOCK_OPEN_DATA", "columns": "ALL",
                        "pageNumber": 1, "pageSize": page_size,
                        "sortColumns": "STATISTICS_DATE", "sortTypes": -1,
                        "source": "WEB", "client": "PC"},
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            j = r.json()
            data = j.get("result", {}).get("data", [])
            return _ok({
                "total": len(data), "rows": data,
                "sample_fields": list(data[0].keys()) if data else [],
            }, len(r.text))
        except Exception as e:
            return _err(str(e))

    def em_mutual_hold(self, page_size: int = 20) -> dict:
        """东财互持/沪深港通持股 (datacenter-web RPT_MUTUAL_HOLD)

        返回 SECURITY_CODE/SECURITY_NAME/TRADE_MARKET_CODE/FREE_SHARES_RATIO/MUTUAL_TYPE/HOLD_DATE/HOLD_SHARES
        """
        try:
            r = self._std.get(
                "https://datacenter-web.eastmoney.com/api/data/v1/get",
                params={"reportName": "RPT_MUTUAL_HOLD", "columns": "ALL",
                        "pageNumber": 1, "pageSize": page_size,
                        "source": "WEB", "client": "PC"},
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            j = r.json()
            data = j.get("result", {}).get("data", [])
            return _ok({
                "total": len(data), "rows": data,
                "sample_fields": list(data[0].keys()) if data else [],
            }, len(r.text))
        except Exception as e:
            return _err(str(e))

    def em_mutual_holdranking(self, page_size: int = 20) -> dict:
        """东财互持排行 (datacenter-web RPT_MUTUAL_STOCK_HOLDRANKS)

        返回 MUTUAL_TYPE/HOLD_DATE/SECUCODE/SECURITY_NAME/ADD_MARKET_CAP/HOLD_SHARES_CHANGE
        """
        try:
            r = self._std.get(
                "https://datacenter-web.eastmoney.com/api/data/v1/get",
                params={"reportName": "RPT_MUTUAL_STOCK_HOLDRANKS", "columns": "ALL",
                        "pageNumber": 1, "pageSize": page_size,
                        "source": "WEB", "client": "PC"},
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            j = r.json()
            data = j.get("result", {}).get("data", [])
            return _ok({
                "total": len(data), "rows": data,
                "sample_fields": list(data[0].keys()) if data else [],
            }, len(r.text))
        except Exception as e:
            return _err(str(e))

    # ===== 第8轮反爬: RPT_INDEX_CONSTITUENT (brute force) =====

    def em_index_constituent(self, index_code: str = "000300",
                             page_size: int = 10) -> dict:
        """东财指数成分股 (datacenter-web RPT_INDEX_CONSTITUENT)

        brute force RPT_* 找到, size=1018+ rows 含成分股列表

        已验证: 5 rows 默认 (上证指数 000001 + 技源集团等)
        返回 INDEX_CODE / INDEX_NAME / SECUCODE / SECURITY_CODE / SECURITY_NAME_ABBR /
               TRADE_DATE / MARKET / STATE

        index_code: 沪深300=000300, 中证500=000905, 中证1000=000852, 上证指数=000001
        """
        try:
            r = self._std.get(
                "https://datacenter-web.eastmoney.com/api/data/v1/get",
                params={"reportName": "RPT_INDEX_CONSTITUENT", "columns": "ALL",
                        "filter": f'(INDEX_CODE="{index_code}")',
                        "pageNumber": 1, "pageSize": page_size,
                        "source": "WEB", "client": "PC"},
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            j = r.json()
            result = j.get("result") or {}
            data = result.get("data", [])
            return _ok({
                "index_code": index_code, "total": len(data),
                "rows": data,
                "sample_fields": list(data[0].keys()) if data else [],
            }, len(r.text))
        except Exception as e:
            return _err(str(e))

    def em_gem_list(self, page_size: int = 10) -> dict:
        """东财创业板 IPO 列表 (datacenter-web RPT_GEM_LIST)

        返回 APPLY_DATE / APPLY_CODE / COMPANY_NAME / ONLINE_APPLY_PRICE / TOTAL_ISSUE_NUM
        """
        try:
            r = self._std.get(
                "https://datacenter-web.eastmoney.com/api/data/v1/get",
                params={"reportName": "RPT_GEM_LIST", "columns": "ALL",
                        "pageNumber": 1, "pageSize": page_size,
                        "source": "WEB", "client": "PC"},
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            j = r.json()
            data = j.get("result", {}).get("data", [])
            return _ok({
                "total": len(data), "rows": data,
                "sample_fields": list(data[0].keys()) if data else [],
            }, len(r.text))
        except Exception as e:
            return _err(str(e))

    def em_lico_fn_cpd(self, page_size: int = 5) -> dict:
        """东财业绩快报 (datacenter-web RPT_LICO_FN_CPD)

        返回 UPDATE_DATE / REPORTDATE / SECURITY_CODE 等
        """
        try:
            r = self._std.get(
                "https://datacenter-web.eastmoney.com/api/data/v1/get",
                params={"reportName": "RPT_LICO_FN_CPD", "columns": "ALL",
                        "pageNumber": 1, "pageSize": page_size,
                        "source": "WEB", "client": "PC"},
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            j = r.json()
            data = j.get("result", {}).get("data", [])
            return _ok({
                "total": len(data), "rows": data,
                "sample_fields": list(data[0].keys()) if data else [],
            }, len(r.text))
        except Exception as e:
            return _err(str(e))

    def em_fund_rank(self, page_size: int = 5) -> dict:
        """东财基金排行 (datacenter-web RPT_FUND_RANK)

        返回 APPLY_RATE / CHANGE_1Y / CHANGE_3Y 等字段
        """
        try:
            r = self._std.get(
                "https://datacenter-web.eastmoney.com/api/data/v1/get",
                params={"reportName": "RPT_FUND_RANK", "columns": "ALL",
                        "pageNumber": 1, "pageSize": page_size,
                        "source": "WEB", "client": "PC"},
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            j = r.json()
            data = j.get("result", {}).get("data", [])
            return _ok({
                "total": len(data), "rows": data,
                "sample_fields": list(data[0].keys()) if data else [],
            }, len(r.text))
        except Exception as e:
            return _err(str(e))

    def em_margin_list(self, page_size: int = 5) -> dict:
        """东财融资融券列表 (datacenter-web RPT_MARGIN_LIST)

        返回 SECUCODE / SECURITY_NAME_ABBR / MARGIN_BALANCE / MARGIN_NETBUY_AMT /
               CHANGE / CHG / MARGIN_TRADE_AMT / MARGIN_TVAL_RATIO
        """
        try:
            r = self._std.get(
                "https://datacenter-web.eastmoney.com/api/data/v1/get",
                params={"reportName": "RPT_MARGIN_LIST", "columns": "ALL",
                        "pageNumber": 1, "pageSize": page_size,
                        "sortColumns": "MARGIN_BALANCE", "sortTypes": -1,
                        "source": "WEB", "client": "PC"},
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            j = r.json()
            data = j.get("result", {}).get("data", [])
            return _ok({
                "total": len(data), "rows": data,
                "sample_fields": list(data[0].keys()) if data else [],
            }, len(r.text))
        except Exception as e:
            return _err(str(e))

    def em_industry_list(self, page_size: int = 5) -> dict:
        """东财行业列表 (datacenter-web RPT_INDUSTRY_LIST)

        14 页 板块数据，含 BK0xxx 板块代码
        字段: BOARD_CODE / BOARD_NAME / LATEST_DATE / CHANGERATE_3M / RANK_LABEL
        """
        try:
            r = self._std.get(
                "https://datacenter-web.eastmoney.com/api/data/v1/get",
                params={"reportName": "RPT_INDUSTRY_LIST", "columns": "ALL",
                        "pageNumber": 1, "pageSize": page_size,
                        "source": "WEB", "client": "PC"},
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            j = r.json()
            result = j.get("result", {})
            return _ok({
                "total_pages": result.get("pages"),
                "rows": result.get("data", []),
            }, len(r.text))
        except Exception as e:
            return _err(str(e))

    def em_concept_list(self, page_size: int = 5) -> dict:
        """东财概念列表 (datacenter-web RPT_CONCEPT_LIST)

        168 页 概念板块
        字段: BOARD_CODE / BOARD_NAME / DATE_JRRQ
        """
        try:
            r = self._std.get(
                "https://datacenter-web.eastmoney.com/api/data/v1/get",
                params={"reportName": "RPT_CONCEPT_LIST", "columns": "ALL",
                        "pageNumber": 1, "pageSize": page_size,
                        "source": "WEB", "client": "PC"},
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            j = r.json()
            result = j.get("result", {})
            return _ok({
                "total_pages": result.get("pages"),
                "rows": result.get("data", []),
            }, len(r.text))
        except Exception as e:
            return _err(str(e))

    def em_dividend_rank(self, page_size: int = 5) -> dict:
        """东财分红排行 (datacenter-web RPT_DIVIDEND_RANK)

        3616 页 分红排行
        字段: SECUCODE / SECURITY_CODE / DIVIDEND_RATIO / RISE_YEARS /
               PER_NETCASH / PARENT_NETPROFIT / PARENT_NETPROFIT_YOY / DIVIDEND_NEWRATIO
        """
        try:
            r = self._std.get(
                "https://datacenter-web.eastmoney.com/api/data/v1/get",
                params={"reportName": "RPT_DIVIDEND_RANK", "columns": "ALL",
                        "pageNumber": 1, "pageSize": page_size,
                        "source": "WEB", "client": "PC"},
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            j = r.json()
            result = j.get("result", {})
            return _ok({
                "total_pages": result.get("pages"),
                "rows": result.get("data", []),
            }, len(r.text))
        except Exception as e:
            return _err(str(e))

    # ===== 第11轮反爬: 腾讯 qt.gtimg.cn (新浪 backup) =====

    def em_kamt(self) -> dict:
        """东财沪股通/深股通资金流向 (push2.eastmoney.com/api/qt/kamt/get)

        走 kamt/get (未被 ban, curl_cffi + ut token 直接可调);
        push2.eastmoney.com 在沙盒里 RemoteDisconnected

        返回 hk2sh / sh2hk / sz2hk / hk2sz (沪→港/港→沪/深→港/港→深) 资金流向
        字段: status, dayNetAmtIn, dayAmtRemain, dayAmtThreshold, date2, buyAmt

        已验证: size=585 含完整 JSON
        """
        try:
            # 用类内会话 (已接 netx 路由) —— 局部自建 Session 会绕过代理规则
            r = self._xueqiu_session().get(
                "https://push2.eastmoney.com/api/qt/kamt/get",
                params={"fields1": "f1,f2,f3,f4",
                        "fields2": "f51,f52,f53,f54,f56,f60",
                        "ut": "13697a1cc677c8bfa9a496437bfef419"},
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            j = r.json()
            return _ok(j, len(r.text))
        except Exception as e:
            return _err(str(e))

    # ------------------------------------------------------------------
    # 扩展接口 (api_docs_extra.md 第二轮)
    # ------------------------------------------------------------------

    def em_f10_lico_fn_cpd(self, code: str = "600519.SH", page_size: int = 3) -> dict:
        """东财 F10 业绩表 (RPT_LICO_FN_CPD, 全市场 485301 条)"""
        try:
            r = self._std.get(
                "https://datacenter-web.eastmoney.com/api/data/v1/get",
                params={"reportName": "RPT_LICO_FN_CPD", "columns": "ALL",
                        "filter": f'(SECUCODE="{code}")',
                        "pageNumber": 1, "pageSize": page_size,
                        "sortTypes": -1, "source": "WEB", "client": "PC"},
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            j = r.json()
            if not j.get("success"):
                return _err(f"success=False msg={j.get('message','')[:50]}")
            data = j.get("result", {}).get("data", [])
            return _ok({"rows": data, "report": "RPT_LICO_FN_CPD"}, len(r.text))
        except Exception as e:
            return _err(str(e))

    def em_capital_structure(self, code: str = "SH600519") -> dict:
        """东财 F10 股本结构 (xsjj/gbjg/lngbbd/gbgc)"""
        return self._em_f10("CapitalStockStructure/PageAjax", code)

    def em_shareholder_research(self, code: str = "SH600519") -> dict:
        """东财 F10 股东户数 (gdrs)"""
        return self._em_f10("ShareholderResearch/PageAjax", code)

    def em_business_analysis(self, code: str = "SH600519") -> dict:
        """东财 F10 业务分析 (zyfw)"""
        return self._em_f10("BusinessAnalysis/PageAjax", code)

    def em_new_finance_analysis(self, code: str = "SH600519",
                                type_: int = 0) -> dict:
        """东财 F10 财务分析页 (HTML, type: 0综合/1资产/2利润/3现金流)"""
        try:
            r = self._std.get(
                "https://emweb.eastmoney.com/PC_HSF10/NewFinanceAnalysis/Index",
                params={"type": type_, "code": code},
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            return _ok({"html_len": len(r.text)}, len(r.text))
        except Exception as e:
            return _err(str(e))

    # 东财 F10 datacenter

    def em_f10_main_finadata(self, code: str = "600519.SH") -> dict:
        """东财 F10 主要财务指标 (165 列)"""
        return self._em_f10_datacenter("RPT_F10_FINANCE_MAINFINADATA", code)

    def em_f10_gincome(self, code: str = "600519.SH") -> dict:
        """东财 F10 利润表"""
        return self._em_f10_datacenter("RPT_F10_FINANCE_GINCOME", code)
