"""腾讯财经 (qq) —— 9 个方法

端点: qt.gtimg.cn / web.ifzq.gtimg.cn / gu.qq.com
反爬: web.ifzq 的 fqkline 端点需 curl_cffi 指纹, 借用公共底座的会话

"""
from webtool.stock.bridge.sources._base import _err, _ok, SourceBase
from webtool.stock.bridge.sources import _symbol


import re


def _d8(s):
    """'20261020' / '2026-10-20' → '2026-10-20' (画图与排序都用它)"""
    s = str(s or '').strip()
    return f'{s[:4]}-{s[4:6]}-{s[6:8]}' if len(s) == 8 and s.isdigit() else s[:10]


def _fnum(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None

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
            r = self._cffi().get(
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
            r = self._cffi().get(
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
            r = self._cffi().get(
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

    def _tencent_minute_days(self, path: str, code: str) -> tuple:
        """分时原始取数 → (days, qt 字段数组)

        minute/query 的 data 是 {data: [...], date: '20261020'} (当日一条);
        day/query 的 data 是 [{date, data:[...]}, ...] (近 5 个交易日, 新→旧)。
        两种形状在这里收敛成同一种 days, 调用方不必关心走的是哪条端点。
        """
        r = self._cffi().get(
            f"https://web.ifzq.gtimg.cn/appstock/app/{path}",
            params={"code": _symbol.tencent(code)},
            headers={"Referer": "https://gu.qq.com/"},
            timeout=self.BASE_TIMEOUT,
        )
        if r.status_code != 200 or not r.text:
            raise RuntimeError(f"status={r.status_code}")
        j = r.json()
        if j.get("code") != 0:
            raise RuntimeError(f"code={j.get('code')} msg={j.get('msg', '')[:50]}")
        first = next(iter((j.get("data") or {}).values()), {}) or {}
        qt = next((v for v in (first.get("qt") or {}).values()
                   if isinstance(v, list) and len(v) > 4), None)
        inner = first.get("data")
        days = []
        if isinstance(inner, dict):                     # 当日
            days.append({"date": _d8(inner.get("date") or ""),
                         "rows": inner.get("data") or []})
        elif isinstance(inner, list):                   # 五日
            for it in inner:
                if isinstance(it, dict):
                    days.append({"date": _d8(it.get("date") or ""),
                                 "rows": it.get("data") or []})
        # 腾讯给新→旧, 统一成正序 (画图从左到右)
        days.sort(key=lambda d: d["date"])
        return days, qt

    def tencent_minute_days(self, code: str = "sh600519", ndays: int = 1) -> dict:
        """分时 (当日 / 五日): 归一成 {days:[{date, rows}], qt, name, preclose}

        rows 原样保留腾讯的 "HHMM price 累计量 累计额" 字符串, 解析放在
        command 层 (与 K 线的 normalize_rows 同一思路: 源形状各异, 渲染前一次洗干净)。

        已验证: sh600519 121 点/日 (午休压缩), hk00700 152 点 (09:30-12:00),
        五日 day/query 返回 5 个交易日共 1083 点。
        """
        ndays = 5 if int(ndays or 1) > 1 else 1
        path = "day/query" if ndays == 5 else "minute/query"
        try:
            days, qt = self._tencent_minute_days(path, code)
            if len(days) > ndays:
                days = days[-ndays:]
            data = {"symbol": code, "ndays": ndays, "days": days,
                    "qt": qt or [],
                    "name": qt[1] if qt and len(qt) > 1 else None,
                    "preclose": _fnum(qt[4]) if qt and len(qt) > 4 else None}
            return _ok(data, sum(len(d["rows"]) for d in days))
        except Exception as e:
            return _err(str(e))

    def tencent_ticks(self, code: str = "sh600519", max_pages: int = 120) -> dict:
        """逐笔成交 (分笔): 当日 09:25 起, 70 条/页, 翻页到底

        返回 [时间 HH:MM:SS, 价格, 成交量(手), 成交额] 升序。用于把分时量柱
        做到分钟以下 (30s/15s); 一整天约 60-80 页, 比分钟接口重, 只在显式
        要求细粒度时调用。
        """
        sym = _symbol.tencent(code)
        out, seen = [], set()
        pat = re.compile(r"(\d{2}:\d{2}:\d{2})/([\d.]+)/[-\d.]+/(\d+)/(\d+)")

        def _page(page: int):
            """取第 page 页 (70 条)。页大小是接口写死的, 只能靠并发削时间。"""
            r = self._cffi_tls().get(
                "https://stock.gtimg.cn/data/index.php",
                params={"appn": "detail", "action": "data",
                        "c": sym, "p": page},
                headers={"Referer": "https://gu.qq.com/"},
                timeout=self.BASE_TIMEOUT,
            )
            txt = r.content.decode("gbk", "ignore") if r.content else ""
            return pat.findall(txt)

        try:
            from concurrent.futures import ThreadPoolExecutor
            # 4 路并发: 茅台这种一天 58 页, 串行 6~8s, 并发约 1.5s;
            # 再高容易触发 gtimg 的频控, 4 是实测稳的值。
            with ThreadPoolExecutor(max_workers=4) as ex:
                page = 0
                while page < max_pages:
                    todo = list(range(page, min(page + 4, max_pages)))
                    stop = False
                    for hits in ex.map(_page, todo):
                        new = 0
                        for t, price, vol, amt in hits:
                            key = f"{t}|{price}|{vol}|{amt}"
                            if key in seen:
                                continue
                            seen.add(key)
                            new += 1
                            out.append([t, float(price), float(vol),
                                        float(amt)])
                        if new == 0:      # 翻到底 (空页 / 整页重复)
                            stop = True
                    if stop:
                        break
                    page += 4
            if not out:
                return _err("no tick rows")
            out.sort(key=lambda x: x[0])
            return _ok({"rows": out, "symbol": code}, len(out))
        except Exception as e:
            return _err(str(e))

    def tencent_us(self, code: str = "usTSLA") -> dict:
        """腾讯美股 (code: usTSLA / usAAPL / usNVDA / usMSFT)"""
        return self._tencent_q(code)

    def tencent_index(self, code: str = "s_sh000300") -> dict:
        """腾讯指数 (code: s_sh000300 / s_sz399006 / s_sh000001 ...)"""
        return self._tencent_q(code)

    # 一键验证

    # ── gtimg 系列 (自 sina.py 迁入: 端点 qt.gtimg.cn 属腾讯, 按数据源归位) ──
    # 扩展接口 (api_docs_extra.md)

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

    # qt.gtimg.cn 的富字段索引 (0-based)。**这是全仓唯一一份** ——
    # 校验法: 涨停价 == 昨收×1.1、换手 == 成交量÷流通股本、振幅 == (高-低)÷昨收
    _GTIMG_F = {
        'current': 3, 'prev_close': 4, 'open': 5, 'volume_hand': 6,
        'time': 30, 'change': 31, 'percent': 32, 'high': 33, 'low': 34,
        'amount_wan': 37, 'turnover_rate': 38, 'pe': 39,
        'amplitude': 43, 'float_mktcap': 44, 'total_mktcap': 45, 'pb': 46,
        'limit_up': 47, 'limit_down': 48, 'volume_ratio': 49, 'avg_price': 51,
    }

    def gtimg_quote_flat(self, codes) -> dict:
        """腾讯行情 **富字段** 版 —— 逐只展平成 dict, 含涨跌停价/量比/换手/市值

        与 `gtimg_hq` 的区别: 那个把原始 `v_sh600519="1~贵州茅台~..."` 原样
        交出去 (给人看/给上层自己解析), 这个解析成字段并归一 symbol ——
        短线动作 (可买性闸门、距涨停空间、量比) 要的就是这批字段。

        市场前缀归一见 `_symbol.tencent`: 传 `SH600519` 会被腾讯静默忽略
        (`pv_none_match`), 所以必须在入口转成小写形态。

        字段不足 49 列 (停牌 / 代码不存在 / 指数缺涨跌停位) 的行不进 rows,
        只记进 `missing`, 由调用方决定是报错还是跳过 —— 这里不替它判断。
        """
        if isinstance(codes, str):
            codes = [c for c in codes.split(',') if c.strip()]
        syms = [_symbol.tencent(c) for c in codes]
        try:
            r = self._std.get(
                'https://qt.gtimg.cn/q=' + ','.join(syms),
                timeout=self.BASE_TIMEOUT,
            )
            if r.status_code != 200:
                return _err(f'status={r.status_code}', r.status_code)
            raw = r.content.decode('gbk', errors='replace')
        except Exception as e:                                # noqa: BLE001
            return _err(f'{type(e).__name__}: {e}')

        def _num(v):
            try:
                return float(v)
            except (TypeError, ValueError):
                return None

        rows, missing = [], []
        for line in raw.strip().split(';'):
            if '="' not in line:
                continue
            sym = line.split('=', 1)[0].strip().removeprefix('v_')
            f = line.split('="', 1)[1].rstrip('";\n').split('~')
            if len(f) < 49 or not f[3]:
                missing.append(sym)
                continue
            row = {'symbol': sym, 'name': f[1], 'code': sym[2:],
                   'source': 'tencent'}
            for key, ix in self._GTIMG_F.items():
                row[key] = _num(f[ix]) if ix < len(f) else None
            row['quote_time'] = f[30] if len(f) > 30 else ''
            # 距涨停空间 = 还有几个点封板 (0 或负数 = 已封/超涨停异常)
            if row['current'] and row['limit_up']:
                row['to_limit_pct'] = round(
                    (row['limit_up'] / row['current'] - 1) * 100, 2)
            else:
                row['to_limit_pct'] = None
            rows.append(row)
        got = {r['symbol'] for r in rows} | set(missing)
        for s in syms:                       # 接口整体无返回时也要点出请求过的
            if s not in got:
                missing.append(s)
        return _ok({'rows': rows, 'missing': missing}, len(raw))

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
