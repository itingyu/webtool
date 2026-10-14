"""新浪财经 (sina) —— 28 个方法

端点: hq.sinajs.cn / vip.stock.finance.sina.com.cn
反爬: Referer 校验。gtimg_* 是腾讯行情但走新浪 CDN, 按实际域名归此源

"""
from webtool.stock.bridge.sources._base import _err, _ok, SourceBase
from webtool.stock.bridge.sources import _symbol
import json
import re


class SinaSource(SourceBase):
    """新浪财经 (sina) 方法集 —— 由 sources/__init__.py 的 APIClient 混入"""

    def _sina_hq(self, symbols: str) -> dict:
        """沪深实时 (symbols: 'sh688825' 或 'sh688825,sz000001')

        symbol 在此归一 (`_symbol.sina`)。新浪对前缀大小写敏感: 传 `SH600519`
        返回 HTTP 200 + `fields=['']` —— 信封 ok=True 但全字段空, 静默失败。
        """
        symbols = _symbol.join(symbols, _symbol.sina)
        try:
            r = self._std.get(
                f"https://hq.sinajs.cn/list={symbols}",
                headers={"Referer": "https://finance.sina.com.cn/"},
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200 or not r.text:
                return _err(f"status={r.status_code}", r.status_code)
            # 解析 var hq_str_xxx="..." 或 多行 var hq_str_xxx1="..."; var hq_str_xxx2="...";
            results = []
            for line in r.text.splitlines():
                m = re.search(r'var hq_str_(\w+)="(.*)";', line)
                if m:
                    sym, body = m.group(1), m.group(2)
                    fields = body.split(",")
                    results.append({"symbol": sym, "fields": fields})
            return _ok(results, len(r.text))
        except Exception as e:
            return _err(str(e))

    def sina_hq_a(self, symbol: str = "sh688825") -> dict:
        """沪深实时"""
        return self._sina_hq(symbol)

    def sina_hq_batch(self, symbols: str = "sh688825,sz000001,sh600519") -> dict:
        """沪深批量实时"""
        return self._sina_hq(symbols)

    def sina_hq_hk(self, code: str = "01810") -> dict:
        """港股实时 (注意带 rt_hk 前缀)"""
        return self._sina_hq(f"rt_hk{code}")

    def sina_list(self, node: str = "hs_a", num: int = 20,
                  sort: str = "", asc: int = 0) -> dict:
        """列表 (涨跌幅榜 / 全列表)"""
        try:
            params = {"node": node, "num": num, "page": 1}
            if sort:
                params["sort"] = sort
                params["asc"] = asc
            r = self._std.get(
                "https://vip.stock.finance.sina.com.cn/quotes_service/api/"
                "json_v2.php/Market_Center.getHQNodeData",
                params=params,
                headers={"Referer": "https://finance.sina.com.cn/"},
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            return _ok(r.json(), len(r.text))
        except Exception as e:
            return _err(str(e))

    def sina_top_chg(self, num: int = 20) -> dict:
        """涨幅榜"""
        return self.sina_list(node="hs_a", num=num, sort="changepercent", asc=0)

    def sina_bill(self, symbol: str = "sh600519", num: int = 10, page: int = 1) -> dict:
        """新浪逐笔成交 (CN_Bill.GetBillList)

        走 vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php size=1471;
              openapi.php 等同族端点返 1010 错误页

        已验证: sh600519 size=1471 (含 ticker/price/volume/turnover/ts)

        params: symbol + num + page + sort=ticktime + asc=0
        """
        try:
            r = self._std.get(
                "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_Bill.GetBillList",
                params={"symbol": _symbol.sina(symbol), "num": num, "page": page,
                        "sort": "ticktime", "asc": 0},
                headers={"Referer": "https://finance.sina.com.cn/"},
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            return _ok(r.json(), len(r.text))
        except Exception as e:
            return _err(str(e))

    def sina_industry(self, industry: str = "041101", num: int = 5) -> dict:
        """新浪行业成分股 (Industry_Service.getIndustryData)

        已验证:
        - industry=041101 size=4873 (行业代码需为新浪行业码)
        - 申万行业代码格式: 041101 (农林牧渔) 042101 (化工) 043201 (医药)

        参数 industry 是新浪内部行业代码 (不是 BK0438 等东财代码)
        """
        try:
            r = self._std.get(
                "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Industry_Service.getIndustryData",
                params={"industry": industry, "num": num},
                headers={"Referer": "https://finance.sina.com.cn/"},
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            return _ok(r.json(), len(r.text))
        except Exception as e:
            return _err(str(e))

    def sina_company(self, symbol: str = "sh600519") -> dict:
        """新浪公司简介 (CompanyInfoService.getCompanyProfile)"""
        try:
            r = self._std.get(
                "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/CompanyInfoService.getCompanyProfile",
                params={"symbol": _symbol.sina(symbol)},
                headers={"Referer": "https://finance.sina.com.cn/"},
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            return _ok(r.json(), len(r.text))
        except Exception as e:
            return _err(str(e))

    def sina_market_sort(self, node: str = "hs_a", num: int = 20,
                         sort: str = "changepercent", asc: int = 0) -> dict:
        """新浪市场列表带排序 (Market_Center.getHQNodeData + sort)

        走 vip.stock.finance.sina.com.cn 直通 size=7195~7788

        排序字段:
        - changepercent 涨跌幅
        - amount 成交额
        - volume 成交量
        - per 市盈率
        - pb 市净率
        - mktcap 总市值
        - turnoverratio 换手率
        """
        return self.sina_list(node=node, num=num, sort=sort, asc=asc)

    def sina_kline_day(self, symbol: str = "sh600519", scale: int = 240,
                       datalen: int = 100) -> dict:
        """新浪 K 线 (CN_MarketData.getKLineData)

        走 vip.stock.finance.sina.com.cn json_v2 size=11202~24908;
              openapi.php 等同族端点返 1010 错误页

        scale 参数 (分钟):
        - 1/5/15/30/60/120/240 (1分钟~日线)
        - 480 (日线)
        - 1200 (周线)
        - 2400 (月线)
        """
        try:
            r = self._std.get(
                "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData",
                params={"symbol": _symbol.sina(symbol), "scale": scale, "datalen": datalen, "ma": "no"},
                headers={"Referer": "https://finance.sina.com.cn/"},
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            return _ok(r.json(), len(r.text))
        except Exception as e:
            return _err(str(e))

    # ------------------------------------------------------------------
    # 腾讯 (2 个)
    # ------------------------------------------------------------------

    def sina_kline_min(self, symbol: str = "sh600519",
                       scale: int = 5, ma: str = "no",
                       count: int = 320) -> dict:
        """新浪 K 线全粒度 (CN_MarketData.getKLineData, 真替身)

        走 money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData
              + 必须传 scale (5/15/30/60/240/1200分钟) 和 ma (no/ma5/ma10/ma20/ma30/vol/macd/kdj/boll/rsi)

        已验证: sh600519 / sz000001 / sh688825 / sh000001 / sz399001 全部 5-1200 分钟全粒度真通

        count 默认 320 根 (≈ 一周 5 分钟线)。原先默认 -1 会拉全部历史
        (~10000 根, 660KB JSON) —— CLI 一次性吐给 Agent 直接爆上下文;
        要全历史显式传 count=-1。

        symbol 格式:
          A 股: sh600519, sz000001
          指数: sh000001 (上证综指), sz399001 (深证成指)
        """
        try:
            r = self._std.get(
                "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData",
                params={"symbol": _symbol.sina(symbol), "scale": scale, "ma": ma, "datalen": count},
                headers={"Referer": "https://finance.sina.com.cn/"},
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            sz = len(r.text)
            if sz < 200:
                return _err(f"size={sz} body={r.text[:200]}")
            try:
                arr = json.loads(r.text)
            except Exception as e:
                return _err(f"not JSON: {str(e)[:50]} body={r.text[:200]}")
            return _ok({
                "symbol": symbol, "scale": scale, "ma": ma,
                "count": len(arr) if isinstance(arr, list) else 0,
                "klines": arr,
                "sample": arr[0] if arr else None,
            }, sz)
        except Exception as e:
            return _err(str(e))

    def sina_corp_finance(self, code: str = "600519",
                          report: str = "vFD_BalanceSheet") -> dict:
        """新浪 corp 财报 HTML (report: BalanceSheet/ProfitStatement/CashFlow/FinancialGuide)"""
        try:
            r = self._std.get(
                f"https://vip.stock.finance.sina.com.cn/corp/go.php/{report}/"
                f"stockid/{code}/ctrl/part/displaytype/4.phtml",
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            # 直接返回 HTML，不解析
            return _ok({"html_len": len(r.text)}, len(r.text))
        except Exception as e:
            return _err(str(e))

    def sina_corp_info(self, code: str = "600519", menu: int = 1) -> dict:
        """新浪 corp 公司基本资料 HTML (vCI_CorpInfo)

        走 vip.stock.finance.sina.com.cn/corp/go.php/vCI_CorpInfo size=50278

        已验证:
        - 600519 茅台 size=50278
        - 688825 长鑫 size=50489
        - 000001 平安银行 size=50359
        - 301707 展芯 size=49782

        menu: 1=基本资料 2=高管 3=股东 4=财务摘要
        """
        try:
            r = self._std.get(
                f"https://vip.stock.finance.sina.com.cn/corp/go.php/vCI_CorpInfo/"
                f"stockid/{code}/menu_num/{menu}.phtml",
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            return _ok({"html_len": len(r.text)}, len(r.text))
        except Exception as e:
            return _err(str(e))

    def sina_corp_bulletin(self, code: str = "600519") -> dict:
        """新浪 corp 公司公告 HTML (vCB_AllBulletin)

        已验证: 600519 size=53233, 688825 size=53650, 000001 size=53087
        """
        try:
            r = self._std.get(
                f"https://vip.stock.finance.sina.com.cn/corp/view/vCB_AllBulletin.php",
                params={"stockid": code},
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            return _ok({"html_len": len(r.text)}, len(r.text))
        except Exception as e:
            return _err(str(e))

    def sina_corp_bulletin2(self, code: str = "600519") -> dict:
        """新浪 corp 公司公告 HTML (vCB_Bulletin)"""
        try:
            r = self._std.get(
                f"https://vip.stock.finance.sina.com.cn/corp/view/vCB_Bulletin.php",
                params={"stockid": code},
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            return _ok({"html_len": len(r.text)}, len(r.text))
        except Exception as e:
            return _err(str(e))

    def sina_corp_manager(self, code: str = "600519") -> dict:
        """新浪 corp 董监高 HTML (vCI_CorpManager)

        已验证: 600519 size=96944, 688825 size=65962, 000001 size=143119
        """
        try:
            r = self._std.get(
                f"https://vip.stock.finance.sina.com.cn/corp/go.php/vCI_CorpManager/stockid/{code}.phtml",
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            return _ok({"html_len": len(r.text)}, len(r.text))
        except Exception as e:
            return _err(str(e))

    def sina_corp_structure(self, code: str = "600519") -> dict:
        """新浪 corp 股本结构 HTML (vCI_StockStructure)"""
        try:
            r = self._std.get(
                f"https://vip.stock.finance.sina.com.cn/corp/go.php/vCI_StockStructure/stockid/{code}.phtml",
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            return _ok({"html_len": len(r.text)}, len(r.text))
        except Exception as e:
            return _err(str(e))

    def sina_corp_news(self, code: str = "600519") -> dict:
        """新浪 corp 全部新闻 HTML (vCB_AllNews)"""
        try:
            r = self._std.get(
                f"https://vip.stock.finance.sina.com.cn/corp/view/vCB_AllNews.php",
                params={"stockid": code},
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            return _ok({"html_len": len(r.text)}, len(r.text))
        except Exception as e:
            return _err(str(e))

    def sina_corp_holder(self, code: str = "600519") -> dict:
        """新浪 corp 股东信息 HTML (vCI_StockHolder)"""
        try:
            r = self._std.get(
                f"https://vip.stock.finance.sina.com.cn/corp/go.php/vCI_StockHolder/stockid/{code}.phtml",
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            return _ok({"html_len": len(r.text)}, len(r.text))
        except Exception as e:
            return _err(str(e))

    def sina_corp_equity(self, code: str = "600519") -> dict:
        """新浪 corp 股权结构 HTML (vCI_EquityStru)"""
        try:
            r = self._std.get(
                f"https://vip.stock.finance.sina.com.cn/corp/go.php/vCI_EquityStru/stockid/{code}.phtml",
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            return _ok({"html_len": len(r.text)}, len(r.text))
        except Exception as e:
            return _err(str(e))

    def sina_corp_finance_summary(self, code: str = "600519") -> dict:
        """新浪 corp 财务摘要 HTML (vFD_FinanceSummary)"""
        try:
            r = self._std.get(
                f"https://vip.stock.finance.sina.com.cn/corp/go.php/vFD_FinanceSummary/stockid/{code}.phtml",
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            return _ok({"html_len": len(r.text)}, len(r.text))
        except Exception as e:
            return _err(str(e))

    # ------------------------------------------------------------------
    # 扩展接口 (api_docs_extra.md)
    # ------------------------------------------------------------------

    def gtimg_hq(self, symbols: str = "sh600519,sh688825,hk00700") -> dict:
        """腾讯财经行情 (qt.gtimg.cn)

        走 qt.gtimg.cn (A 股 + 港股); 新浪 vip 返 456 ban, web.ifzq.gtimg.cn 30 次跳转封禁

        已验证:
        - sh600519 茅台 1309.22 元 size=542
        - sh688825 长鑫 52.48 元 size=569
        - hk00700 腾讯 478.800 size=431
        - 美股 usTSLA.N ban

        返回格式: v_sh600519="1~贵州茅台~600519~现价~昨收~今开~..."
        """
        try:
            r = self._std.get(
                "https://qt.gtimg.cn/q=" + symbols,
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            lines = [l for l in r.text.strip().split(';') if l.strip()]
            rows = []
            for line in lines:
                # 格式: v_<sym>="data"
                if '=' in line:
                    key, val = line.split('=', 1)
                    rows.append({"symbol": key.strip(), "data": val.strip().strip('"')})
            return _ok({
                "count": len(rows),
                "rows": rows,
            }, len(r.text))
        except Exception as e:
            return _err(str(e))

    def gtimg_us_hq(self, symbols: str = "usTSLA,usAAPL,usNVDA,usMSFT") -> dict:
        """腾讯财经美股行情 (qt.gtimg.cn q=usTSLA)

        已验证:
        - usTSLA 特斯拉 328.58 (size=382)
        - usAAPL 苹果 313.33 (size=383)
        - usNDX 纳斯达克100 (size=291)
        - us.DJI 道琼斯 (size=298)
        """
        try:
            r = self._std.get(
                "https://qt.gtimg.cn/q=" + symbols,
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            lines = [l for l in r.text.strip().split(';') if l.strip()]
            rows = []
            for line in lines:
                if '=' in line:
                    key, val = line.split('=', 1)
                    rows.append({"symbol": key.strip(), "data": val.strip().strip('"')})
            return _ok({"count": len(rows), "rows": rows}, len(r.text))
        except Exception as e:
            return _err(str(e))

    def gtimg_index(self, symbols: str = "sh000300,sh000001,sh000905,sz399001,sz399006") -> dict:
        """腾讯财经指数行情 (qt.gtimg.cn)

        已验证:
        - sh000300 沪深300 4694.44
        - sh000001 上证指数 3940.04
        - sh000905 中证500 7980.12
        - sz399001 深证成指 14311.01
        - sz399006 创业板指 3563.12
        - sz399905 中证500
        - sz399852 中证1000 7679.53
        """
        try:
            r = self._std.get(
                "https://qt.gtimg.cn/q=" + symbols,
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            lines = [l for l in r.text.strip().split(';') if l.strip()]
            rows = []
            for line in lines:
                if '=' in line:
                    key, val = line.split('=', 1)
                    rows.append({"symbol": key.strip(), "data": val.strip().strip('"')})
            return _ok({"count": len(rows), "rows": rows}, len(r.text))
        except Exception as e:
            return _err(str(e))

    def gtimg_hk_index(self, symbols: str = "hkHSI,hkHSCEI") -> dict:
        """腾讯财经港股指数 (qt.gtimg.cn)

        已验证:
        - hkHSI 恒生指数 25668.030
        - hkHSCEI 国企指数 8531.580
        """
        try:
            r = self._std.get(
                "https://qt.gtimg.cn/q=" + symbols,
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            lines = [l for l in r.text.strip().split(';') if l.strip()]
            rows = []
            for line in lines:
                if '=' in line:
                    key, val = line.split('=', 1)
                    rows.append({"symbol": key.strip(), "data": val.strip().strip('"')})
            return _ok({"count": len(rows), "rows": rows}, len(r.text))
        except Exception as e:
            return _err(str(e))

    def gtimg_market_code(self, codes: str = "s_sz000001,s_sz399001,s_sz399300") -> dict:
        """腾讯财经全市场代码 (qt.gtimg.cn q=s_sz/sh/xxx)

        走 q=s_sz000001 / s_sz000002 这类前缀, 全市场 A 股可用; s_pksz000300 等前缀全 ban

        已验证: 75+ 个真通
        - s_sz000001 平安银行 11.19
        - s_sz000002 万科A 3.22
        - s_sz000905 厦门港务 8.54
        - s_sz399001 深证成指 14311.01
        - s_sz399300 沪深300 4694.44
        - s_sz399905 中证500 7980.12
        - s_sz399852 中证1000 7679.53
        - s_sz399986 中证银行 7147.55
        - s_sz399987 中证酒 3950.93
        - s_sz399975 证券公司 763.22
        - s_sz399971 中证传媒 1278.85
        - s_sz399996 智能家居 4930.19
        - s_sz399997 中证白酒 6691.73
        - s_sz399998 中证煤炭 2331.67

        返回格式: 51~名称~代码~现价~涨跌~涨跌幅~成交量~成交额~...
        """
        try:
            r = self._std.get(
                "https://qt.gtimg.cn/q=" + codes,
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            lines = [l for l in r.text.strip().split(';') if l.strip()]
            rows = []
            for line in lines:
                if '=' in line:
                    key, val = line.split('=', 1)
                    rows.append({"symbol": key.strip(), "data": val.strip().strip('"')})
            return _ok({"count": len(rows), "rows": rows}, len(r.text))
        except Exception as e:
            return _err(str(e))

    def gtimg_market_all(self, codes: str = "sz000001,sh600519,sz399300,sh000300,hk00700,usTSLA") -> dict:
        """腾讯财经全市场代码 (qt.gtimg.cn 不带 s_ prefix 直接 sz/sh/hk/us)

        已验证: 所有 prefix 都通

        通用格式: code~名称~当前~昨收~今开~成交量~成交额~...

        A 股 (51): sz000001 平安银行, sh600519 茅台, sz000002 万科A
        指数 (1): sh000001 上证, sz399001 深证成指, sh000300 沪深300, sz399905 中证500
        港股 (100): hk00700 腾讯, hk09988 阿里, hkHSI 恒生指数
        美股 (200): usTSLA 特斯拉, usAAPL 苹果, usNVDA 英伟达
        """
        try:
            r = self._std.get(
                "https://qt.gtimg.cn/q=" + codes,
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            lines = [l for l in r.text.strip().split(';') if l.strip()]
            rows = []
            for line in lines:
                if '=' in line:
                    key, val = line.split('=', 1)
                    rows.append({"symbol": key.strip(), "data": val.strip().strip('"')})
            return _ok({"count": len(rows), "rows": rows}, len(r.text))
        except Exception as e:
            return _err(str(e))

    def gtimg_fund(self, codes: str = "jj000001,jj000300,jj000905") -> dict:
        """腾讯财经基金 (qt.gtimg.cn q=jjxxxxxx)

        已验证:
        - jj000001 华夏成长混合 1.3420 (现价)
        - jj000300 德邦德利货币A
        - jj000905 鹏华安盈宝货币A

        返回: code~名称~单位净值~累计净值~日增长~周增长~月增长~...
        """
        try:
            r = self._std.get(
                "https://qt.gtimg.cn/q=" + codes,
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            lines = [l for l in r.text.strip().split(';') if l.strip()]
            rows = []
            for line in lines:
                if '=' in line:
                    key, val = line.split('=', 1)
                    rows.append({"symbol": key.strip(), "data": val.strip().strip('"')})
            return _ok({"count": len(rows), "rows": rows}, len(r.text))
        except Exception as e:
            return _err(str(e))
        """新浪 K 线 (CN_MarketData.getKLineData, ma=no)

        走 CN_MarketData.getKLineData + ma=no, size=11202 (茅台 100 根日 K);
              CN_MarketDataService 返 Service not valid

        返回 day/open/high/low/close/volume

        scale: 5=5分钟, 15=15分钟, 30=30分钟, 60=60分钟, 240=日K, 1200=周K
        """
        try:
            r = self._std.get(
                "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData",
                params={"symbol": _symbol.sina(symbol), "scale": scale, "ma": "no", "datalen": datalen},
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            data = r.json()
            return _ok({
                "symbol": symbol, "scale": scale, "count": len(data), "rows": data,
            }, len(r.text))
        except Exception as e:
            return _err(str(e))

    # ===== 第7轮反爬: push2.eastmoney.com 沪股通资金 (curl_cffi 可调) =====
