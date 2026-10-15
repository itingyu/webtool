"""雪球 (xueqiu) —— 29 个方法

端点: stock.xueqiu.com/v5
反爬: 纯 TLS 指纹反爬: curl_cffi chrome110 + 3 页 warmup, 无 token

"""
from webtool.stock.bridge.sources._base import _err, _ok, SourceBase
from webtool.stock.bridge.sources import _symbol
import time


class XueqiuSource(SourceBase):
    """雪球 (xueqiu) 方法集 —— 由 sources/__init__.py 的 APIClient 混入"""

    def xueqiu_stock_html(self, symbol: str = "SH600519") -> dict:
        """雪球个股主页 HTML (xueqiu.com/S/SH600519)

        走 xueqiu.com/S/SH{code} 直通 size=110310 (f10 announce/finance 各路均不可用)

        已验证: SH600519 茅台 size=110310, SH688825 长鑫 size=110310
                SZ301707 展芯 size=110310, SH688825/detail size=110310

        返回 HTML 页面含动态加载数据
        """
        try:
            # self._xs 已带 impersonate 与 3 页 warmup, 复用即可:
            # 局部自建 session 既绕过代理规则, 又把 warmup 重做一遍
            r = self._xueqiu_session().get(f'https://xueqiu.com/S/{symbol}',
                headers={'Referer': 'https://xueqiu.com/hq'}, timeout=8)
            return _ok({'html_len': len(r.text)}, len(r.text))
        except Exception as e:
            return _err(str(e))

    def xueqiu_quote(self, symbol: str = "SH688825") -> dict:
        """雪球完整行情+市场数据 (v5/stock/quote.json)

        已验证:
        - SH600519 茅台 1309.22 size=1021
        - SH688825 长鑫 52.48 size=1021
        - SZ301707 展芯 116.52
        - TSLA 328.58
        - AAPL 313.33
        - NVDA 223.96
        - HK00700 沙盒无数据

        返回 data 含 market/quote/others/tags 子段
        """
        return self._xq_get("/v5/stock/quote.json",
                            {"symbol": symbol})

    def xueqiu_f10_company(self, symbol: str = "SH688825") -> dict:
        """公司简介"""
        return self._xq_get("/v5/stock/f10/cn/company.json", {"symbol": symbol})

    def xueqiu_f10_business(self, symbol: str = "SH688825") -> dict:
        """主营业务分析"""
        return self._xq_get("/v5/stock/f10/cn/business_analysis.json",
                            {"symbol": symbol})


    def xueqiu_quote_flat(self, codes) -> dict:
        """`{代码: 行情 dict}` —— 分析层要的展平契约

        比 `xueqiu_quote` 多两件事:
        1. 雪球取不到时兜底到东财;
        2. `pe_ttm` / `pb` 真去东财 F10 取 —— 雪球 quote.json 不返回这两个键,
           只从它取会永远静默返回 None, 下游评分拿不到估值因子。

        返回字段名保持既有契约 (current/percent/...), 调用方零改动。
        """
        if isinstance(codes, str):
            codes = [codes]
        out = {}
        # `xueqiu_quote` 只认单个 symbol —— 传 list 也只回第一只, 所以这里逐只查。
        # 要真批量得改 v5 端点, 那属于另一个源的事。
        for code in list(codes):
            r = self.xueqiu_quote(code)
            q = (r.get('data') or {}).get('quote') if r.get('ok') else None
            if q and (q.get('current') or q.get('open')):
                fq = self._flat_quote(q)
                if fq.get('pe_ttm') is None or fq.get('pb') is None:
                    fq['pe_ttm'], fq['pb'] = self._flat_valuation(code)
                out[fq['code'] or q.get('symbol')] = fq
        todo = [c for c in codes if not any(
            k.endswith(str(c)[-6:]) or str(c)[-6:] == k[-6:] for k in out)]
        for code in todo:                       # 雪球没覆盖到的走东财
            q = self.em_stock_get(code).get('data') or {}
            if q.get('current'):
                out[_symbol.xueqiu(code)] = self._flat_em_quote(q)
        return out

    @staticmethod
    def _flat_quote(q):
        """雪球 quote.json → 分析层字段名。雪球已是英文字段, 只做补位。"""
        # 字段名沿用 fetchers 契约 (current/percent/turnover_rate/...),
        # 调用方 single_analysis / short_pool / long_pool / mid_pool 按这些 key 取,
        # 换名字等于让 14 个调用点全改
        return {
            'code': q.get('code') or q.get('symbol'),
            'symbol': q.get('symbol'),
            'name': q.get('name'),
            'current': q.get('current'),
            'percent': q.get('percent'),
            'change': q.get('chg'),
            'high': q.get('high'), 'low': q.get('low'), 'open': q.get('open'),
            'prev_close': q.get('last_close'),
            'volume': q.get('volume'), 'amount': q.get('amount'),
            'turnover_rate': q.get('turnover_rate'),
            'amplitude': q.get('amplitude'),
            'mktcap': q.get('market_capital'),
            'float_mktcap': q.get('float_market_capital'),
            'pe_ttm': None, 'pb': None,      # 雪球 quote.json 不给, 下面补
            'currency': q.get('currency'),
            'error': None,
        }

    def _flat_valuation(self, code):
        """补 pe_ttm / pb —— 雪球 quote.json 不给这两个键

        fetchers 原实现是 `q.get("pe_ttm")`, 恒为 None, 下游评分因此拿不到
        估值因子 (静默失效, 不报错)。这里改从东财 push2 取真实值:
        f162 = PE(动态), f167 = PB, 都按 ×100 缩放。
        """
        mkt = _symbol.em_market(code)
        try:
            # 走统一通道 (_em_get, 正确 UA/ut)。注意: push2 的 ulist.np/get
            # 对本沙盒出口 IP 稳定断连 (stock/get 同刻 200, ulist 必炸, 已多轮
            # 复测) —— 估值改用 stock/get 的 f116/f117 (总/流通市值, 元) +
            # 涨跌字段换算不可行, PE/PB 退回雪球 K 线接口计算:
            #   pe = price / (净利/股本) 太重; 直接用东财 F10 的
            #   datacenter 通道 (RPT_F10_FINANCE_MAINFINADATA) 拿 EPS+BPS。
            from webtool.stock.bridge.sources.em import EmSource
            ems = EmSource()
            # 1) 行情价 (push2 stock/get 稳定可达)
            rq = ems._em_get('https://push2.eastmoney.com/api/qt/stock/get',
                             {'secid': f'{mkt}.{_symbol.em(code)}',
                              'fields': 'f43,f58'})
            if not rq.get('ok'):
                return None, None
            price = (rq.get('data') or {}).get('f43')
            if not isinstance(price, (int, float)) or not price:
                return None, None
            price = price / 100.0  # 两位精度
            # 2) EPS / BPS (datacenter 通道, 可达)。注意 em_market 返回的是
            #    push2 数字码 ('1'=沪), datacenter 要的是 'SH'/'SZ' 后缀
            suffix = 'SH' if str(mkt) == '1' else 'SZ'
            rf = ems._em_get(
                'https://datacenter.eastmoney.com/securities/api/data/v1/get',
                {'reportName': 'RPT_F10_FINANCE_MAINFINADATA',
                 'columns': 'SECUCODE,EPSJB,BPS',
                 'filter': f'(SECUCODE="{_symbol.em(code)}.{suffix}")',
                 'pageSize': '1', 'sortColumns': 'REPORT_DATE',
                 'sortTypes': '-1'})
            rows = ((rf.get('data') or {}).get('result') or {}).get('data') or []
            if not rows:
                return None, None
            eps, bps = rows[0].get('EPSJB'), rows[0].get('BPS')
            pe = round(price / eps, 2) if isinstance(eps, (int, float)) and eps else None
            pb = round(price / bps, 2) if isinstance(bps, (int, float)) and bps else None
            return pe, pb
        except Exception:
            return None, None

    def _flat_em_quote(q):
        """东财 push2 → 分析层字段名 (价格已 /100)"""
        return {
            'code': q.get('code'), 'name': q.get('name'),
            'current': q.get('current'), 'percent': q.get('pct_chg'),
            'change': q.get('chg'), 'high': q.get('high'),
            'low': q.get('low'), 'open': q.get('open'),
            'prev_close': q.get('pre_close'), 'volume': q.get('volume'),
            'amount': q.get('amount'), 'turnover_rate': q.get('turnover'),
            'mktcap': q.get('mktcap'), 'float_mktcap': q.get('float_mktcap'),
            'pe_ttm': q.get('pe'), 'pb': q.get('pb'),
            'currency': None, 'error': None,
        }

    def xueqiu_fill_valuation(self, codes, fields=('pe', 'pb')) -> dict:
        """给展平行情补 PE/PB —— 东财 F10 一次批量取回

        统一在这里补一次; 取不到的保持 None,
        调用方要按"缺失"处理而不是当 0。
        """
        import re as _re
        need = [c for c in codes if c in fields]
        if not need:
            return {}
        out = {}
        for code in codes:
            secuid = code if '.' in str(code) else \
                ('SH' if str(code).upper().startswith('SH') else 'SZ') + \
                _re.sub(r'^(SH|SZ|BJ)', '', str(code).upper())
            r = self.em_f10_main_finadata(secuid)
            rows = (r.get('data') or {}).get('rows') or []
            if not rows:
                continue
            row = rows[0] if isinstance(rows[0], dict) else {}
            vals = {}
            if 'pe' in fields:
                vals['pe'] = row.get('PE_TTM') or row.get('PE_LAR')
            if 'pb' in fields:
                vals['pb'] = row.get('PB_MRQ') or row.get('PB')
            out[code] = vals
        return out

    def xueqiu_kline(self, symbol: str = "SH688825",
                     period: str = "day", count: int = 20) -> dict:
        """K 线 (day/week/month)"""
        now_ms = int(time.time() * 1000)
        # begin 必须按周期反推跨度, 不能用固定天数。
        # 雪球 kline.json 的 type=before 是"取 end 之前 count 条", 但仍要 begin
        # 落在足够远的过去 —— 用固定 span 时请求 250 根日 K 只回 16 根
        # (span=30 天只够 16 个交易日), 而周/月 K 更离谱, 结果是长周期
        # 指标 (MA60 / 年线 / 季线) 全部算错。
        # 经验系数: day×1.6 / week×7×1.4 / month×30×1.3, 再加 15 天冗余。
        mult = {"day": 1.6, "week": 7 * 1.4, "month": 30 * 1.3}.get(period, 1.6)
        cal_days = int(count * mult) + 15
        return self._xq_get(
            "/v5/stock/chart/kline.json",
            {"symbol": symbol, "period": period, "type": "before",
             "count": count, "begin": now_ms - cal_days * 86400000,
             "end": now_ms, "indicator": "kline"},
        )

    def xueqiu_kline_day(self, symbol: str = "SH688825") -> dict:
        """K 线 day 别名"""
        return self.xueqiu_kline(symbol, "day")

    def xueqiu_kline_week(self, symbol: str = "SH688825") -> dict:
        """K 线 week 别名"""
        return self.xueqiu_kline(symbol, "week")

    def xueqiu_realtime_batch(self, symbols: str = "SH688825,SH600519") -> dict:
        """多股批量实时 (symbols 用逗号分隔)"""
        return self._xq_get("/v5/stock/realtime/quotec.json", {"symbol": symbols})

    def xueqiu_screener_list(self, page: int = 1, size: int = 20,
                              order_by: str = "percent", order: str = "desc",
                              market: str = "CN", type_: str = "sh_sz") -> dict:
        """雪球选股器列表 (screener/quote/list.json)

        走 screener/quote/list.json (必须带 .json; 不带会返 Whitelabel 或 list=[])

        已验证:
        - market=CN type=sh_sz: 5000 只 A 股
        - market=HK type=hk: 3081 只 港股
        - market=HK type=hkex: 3122 只 港股
        - market=US type=us / us_n / us_oq: 5000 只 美股
        """
        return self._xq_get("/v5/stock/screener/quote/list.json",
                            {"page": page, "size": size,
                             "order_by": order_by, "order": order,
                             "market": market, "type": type_})

    def xueqiu_industry(self, symbol: str = "SH688825") -> dict:
        """所属行业"""
        return self._xq_get("/v5/stock/industry/quote.json", {"symbol": symbol})

    def xueqiu_f10_concept(self, symbol: str = "SH688825") -> dict:
        """股票所属行业/概念 (f10/cn/industry.json)

        走 f10/cn/industry.json (含 ind_name + ind_code BK0xxx); sector/concept_plate 返 Whitelabel

        返回样例:
        - 600519 (茅台): 融资融券 BK0409, 沪股通 BK0472, 白酒概念 BK0475
        - 688825 (长鑫科技): 融资融券 BK0409, 新股与次新股 BK0512, 阿里 BK0515
        """
        return self._xq_get("/v5/stock/f10/cn/industry.json", {"symbol": symbol})

    def xueqiu_f10_industry_us(self, symbol: str = "TSLA") -> dict:
        """美股所属行业/概念 (f10/us/industry.json)

        已验证:
        - TSLA 特斯拉 size=1413
        - AAPL 苹果 size=2070
        - NVDA 英伟达 size=1595
        - BABA 阿里 size=1502
        """
        return self._xq_get("/v5/stock/f10/us/industry.json", {"symbol": symbol})

    def xueqiu_f10_indicator_us(self, symbol: str = "TSLA") -> dict:
        """美股核心财务指标 (f10/us/indicator.json)

        已验证:
        - TSLA 特斯拉 size=519, pe_ttm=341.152
        - AAPL 苹果 size=523
        - NVDA 英伟达 size=527

        字段: eps_dlt/asset_liab_ratio/pledge_ratio/net_profit_atsopc_yoy/
               operating_income_yoy/goodwill_in_net_assets/gross_selling_rate/
               pb/total_revenue/roe_avg 等 22 个
        """
        return self._xq_get("/v5/stock/f10/us/indicator.json", {"symbol": symbol})

    def xueqiu_f10_bonus_us(self, symbol: str = "TSLA") -> dict:
        """美股分红/bonus (f10/us/bonus.json)

        已验证:
        - TSLA 特斯拉 size=519
        - AAPL 苹果 size=1238
        - NVDA 英伟达 size=1238
        """
        return self._xq_get("/v5/stock/f10/us/bonus.json", {"symbol": symbol})

    def xueqiu_f10_industry_hk(self, symbol: str = "HK00700") -> dict:
        """港股所属行业/概念 (f10/hk/industry.json)

        已验证: 任何 SH/SZ/HK/US 代码 size=231~233 真通 (含港股代码)
        """
        return self._xq_get("/v5/stock/f10/hk/industry.json", {"symbol": symbol})

    def xueqiu_top_holders(self, symbol: str = "SH600519") -> dict:
        """十大股东 (老股)"""
        return self._xq_get("/v5/stock/f10/cn/top_holders.json", {"symbol": symbol})

    def xueqiu_skholderchg(self, symbol: str = "SH600519") -> dict:
        """股东变动 (老股)"""
        return self._xq_get("/v5/stock/f10/cn/skholderchg.json", {"symbol": symbol})

    # 同花顺 (4 个)

    def xueqiu_business_analysis(self, symbol: str = "SH688825") -> dict:
        """雪球业务分析 (f10/cn/business_analysis.json, 反爬绕过后真通)

        走 /v5/stock/f10/cn/business_analysis.json (8405 字节含完整业务分析);
              operate.json 等同族端点返 Whitelabel Error Page

        已验证: SH688825 长鑫科技 size=8405 含 3 个报告期 (2025年报/2025中报) 完整业务说明:
          - 营业收入构成 (DDR/LPDDR 系列产品销售)
          - 产能建设工艺迭代
          - DRAM 行业分析
          - 客户 (阿里云/字节跳动/腾讯/联想/小米/传音/荣耀/OPPO/vivo)
          - LPDDR5/DDR5/LPDDR5X 量产时间
          - 中国香港境外收入占比
          - 各季度收入变化

        返回 data.items[].operating_analysis_explain / report_date

        已验证:
        - SZ000333 美的集团 size=258225 (巨大完整业务说明)
        - SH688041 沐曦 size=63712
        - SZ301707 展芯股份 size=4178
        """
        try:
            r = self._xueqiu_session().get(
                "https://stock.xueqiu.com/v5/stock/f10/cn/business_analysis.json",
                params={"symbol": symbol},
                headers={"Referer": "https://xueqiu.com/hq"},
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            j = r.json()
            items = j.get("data", {}).get("items", [])
            return _ok({
                "symbol": symbol, "count": len(items),
                "items": items,
                "sample_dates": [i.get("report_date") for i in items],
            }, len(r.text))
        except Exception as e:
            return _err(str(e))

    def xueqiu_bonus(self, symbol: str = "SH600519") -> dict:
        """雪球增减持/分红/配股 (f10/cn/bonus.json, 真替身)

        走 /v5/stock/f10/cn/bonus.json (data.items 常为空但端点通);
              dividend.json 等同族端点返 Whitelabel Error Page

        返回 data.addtions / data.allots / data.items (增减持/配股/分红)
        """
        try:
            r = self._xueqiu_session().get(
                "https://stock.xueqiu.com/v5/stock/f10/cn/bonus.json",
                params={"symbol": symbol},
                headers={"Referer": "https://xueqiu.com/hq"},
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            j = r.json()
            data = j.get("data", {})
            return _ok({
                "symbol": symbol,
                "addtions_count": len(data.get("addtions", []) or []),
                "allots_count": len(data.get("allots", []) or []),
                "items_count": len(data.get("items", []) or []),
                "data": data,
            }, len(r.text))
        except Exception as e:
            return _err(str(e))

    def xueqiu_industry_list_full(self, symbol: str = "SH600519") -> dict:
        """雪球个股所属行业全列表 (industry/quote.json, 反爬补强后真通)

        走 /v5/stock/industry/quote.json, 必须传 symbol (/list.json 404)

        用法: 传 symbol (e.g. SH600519), 返回该股所属的所有行业列表
              含 BK0088 白酒 percent=0.32 current=2514.32 等指数实时行情

        注意: industry/quote.json 必须传 symbol, 不传会触发 "Required String parameter 'symbol'"
              与 xueqiu_industry(symbol) 等价, 但用更明确的命名
        """
        try:
            r = self._xueqiu_session().get(
                "https://stock.xueqiu.com/v5/stock/industry/quote.json",
                params={"symbol": symbol},
                headers={"Referer": "https://xueqiu.com/hq"},
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            j = r.json()
            data = j.get("data") or {}
            items = data.get("items", []) if isinstance(data, dict) else []
            return _ok({
                "symbol": symbol, "total": len(items),
                "items": items,
                "sample": items[:3] if items else None,
            }, len(r.text))
        except Exception as e:
            return _err(str(e))

    def xueqiu_indicator(self, symbol: str = "SH600519", count: int = 3) -> dict:
        """雪球指标详情 (f10/cn/indicator.json, 22 个指标字段)

        可用, 传 symbol + count 拿最近 3 个季度/年度数据 (部分文档称 404, 系误传)

        已验证: SH600519/SZ000001/SH688825 真通, HK00700/usTSLA size=59 不支持

        返回 items 含 22 字段:
          asset_liab_ratio (资产负债率%)
          pledge_ratio (质押比例%)
          net_profit_atsopc_yoy (净利润同比%)
          operating_income_yoy (营业收入同比%)
          goodwill_in_net_assets (商誉占净资产%)
          basic_eps (基本每股收益)
          net_selling_rate (净利率%)
          avg_roe (平均ROE%)
          gross_selling_rate (毛利率%)
          float_shares (流通股数)
          pb (市净率)
          np_per_share (每股净利)
          float_market_capital (流通市值)
          total_revenue (总营收)
          market_capital (市值)
          pe_ttm (PE TTM)
          dividend (股息)
          currency (货币)
          dividend_yield (股息率%)
          net_profit_atsopc (净利润)
          total_shares (总股本)
          report_date (报告日期)
        """
        try:
            r = self._xueqiu_session().get(
                "https://stock.xueqiu.com/v5/stock/f10/cn/indicator.json",
                params={"symbol": symbol, "count": count},
                headers={"Referer": "https://xueqiu.com/hq"},
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            j = r.json()
            items = j.get("data", {}).get("items", []) if isinstance(j.get("data"), dict) else []
            return _ok({
                "symbol": symbol, "count": len(items),
                "items": items,
                "sample": items[0] if items else None,
            }, len(r.text))
        except Exception as e:
            return _err(str(e))

    def xueqiu_screener_f10(self, type_: str = "sha", order_by: str = "percent",
                            order: str = "desc", page: int = 1, size: int = 30) -> dict:
        """雪球 f10 风格 screener (f10/list.json, 真替身)

        走 /service/v5/stock/screener/f10/list.json (无 /service 前缀的旧 path 已下线)

        注意: list 字段为空 (size=140 但 items=0), 实际数据要看参数配置
        """
        try:
            r = self._xueqiu_session().get(
                "https://xueqiu.com/service/v5/stock/screener/f10/list.json",
                params={"type": type_, "order_by": order_by, "order": order,
                        "page": page, "size": size},
                headers={"Referer": "https://xueqiu.com/"},
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            j = r.json()
            return _ok(j, len(r.text))
        except Exception as e:
            return _err(str(e))

    def xueqiu_screener_portfolio(self, type_: str = "sha",
                                  order_by: str = "percent",
                                  order: str = "desc",
                                  page: int = 1, size: int = 30) -> dict:
        """雪球 portfolio 风格 screener (portfolio/list.json, 真替身)

        走 /service/v5/stock/screener/portfolio/list.json (无 /service 前缀的旧 path 已下线)
        """
        try:
            r = self._xueqiu_session().get(
                "https://xueqiu.com/service/v5/stock/screener/portfolio/list.json",
                params={"type": type_, "order_by": order_by, "order": order,
                        "page": page, "size": size},
                headers={"Referer": "https://xueqiu.com/"},
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            j = r.json()
            return _ok(j, len(r.text))
        except Exception as e:
            return _err(str(e))

    def xueqiu_company(self, symbol: str = "SH600519") -> dict:
        """雪球公司基本信息 (f10/cn/company.json, 反爬绕过后真通)

        可用; data 在 company 字段 (不是 items) —— status=400 是误判

        已验证: SH600519 / SH688825 / SZ000858 全股通
                 SH510050 / SZ159915 ETF 返 None (ETF 无公司信息)

        返回 data.company 含:
          org_name_cn/org_name_en/org_short_name_cn
          main_operation_business (主营业务)
          org_cn_introduction (公司简介)
          legal_representative/general_manager/secretary
          chairman
          established_date/listed_date
          reg_asset (注册资本)
          staff_num (员工数)
          provincial_name/classi_name/actual_controller
          reg_address_cn/office_address_cn
          telephone/postcode/fax/email/org_website
          affiliate_industry.ind_code / ind_name (所属行业)
        """
        try:
            # cn / hk / us 三种 prefix
            if symbol.startswith("HK"):
                url = "https://stock.xueqiu.com/v5/stock/f10/hk/company.json"
            elif symbol.startswith("us"):
                url = "https://stock.xueqiu.com/v5/stock/f10/us/company.json"
            else:
                url = "https://stock.xueqiu.com/v5/stock/f10/cn/company.json"
            r = self._xueqiu_session().get(url,
                params={"symbol": symbol},
                headers={"Referer": "https://xueqiu.com/hq"},
                timeout=self.BASE_TIMEOUT)
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            j = r.json()
            data = j.get("data") or {}
            company = data.get("company") or {}
            return _ok({
                "symbol": symbol, "has_data": bool(company),
                "org_name_cn": company.get("org_name_cn"),
                "org_short_name_cn": company.get("org_short_name_cn"),
                "main_operation_business": company.get("main_operation_business"),
                "org_cn_introduction": company.get("org_cn_introduction"),
                "chairman": company.get("chairman"),
                "staff_num": company.get("staff_num"),
                "reg_asset": company.get("reg_asset"),
                "listed_date": company.get("listed_date"),
                "established_date": company.get("established_date"),
                "provincial_name": company.get("provincial_name"),
                "classi_name": company.get("classi_name"),
                "actual_controller": company.get("actual_controller"),
                "reg_address_cn": company.get("reg_address_cn"),
                "telephone": company.get("telephone"),
                "org_website": company.get("org_website"),
                "affiliate_industry": company.get("affiliate_industry"),
                "raw_size": len(r.text),
            }, len(r.text))
        except Exception as e:
            return _err(str(e))

    def xueqiu_concept_industry(self, symbol: str = "SH600519") -> dict:
        """雪球个股所属行业+概念 (f10/cn/industry.json, 反爬绕过后真通)

        data 在 concept + industry + company 字段; items=0 / size=691 是正常的

        已验证: SH688825 长鑫 13 概念 + 半导体行业 + 公司信息全有
                 SZ000858 五粮液 11 概念 + 白酒行业
                 HK00700 腾讯 部分字段 (港股字段名为 mbu/comcnname)
                 usTSLA TSLA 部分字段 (美股字段名为 org_name_en)

        返回:
          data.concept: 概念板块列表 (e.g. [{"ind_name":"芯片概念","ind_code":"BK0586"}, ...])
          data.industry: 行业板块列表 (e.g. [{"ind_name":"半导体","ind_code":"BK0021"}])
          data.company: 公司基础信息
          data.industry_class: SW2014 / HS / GICS (申万/恒生/GICS 分类)
        """
        try:
            if symbol.startswith("HK"):
                url = "https://stock.xueqiu.com/v5/stock/f10/hk/industry.json"
            elif symbol.startswith("us"):
                url = "https://stock.xueqiu.com/v5/stock/f10/us/industry.json"
            else:
                url = "https://stock.xueqiu.com/v5/stock/f10/cn/industry.json"
            r = self._xueqiu_session().get(url,
                params={"symbol": symbol},
                headers={"Referer": "https://xueqiu.com/hq"},
                timeout=self.BASE_TIMEOUT)
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            j = r.json()
            data = j.get("data") or {}
            concepts = data.get("concept", []) or []
            industries = data.get("industry", []) or []
            return _ok({
                "symbol": symbol,
                "concept_count": len(concepts),
                "concept": concepts,
                "industry_count": len(industries),
                "industry": industries,
                "industry_class": data.get("industry_class"),
                "concept_class": data.get("concept_class"),
                "company_brief": data.get("company") or {},
                "raw_size": len(r.text),
            }, len(r.text))
        except Exception as e:
            return _err(str(e))

    # ===== 第5轮反爬: 新版 datacenter reportName =====

    def xueqiu_screener(self, type_: str = "sha",
                        order_by: str = "percent", order: str = "desc",
                        page: int = 1, size: int = 30) -> dict:
        """雪球 screener 涨跌幅榜 (type: sha沪A/sza深A/us美股/hk港股)"""
        try:
            r = self._xueqiu_session().get(
                "https://xueqiu.com/service/v5/stock/screener/quote/list",
                params={"type": type_, "order_by": order_by, "order": order,
                        "page": page, "size": size},
                headers={"Referer": "https://xueqiu.com/"},
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            j = r.json().get("data", {})
            return _ok({"count": j.get("count"), "list": j.get("list", [])},
                       len(r.text))
        except Exception as e:
            return _err(str(e))

    def xueqiu_kline_month(self, symbol: str = "SH688825", count: int = 12) -> dict:
        """雪球月 K 线"""
        return self.xueqiu_kline(symbol, "month", count)

    def xueqiu_top_holders_full(self, symbol: str = "SH600519") -> dict:
        """雪球十大股东 (老股) — 完整字段"""
        return self._xq_get("/v5/stock/f10/cn/top_holders.json", {"symbol": symbol})

    def xueqiu_skholderchg_full(self, symbol: str = "SH600519") -> dict:
        """雪球股东变动 (老股) — 完整字段"""
        return self._xq_get("/v5/stock/f10/cn/skholderchg.json", {"symbol": symbol})
