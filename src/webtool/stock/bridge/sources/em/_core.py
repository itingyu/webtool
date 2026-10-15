"""东财公共零件: 请求封装 / secid 归一 / F10 URL 组装"""
"""东方财富 (eastmoney) —— 32 个方法

端点: push2 / push2his / emweb / datacenter-web
反爬: push2 需固定 ut token; datacenter 需 source=WEB+client=PC; 公告一路走 curl 子进程

"""
from webtool.stock.bridge.sources._base import _err, _ok
from webtool.stock.bridge.sources import _symbol





class EmCoreMixin:
    """公共零件: 只依赖 self, 由 EmSource 组合进 MRO 最里层"""

    def _em_get(self, url: str, params: dict) -> dict:
        try:
            # push2 必须带 ut token, 否则沙盒 IP 被 ban (RemoteDisconnected)。
            # httpsdowngrade 会把 https 静默降成 http, 而 ulist.np/get 的
            # http 端点会 RemoteDisconnected —— 锁死 https 绕开降级。
            params = dict(params)
            if "ut" not in params:
                params["ut"] = "13697a1cc677c8bfa9a496437bfef419"
            r = self._std.get(url, params=params, timeout=self.BASE_TIMEOUT,
                              headers={'X-Scheme-Lock': url.split(':')[0]})
            if r.status_code != 200:
                return _err(f"status={r.status_code}", r.status_code)
            j = r.json()
            return _ok(j.get("data") or j, len(r.text))
        except Exception as e:
            return _err(str(e))

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

    def _em_kline_secid(self, secid: str, klt: int, beg: str, end: str,
                        fqt: int, lmt: int) -> dict:
        # fields1/fields2 必须显式给: 不带这两项时接口回 200 但 klines 为空
        # (信封 ok=True, rows=0), 看起来像"这只票没有 K 线"。
        r = self._em_get(
            "https://push2his.eastmoney.com/api/qt/stock/kline/get",
            {"secid": secid, "klt": klt, "beg": beg,
             "end": end, "fqt": fqt, "lmt": lmt,
             "fields1": "f1,f2,f3,f4,f5,f6",
             "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"},
        )
        if r["ok"]:
            raw = r["data"] if isinstance(r["data"], dict) else {}
            klines = raw.get("klines", [])
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
            r["data"] = {"rows": rows, "raw_count": len(klines),
                         "name": raw.get("name"), "code": raw.get("code"),
                         "market": raw.get("market")}
        return r

