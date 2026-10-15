"""东财 datacenter 族: 榜单类 (互持/成分/基金/融资融券/行业/概念/分红/开盘)"""
"""东方财富 (eastmoney) —— 32 个方法

端点: push2 / push2his / emweb / datacenter-web
反爬: push2 需固定 ut token; datacenter 需 source=WEB+client=PC; 公告一路走 curl 子进程

"""
from webtool.stock.bridge.sources._base import _err, _ok





class EmDatacenterMixin:
    """端点族 mixin; 只依赖 self._em_* (由 EmCoreMixin 提供)"""

    def em_datacenter(self, report_name: str = "RPT_MUTUAL_STOCK_HOLDRANKS",
                      **kwargs) -> dict:
        """东财 datacenter 数据 (参数依 report_name 而异)"""
        params = {"reportName": report_name,
                  "columns": "all", "pageNumber": 1, "pageSize": 50,
                  "sortColumns": "", "sortTypes": -1, "source": "WEB",
                  "client": "PC", "p": 1, "pageNo": 1, "pageNum": 1}
        params.update(kwargs)
        return self._em_get("https://datacenter-web.eastmoney.com/api/data/v1/get", params)

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

