"""腾讯财经 (qq) —— 9 个方法

端点: qt.gtimg.cn / web.ifzq.gtimg.cn / gu.qq.com
反爬: web.ifzq 的 fqkline 端点需 curl_cffi 指纹, 借用公共底座的会话

"""
from webtool.stock.bridge.sources._base import _err, _ok, SourceBase
from webtool.stock.bridge.sources import _symbol
import json


import re

class TencentSource(SourceBase):
    """腾讯财经 (qq) 方法集 —— 由 sources/__init__.py 的 APIClient 混入"""

    def _tencent_q(self, q: str) -> dict:
        """qt.gtimg.cn 统一入口 —— code 在此归一 (`_symbol.tencent`)。

        大小写敏感: 传 `SH600519` 返回 HTTP 200 + `pv_none_match`,
        信封 ok=True 但数据是"无匹配"。专有 prefix (`s_sz000001` /
        `usTSLA` / `hkHSI` / `jj000001`) 原样透传。
        """
        q = _symbol.join(q, _symbol.tencent)
        try:
            r = self._std.get(f"https://qt.gtimg.cn/q={q}",
                              headers={"Referer": "https://gu.qq.com/"},
                              timeout=self.BASE_TIMEOUT)
            if r.status_code != 200 or not r.text:
                return _err(f"status={r.status_code}", r.status_code)
            results = []
            for line in r.text.splitlines():
                m = re.search(r'v_(\w+)="(.*)";', line)
                if m:
                    sym, body = m.group(1), m.group(2)
                    fields = body.split("~")
                    results.append({"symbol": sym, "fields": fields})
            return _ok(results, len(r.text))
        except Exception as e:
            return _err(str(e))

    def tencent_a(self, symbol: str = "sh688825") -> dict:
        """A 股实时 (字段最全)"""
        return self._tencent_q(symbol)

    def tencent_batch(self, symbols: str = "sh688825,sz000001,sh600519") -> dict:
        """A 股批量"""
        return self._tencent_q(symbols)

    def tencent_hk(self, code: str = "hk01810") -> dict:
        """港股实时"""
        return self._tencent_q(code)

    # efinance (5 个)

    def tencent_global(self, code: str = "usTSLA") -> dict:
        """腾讯全市场报价 (qt.gtimg.cn/q=) - 反爬补强后真通

        用不带点 / 不带前缀的写法: usAAPL / sh900901 (us.AAPL / b_sh900901 均不可用)

        支持 prefix:
          A 股: sh600519, sz000001
          港股: hk00700, hk09988, hk02318, hk03690, hk01810
          美股: usTSLA, usAAPL, usNVDA, usMSFT, usGOOGL, usAMZN, usMETA, usBABA
          B 股: sh900901 ~ sh900907
          指数: s_sh000001/000300/000016, s_sz399001/399006/399905/399852
                usDJI, usIXIC, hkHSI, hkHSCEI
        批量: 多 code 用 , 分隔一次拿
        """
        return self._tencent_q(code)

    def tencent_kline_global(self, code: str = "hk00700", period: str = "day",
                             count: int = 320, fq: str = "qfq") -> dict:
        """腾讯 web.ifzq 全市场 K 线 (反爬补强后真通)

        该域名下走 appstock/app/fqkline/get?param={code},{period},,,{count},{fq};
        旧接口路径已 403, 不要换回去

        已验证:
          A 股: sh600519 day qfq → size=24685
          港股: hk00700 day qfq → size=49972 (320 根 K 线!)
          美股: usTSLA day qfq → size=1637

        period: day/week/month
        fq: qfq (前复权) / hfq (后复权) / 不复权
        """
        try:
            r = self._xueqiu_session().get(
                "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get",
                params={"param": f"{_symbol.tencent(code)},{period},,,{count},{fq}"},
                headers={"Referer": "https://gu.qq.com/"},
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200 or not r.text:
                return _err(f"status={r.status_code}", r.status_code)
            j = r.json()
            if j.get("code") != 0:
                return _err(f"code={j.get('code')} msg={j.get('msg','')[:50]}")
            data = j.get("data", {})
            if not data:
                return _err("空 data")
            # 取第一个 key
            first = list(data.values())[0] if data else {}
            if isinstance(first, dict):
                qt = first.get("qt", {})
                # K 线可能在 day/week/m1/m5/... 不同字段
                for k in ("day", "week", "month", "qfqday", "qfqmonth"):
                    if first.get(k):
                        return _ok({
                            "symbol": code, "period": period, "fq": fq,
                            "qt": qt, "klines": first[k],
                            "count": len(first[k]),
                        }, len(r.text))
                # 取所有非 qt 数组
                klines = []
                for k, v in first.items():
                    if isinstance(v, list) and v and isinstance(v[0], list):
                        klines = v
                        break
                return _ok({
                    "symbol": code, "period": period, "qt": qt, "klines": klines,
                    "count": len(klines),
                }, len(r.text))
            return _ok({"data": data}, len(r.text))
        except Exception as e:
            return _err(str(e))

    def tencent_us_kline(self, code: str = "usTSLA", period: str = "day",
                         count: int = 320, fq: str = "qfq") -> dict:
        """腾讯 web.ifzq 美股 K 线 (usfqkline/get, 独立 endpoint)

        该域名下走 appstock/app/usfqkline/get?param={code},{period},,,{count},{fq};
        旧接口路径已 403, 不要换回去

        已验证:
          usTSLA day qfq → size=1697 (含 day=2)
          usTSLA week qfq → size=1607
          usTSLA month qfq → size=1608
          usAAPL/NVDA day qfq → size=1700/1717
        """
        try:
            r = self._xueqiu_session().get(
                "https://web.ifzq.gtimg.cn/appstock/app/usfqkline/get",
                params={"param": f"{_symbol.tencent(code)},{period},,,{count},{fq}"},
                headers={"Referer": "https://gu.qq.com/"},
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200 or not r.text:
                return _err(f"status={r.status_code}", r.status_code)
            j = r.json()
            if j.get("code") != 0:
                return _err(f"code={j.get('code')} msg={j.get('msg','')[:50]}")
            data = j.get("data", {})
            first = list(data.values())[0] if data else {}
            if isinstance(first, dict):
                return _ok({
                    "symbol": code, "period": period, "fq": fq,
                    "qt": first.get("qt", {}),
                    "klines": first.get("day", []),
                    "count": len(first.get("day", [])),
                }, len(r.text))
            return _ok({"data": data}, len(r.text))
        except Exception as e:
            return _err(str(e))

    def tencent_minute(self, code: str = "sh600519") -> dict:
        """腾讯 web.ifzq 分时数据 (minute/query)

        已验证:
          sh600519 → size=10872 (A 股分时)
          hk00700 → size=14210 (港股分时)
          usTSLA → size=1420 (美股分时)
        """
        try:
            r = self._xueqiu_session().get(
                "https://web.ifzq.gtimg.cn/appstock/app/minute/query",
                params={"code": _symbol.tencent(code)},
                headers={"Referer": "https://gu.qq.com/"},
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200 or not r.text:
                return _err(f"status={r.status_code}", r.status_code)
            j = r.json()
            if j.get("code") != 0:
                return _err(f"code={j.get('code')} msg={j.get('msg','')[:50]}")
            data = j.get("data", {})
            first = list(data.values())[0] if data else {}
            if isinstance(first, dict):
                return _ok({
                    "symbol": code,
                    "qt": first.get("qt", {}),
                    "data": first.get("data", first.get("minute", [])),
                }, len(r.text))
            return _ok({"data": data}, len(r.text))
        except Exception as e:
            return _err(str(e))

    def tencent_us(self, code: str = "usTSLA") -> dict:
        """腾讯美股 (code: usTSLA / usAAPL / usNVDA / usMSFT)"""
        return self._tencent_q(code)

    def tencent_index(self, code: str = "s_sh000300") -> dict:
        """腾讯指数 (code: s_sh000300 / s_sz399006 / s_sh000001 ...)"""
        return self._tencent_q(code)

    # 一键验证
