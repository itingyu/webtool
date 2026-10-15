"""东财 F10 族: 公司资料 / 财务三表 / 股本股东 / 业绩与评级"""
"""东方财富 (eastmoney) —— 32 个方法

端点: push2 / push2his / emweb / datacenter-web
反爬: push2 需固定 ut token; datacenter 需 source=WEB+client=PC; 公告一路走 curl 子进程

"""
from webtool.stock.bridge.sources._base import _err, _ok
import re





class EmF10Mixin:
    """端点族 mixin; 只依赖 self._em_* (由 EmCoreMixin 提供)"""

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

    def em_dmsk_cashflow(self, code: str = "600519.SH", page_size: int = 30) -> dict:
        """东财新版现金流量表 (RPT_DMSK_FN_CASHFLOW)

        RPT_F10_FINANCE_BCASHFLOW 对多只股票返回空 (success=false), 备源走
        大盘现金流量表; 与 balance/income 同构 (REPORT_DATE/TOTAL_OPERATE_INCOME)。
        """
        try:
            r = self._std.get(
                "https://datacenter-web.eastmoney.com/api/data/v1/get",
                params={"reportName": "RPT_DMSK_FN_CASHFLOW", "columns": "ALL",
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

    def em_f10_main_finadata(self, code: str = "600519.SH") -> dict:
        """东财 F10 主要财务指标 (165 列)"""
        return self._em_f10_datacenter("RPT_F10_FINANCE_MAINFINADATA", code)

    def em_f10_gincome(self, code: str = "600519.SH") -> dict:
        """东财 F10 利润表"""
        return self._em_f10_datacenter("RPT_F10_FINANCE_GINCOME", code)

