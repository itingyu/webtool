"""同花顺 (10jqka) —— 35 个方法

端点: q.10jqka.com.cn / d.10jqka.com.cn
反爬: chameleon 反爬, 需 v cookie (qjs 跑 akshare ths.js 生成) + curl_cffi chrome120 指纹

"""
from webtool.stock.bridge.sources._base import _err, _ok, SourceBase
from curl_cffi import requests as cffi
from webtool.stock.bridge.sources._base import _ths_v_token
from webtool.stock.bridge.sources import _routing

# 同花顺会话统一走 RoutedCffiSession (带 netx 代理路由)
_ths_factory = lambda: _routing.RoutedCffiSession(  # noqa: E731
    impersonate='chrome120', override=None)


def _ths_session(factory):
    """给同花顺会话补 v token 与必备头

    `factory` 由调用方给 —— 传 `_routing.RoutedCffiSession` 才能带上代理路由,
    局部自建 cffi.Session 会绕过 netx, 于是配置里的代理对它无效。
    """
    s = factory()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": "http://q.10jqka.com.cn/",
    })
    try:
        s.get("http://q.10jqka.com.cn/", timeout=8)
    except Exception:                                # noqa: BLE001
        pass
    try:
        s.cookies.set("v", _ths_v_token())
    except Exception:                                # noqa: BLE001
        pass
    return s
import json
import re


class ThsSource(SourceBase):
    """同花顺 (10jqka) 方法集 —— 由 sources/__init__.py 的 APIClient 混入"""

    def ths_session(self) -> "requests.Session":  # noqa: F821 (仅类型注解)
        if self._ths is None:
            self._ths = _ths_session(_ths_factory)
        return self._ths

    def _ths_data(self, path: str, host: str = "data.10jqka.com.cn") -> dict:
        """同花顺子域 (反爬绕过: 不在 nginx 403 IP ban 名单)

        host: data.10jqka.com.cn / stock.10jqka.com.cn / news.10jqka.com.cn /
              futures.10jqka.com.cn 等
        """
        try:
            r = self._std.get(f"http://{host}{path}",
                headers={"Referer": "http://q.10jqka.com.cn/"},
                timeout=self.BASE_TIMEOUT)
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            html = r.content.decode("gbk", errors="replace")
            return _ok({"html_len": len(html), "html": html}, len(html))
        except Exception as e:
            return _err(str(e))

    def _ths_data_parse_table(self, path: str, host: str = "data.10jqka.com.cn") -> dict:
        """同花顺子域表格解析 (取第 1 个真实数据 table)"""
        r = self._ths_data(path, host=host)
        if not r["ok"]:
            return r
        html = r["data"]["html"]
        # 找第 2 个 table（避开 header table），找数据 table
        tables = re.findall(r'<table[^>]*>(.*?)</table>', html, re.DOTALL)
        if not tables:
            return _err("no table")
        # 通常第 2-3 个 table 才是数据
        data_table = tables[-1] if len(tables) > 1 else tables[0]
        # 提取 header
        headers = re.findall(r'<th[^>]*>(.*?)</th>', data_table, re.DOTALL)
        headers = [re.sub(r'<[^>]+>', '', h).strip() for h in headers]
        # 提取 rows
        rows = re.findall(r'<tr[^>]*>(.*?)</tr>', data_table, re.DOTALL)
        parsed = []
        for row in rows:
            cols = re.findall(r'<td[^>]*>(.*?)</td>', row, re.DOTALL)
            if cols:
                # 去掉 HTML 标签
                cols_clean = []
                for c in cols:
                    txt = re.sub(r'<[^>]+>', '', c)
                    txt = re.sub(r'\s+', ' ', txt).strip()
                    cols_clean.append(txt)
                if cols_clean:
                    parsed.append(cols_clean)
        return _ok({
            "headers": headers,
            "rows": parsed,
            "row_count": len(parsed),
            "html_len": r["data"]["html_len"],
        }, r["data"]["html_len"])

    def _ths_stockpage(self, code: str, sub: str = "") -> dict:
        """stockpage.10jqka.com.cn 个股详情页 (反爬绕过)"""
        path = f"/{code}{('/' + sub) if sub else ''}"
        try:
            r = self._std.get(f"http://stockpage.10jqka.com.cn{path}",
                headers={"Referer": "http://q.10jqka.com.cn/"},
                timeout=self.BASE_TIMEOUT)
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            html = r.content.decode("gbk", errors="replace")
            return _ok({"html_len": len(html), "html": html}, len(html))
        except Exception as e:
            return _err(str(e))

    def ths_industry_list(self, page: int = 1) -> dict:
        """行业板块列表 (返回 dict: {板块名: 涨跌幅%})"""
        try:
            r = self.ths_session().get(
                f"http://q.10jqka.com.cn/thshy/index/field/199112/order/desc/"
                f"page/{page}/ajax/1/free/1/",
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200 or not r.text:
                return _err(f"status={r.status_code}, size={len(r.text)}", r.status_code)
            # GBK 解码 + 正则提取
            html = r.content.decode("gbk", errors="replace")
            # 板块名形如 >半导体</a>
            names = re.findall(r'>([^<>]{2,8})</a>', html)
            return _ok({"names": names[:30]}, len(r.text))
        except Exception as e:
            return _err(str(e))

    def ths_concept_list(self, page: int = 1) -> dict:
        """概念板块列表"""
        try:
            r = self.ths_session().get(
                f"http://q.10jqka.com.cn/gn/index/field/addtime/order/desc/"
                f"page/{page}/ajax/1/free/1/",
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200 or not r.text:
                return _err(f"status={r.status_code}", r.status_code)
            html = r.content.decode("gbk", errors="replace")
            names = re.findall(r'>([^<>]{2,8})</a>', html)
            return _ok({"names": names[:30]}, len(r.text))
        except Exception as e:
            return _err(str(e))

    def ths_industry_detail(self, code: str = "881270") -> dict:
        """行业板块详情 (成分股)"""
        try:
            r = self.ths_session().get(
                f"http://q.10jqka.com.cn/thshy/detail/code/{code}/",
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200 or not r.text:
                return _err(f"status={r.status_code}", r.status_code)
            html = r.content.decode("gbk", errors="replace")
            # 成分股代码 (6 位数字) + 名称
            symbols = re.findall(r'\b(\d{6})\b', html)
            return _ok({"code": code, "html_len": len(html), "symbols_sample": symbols[:20]},
                       len(r.text))
        except Exception as e:
            return _err(str(e))

    def ths_bk_kline(self, code: str = "881270", year: int = 2026) -> dict:
        """板块 K 线 (JSONP)"""
        try:
            r = self._std.get(
                f"https://d.10jqka.com.cn/v4/line/bk_{code}/01/{year}.js",
                headers={"Referer": "http://q.10jqka.com.cn/"},
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200 or not r.text:
                return _err(f"status={r.status_code}", r.status_code)
            # quotebridge_v4_line_bk_XXX_01_YYYY({"data":"日期,O,H,L,C,vol,amt;..."})
            m = re.search(r'quotebridge\w*\((.*)\)', r.text)
            if not m:
                return _err("JSONP 格式不匹配", 200)
            payload = json.loads(m.group(1))
            rows = []
            for line in payload.get("data", "").split(";"):
                parts = line.split(",")
                if len(parts) >= 7 and parts[0]:
                    rows.append({
                        "date": parts[0], "open": float(parts[1]),
                        "high": float(parts[2]), "low": float(parts[3]),
                        "close": float(parts[4]), "volume": int(parts[5] or 0),
                        "amount": float(parts[6] or 0),
                    })
            return _ok(rows, len(r.text))
        except Exception as e:
            return _err(str(e))

    # ------------------------------------------------------------------
    # 东财 (5 个)
    # ------------------------------------------------------------------

    def ths_rank_cxfl(self) -> dict:
        """同花顺持续放量排行 (data.10jqka.com.cn/rank/cxfl/)

        /thshy/getBsMarketDataAjax/* 已成 403 (nginx IP ban);
        走 data 子域解析 HTML 表格, 出真实排行数据

        返回 headers + rows (~50 行), 含 stockcode/股票简称/涨跌幅/成交量/放量天数
        """
        return self._ths_data_parse_table("/rank/cxfl/")

    def ths_market_rzrq(self) -> dict:
        """同花顺融资融券 (data.10jqka.com.cn/market/rzrq/)

        同花顺各 endpoint 均 403; 走 data 子域

        返回 headers + rows, 含交易日期/融资余额/融券余量/上海/深圳/北京/合计
        """
        return self._ths_data_parse_table("/market/rzrq/")

    def ths_funds_ggzjl(self) -> dict:
        """同花顺个股资金一览 (data.10jqka.com.cn/funds/ggzjl/)

        返回 headers + rows, 含股票代码/简称/最新价/涨跌幅/换手率/资金流入流出/净额
        """
        return self._ths_data_parse_table("/funds/ggzjl/")

    def ths_funds_hyzjl(self) -> dict:
        """同花顺行业资金一览 (data.10jqka.com.cn/funds/hyzjl/)

        返回 headers + rows, 含行业/涨跌幅/流入资金/流出资金/净额
        """
        return self._ths_data_parse_table("/funds/hyzjl/")

    def ths_market_dzjy(self) -> dict:
        """同花顺大宗交易 (data.10jqka.com.cn/market/dzjy/)

        返回 headers + rows
        """
        return self._ths_data_parse_table("/market/dzjy/")

    def ths_ipo_xgpt(self) -> dict:
        """同花顺新股配售 (data.10jqka.com.cn/ipo/xgpt/)

        返回 IPO 日历数据
        """
        return self._ths_data_parse_table("/ipo/xgpt/")

    def ths_ipo_xgyp(self) -> dict:
        """同花顺新股申购 (data.10jqka.com.cn/ipo/xgyp/)

        返回 ipo 申购日历数据
        """
        return self._ths_data_parse_table("/ipo/xgyp/")

    def ths_market_ggsyl(self) -> dict:
        """同花顺个股速览 (data.10jqka.com.cn/market/ggsyl/)

        返回 个股市盈率 排行
        """
        return self._ths_data_parse_table("/market/ggsyl/")

    def ths_market_overview(self) -> dict:
        """同花顺市场总览 (data.10jqka.com.cn/market/)

        返回 市场首页数据 (size=769767)
        """
        return self._ths_data("/market/")

    # stockpage.10jqka.com.cn 个股详情页

    def ths_stockpage_main(self, code: str = "600519") -> dict:
        """同花顺个股主页 (stockpage.10jqka.com.cn/{code})"""
        return self._ths_stockpage(code)

    def ths_stockpage_news(self, code: str = "600519") -> dict:
        """同花顺个股新闻 (stockpage.10jqka.com.cn/{code}/news) - size=101015"""
        return self._ths_stockpage(code, "news")

    def ths_stockpage_finance(self, code: str = "600519") -> dict:
        """同花顺个股财务 (stockpage.10jqka.com.cn/{code}/finance) - size=17300"""
        return self._ths_stockpage(code, "finance")

    def ths_stockpage_holder(self, code: str = "600519") -> dict:
        """同花顺个股股东 (stockpage.10jqka.com.cn/{code}/holder) - size=18283"""
        return self._ths_stockpage(code, "holder")

    def ths_stockpage_event(self, code: str = "600519") -> dict:
        """同花顺个股事件 (stockpage.10jqka.com.cn/{code}/event) - size=17441"""
        return self._ths_stockpage(code, "event")

    def ths_stockpage_f10(self, code: str = "600519") -> dict:
        """同花顺个股 F10 (stockpage.10jqka.com.cn/{code}/f10) - size=7362"""
        return self._ths_stockpage(code, "f10")

    # 同花顺 stock.10jqka.com.cn 子域 (反爬绕过)

    def ths_stock_zaopan(self) -> dict:
        """同花顺早盘 (stock.10jqka.com.cn/zaopan/) - size=26123"""
        return self._ths_data("/zaopan/", host="stock.10jqka.com.cn")

    def ths_stock_fupan(self) -> dict:
        """同花顺复盘 (stock.10jqka.com.cn/fupan/) - size=49980"""
        return self._ths_data("/fupan/", host="stock.10jqka.com.cn")

    def ths_stock_newstock(self) -> dict:
        """同花顺新股 (stock.10jqka.com.cn/newstock/) - size=391737"""
        return self._ths_data("/newstock/", host="stock.10jqka.com.cn")

    def ths_stock_fincalendar(self) -> dict:
        """同花顺财报日历 (stock.10jqka.com.cn/fincalendar.shtml) - size=10530"""
        return self._ths_data("/fincalendar.shtml", host="stock.10jqka.com.cn")

    def ths_stock_market(self) -> dict:
        """同花顺市场首页 (stock.10jqka.com.cn/market.shtml) - size=111303"""
        return self._ths_data("/market.shtml", host="stock.10jqka.com.cn")

    def ths_stock_chuangye(self) -> dict:
        """同花顺创业板 (stock.10jqka.com.cn/chuangye/) - size=62021"""
        return self._ths_data("/chuangye/", host="stock.10jqka.com.cn")

    # 同花顺 news.10jqka.com.cn 子域 (反爬绕过)

    def ths_news_yaowen(self) -> dict:
        """同花顺财经要闻 (news.10jqka.com.cn/yaowen/) - size=63658"""
        return self._ths_data("/yaowen/", host="news.10jqka.com.cn")

    def ths_news_cjzx(self) -> dict:
        """同花顺财经资讯 (news.10jqka.com.cn/cjzx_list/) - size=63824"""
        return self._ths_data("/cjzx_list/", host="news.10jqka.com.cn")

    def ths_news_guojicj(self) -> dict:
        """同花顺国际财经 (news.10jqka.com.cn/guojicj_list/) - size=63975"""
        return self._ths_data("/guojicj_list/", host="news.10jqka.com.cn")

    def ths_news_tzz(self) -> dict:
        """同花顺投资者网 (news.10jqka.com.cn/tzz/) - size=13289"""
        return self._ths_data("/tzz/", host="news.10jqka.com.cn")

    def ths_news_hudong(self) -> dict:
        """同花顺互动 (news.10jqka.com.cn/hudong/) - size=1269879"""
        return self._ths_data("/hudong/", host="news.10jqka.com.cn")

    # 同花顺 futures.10jqka.com.cn 期货子域

    def ths_futures_index(self) -> dict:
        """同花顺期货首页 (futures.10jqka.com.cn/) - size=125009"""
        return self._ths_data("/", host="futures.10jqka.com.cn")

    # ------------------------------------------------------------------
    # 反爬抢救接口 (api_docs_rescued.md)
    # ------------------------------------------------------------------
    # 2026-08-09 探活发现，同一数据源内可通过反爬补强 (新path / 反爬 / 参数) 救活的接口
    # 详见 api_docs_rescued.md

    def ths_industry_by_field(self, field: str = "199112", page: int = 1) -> dict:
        """同花顺行业板块 - 自定义排序字段

        注意: 仅 199112 (涨跌幅) 有数据，其他字段 (199113成交额/199114换手率/199115涨速) 返回空表头
        """
        try:
            r = self.ths_session().get(
                f"http://q.10jqka.com.cn/thshy/index/field/{field}/order/desc/"
                f"page/{page}/ajax/1/free/1/",
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200 or not r.text:
                return _err(f"status={r.status_code}", r.status_code)
            html = r.content.decode("gbk", errors="replace")
            # 过滤分页链接
            names = [n for n in re.findall(r'>([^<>]{2,8})</a>', html)
                     if n not in ('下一页', '尾页', '首页', '上一页')]
            return _ok({"field": field, "names": names[:30], "size": len(r.text)},
                       len(r.text))
        except Exception as e:
            return _err(str(e))

    def ths_concept_by_addtime(self, page: int = 1) -> dict:
        """同花顺概念板块 - 按添加时间排序 (addtime, 唯一真通的 field)"""
        try:
            r = self.ths_session().get(
                f"http://q.10jqka.com.cn/gn/index/field/addtime/order/desc/"
                f"page/{page}/ajax/1/free/1/",
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200 or not r.text:
                return _err(f"status={r.status_code}", r.status_code)
            html = r.content.decode("gbk", errors="replace")
            names = re.findall(r'>([^<>]{2,8})</a>', html)
            names = [n for n in names if n not in ('下一页', '尾页', '首页', '上一页')]
            return _ok({"names": names[:30]}, len(r.text))
        except Exception as e:
            return _err(str(e))

    def ths_bk_kline_v2(self, code: str = "881270", year: int = 2026) -> dict:
        """同花顺板块 K 线 v2 版本 (与 v4 数据相同)"""
        try:
            r = self._std.get(
                f"https://d.10jqka.com.cn/v2/line/bk_{code}/01/{year}.js",
                headers={"Referer": "http://q.10jqka.com.cn/"},
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200 or not r.text:
                return _err(f"status={r.status_code}", r.status_code)
            m = re.search(r'quotebridge\w*\((.*)\)', r.text)
            if not m:
                return _err("JSONP 格式不匹配", 200)
            payload = json.loads(m.group(1))
            rows = []
            for line in payload.get("data", "").split(";"):
                parts = line.split(",")
                if len(parts) >= 7 and parts[0]:
                    rows.append({
                        "date": parts[0], "open": float(parts[1]),
                        "high": float(parts[2]), "low": float(parts[3]),
                        "close": float(parts[4]), "volume": int(parts[5] or 0),
                        "amount": float(parts[6] or 0),
                    })
            return _ok(rows, len(r.text))
        except Exception as e:
            return _err(str(e))
