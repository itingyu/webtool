"""东财行情族: 实时行情 / K 线 (A 股/美股) / 涨停池 / 沪深港通资金"""
"""东方财富 (eastmoney) —— 32 个方法

端点: push2 / push2his / emweb / datacenter-web
反爬: push2 需固定 ut token; datacenter 需 source=WEB+client=PC; 公告一路走 curl 子进程

"""
from webtool.stock.bridge.sources._base import _err, _ok





class EmQuoteMixin:
    """端点族 mixin; 只依赖 self._em_* (由 EmCoreMixin 提供)"""

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

    def em_zt_pool(self, date: str = "") -> dict:
        """涨停池 (push2ex getTopicZTPool) —— 含连板/首封时间/炸板次数/封单/行业

        `date` 认 `YYYYMMDD` / `YYYY-MM-DD`，空则取接口默认。

        **`date` 生效, `qdate` 不能当数据日** —— 逐日行数与真实交易日对上
        (非交易日返回 0 行), 而 `qdate` 恒为"最近交易日":

        | 请求 date | 行数 | 响应 qdate |
        |---|---|---|
        | 20261008(四) | 43 | 20261014 |
        | 20261009(五) | 69 | 20261014 |
        | 20261010/11(周末) | 0 | 20261014 |
        | 20261013(二) | 67 | 20261014 |
        | 20261014(三) | 36 | 20261014 |
        | 20260101(元旦) | 0 | 20261014 |

        逐日行数与真实交易日对上（非交易日为空），所以**数据属于请求日**；
        `qdate` 恒等于"最近交易日"，拿它当数据日会把 10-09 的池子标成 10-14。
        上游为何这样设计不明，按观察到的行为用：`requested` 才是数据日，
        `qdate` 只作为原始字段透出，供调用方需要时自己看。

        剩一个无法自证的点：接口不返回数据所属日，若它真在某天静默回退旧数据，
        这里看不出来 —— 要强校验得拿当日涨停家数跟别的源对，属于调用方的事。
        """
        d = str(date or "").replace("-", "")
        url = ("https://push2ex.eastmoney.com/getTopicZTPool"
               "?ut=7eea3edcaed734bea9cbfc24409ed989"
               "&dpt=wz.ztzt&Pageindex=0&pagesize=300&sort=fbt:asc")
        if d:
            url += f"&date={d}"
        try:
            r = self._std.get(url, timeout=self.BASE_TIMEOUT)
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            js = r.json()
        except Exception as e:                                # noqa: BLE001
            return _err(f"{type(e).__name__}: {e}")
        dd = js.get("data") or {}
        data = dd.get("pool") or []

        def _num(v, default=0.0):
            try:
                return float(v)
            except (TypeError, ValueError):
                return default

        rows = []
        for it in data:
            fbt = str(it.get("fbt", "")).zfill(6)
            zt = it.get("zttj") or {}
            rows.append({
                "code": str(it.get("c", "")), "name": it.get("n"),
                "industry": it.get("hybk"),
                "percent": round(_num(it.get("zdp")), 2),
                "lbc": it.get("lbc") or 1,
                "days": zt.get("days"), "boards": zt.get("ct"),
                "first_seal": (f"{fbt[:2]}:{fbt[2:4]}:{fbt[4:6]}"
                               if len(fbt) == 6 else fbt),
                "break_count": it.get("zbc"),
                "seal_fund": round(_num(it.get("fund")) / 1e8, 2),      # 亿
                "turnover_rate": round(_num(it.get("hs")), 2),
                "float_mktcap": round(_num(it.get("ltsz")) / 1e8, 2),   # 亿
            })
        return _ok({"requested": d, "qdate": str(dd.get("qdate") or ""),
                    "count": len(rows), "rows": rows}, len(r.text))

    def em_kline(self, code: str = "688825", klt: int = 101,
                 beg: str = "0", end: str = "20500101", fqt: int = 1,
                 lmt: int = 60) -> dict:
        """K 线 (101日 / 102周 / 103月)"""
        return self._em_kline_secid(self._em_secid(code), klt, beg, end, fqt, lmt)

    def em_us_kline(self, code: str = "AAPL", klt: int = 101, fqt: int = 1,
                    lmt: int = 60) -> dict:
        """美股 K 线 (东财 push2his; secid 交易所前缀逐个试)

        腾讯 `usfqkline` 现在只回 2 根 (上游退化, 不是参数问题: 加不加
        count/qfq 都一样), 东财这条是活的 —— 105.AAPL 实测 1 万+ 根。
        纳斯达克 105 / 纽交所 106 / 美交所 107, 猜错会回 200 + 空 klines,
        所以按序试到有数据为止。
        """
        code = str(code or '').strip().upper()
        if code.startswith('US'):
            code = code[2:]
        last = None
        for pre in ('105', '106', '107'):
            last = self._em_kline_secid(f'{pre}.{code}', klt, '0', '20500101', fqt, lmt)
            if last.get('ok') and (last.get('data') or {}).get('rows'):
                return last
        return last or _err('empty code')

    def em_trends(self, code: str = "688825", ndays: int = 1,
                  premarket: bool = False) -> dict:
        """分时 (trends2): 当日 ndays=1 / 五日 ndays=5

        `premarket=True` 时带盘前集合竞价 (09:15-09:25): 东财的开关是
        `iscr=1&iscca=0` (口径同 akshare 的 stock_zh_a_hist_pre_min_em)。
        竞价段的行成交量为 0, 只有 09:25 那根含着竞价成交, 所以画出来是
        "一条价格线 + 收盘处一根量柱", 正是行情软件的竞价区样子。

        返回与腾讯 `tencent_minute_days` **同一种 days 形状**, 这样编排层
        换源不必改渲染: {days:[{date, rows:[[t, price, vol, amount], ...]}],
        name, preclose}。
        """
        ndays = 5 if int(ndays or 1) > 1 else 1
        r = self._em_get(
            "https://push2his.eastmoney.com/api/qt/stock/trends2/get",
            {"secid": self._em_secid(code), "ndays": ndays,
             "iscr": 1 if premarket else 0, "iscca": 0,
             "fields1": "f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13",
             "fields2": "f51,f52,f53,f54,f55,f56,f57,f58"},
        )
        if not r["ok"]:
            return r
        d = r["data"] if isinstance(r["data"], dict) else {}
        bucket = {}
        for line in (d.get("trends") or []):
            p = str(line).split(",")
            if len(p) < 7:
                continue
            date, _, tm = p[0].partition(" ")
            bucket.setdefault(date, []).append([tm[-5:], p[2], p[5], p[6]])
        if not bucket:
            return _err("no trends rows")
        days = [{"date": k, "rows": bucket[k]} for k in sorted(bucket)][-ndays:]
        return _ok({"name": d.get("name"), "preclose": d.get("preClose"),
                    "days": days, "ndays": ndays}, r.get("raw_size", 0))

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

