"""
东财 fetcher（沙盒 fallback）
============================
沙盒验证：push2 实时行情 / push2his K 线 可用（参考 接口指南.md）
主要作用：作为雪球 fetcher 的 fallback，避免单源挂掉后整链路崩
"""
from webtool.stock.skill.scripts._common import std_session, log


def _secid_for(code):
    """6 位 A 股代码 → 东财 secid: 600519 → '1.600519', 000001 → '0.000001'"""
    code = code.strip()
    # 沪市：60/68/9/5/7 开头；深市：00/30/20 开头；北交所：92/43/8 开头（secid 前缀是 0）
    if code.startswith(("60", "68", "9", "5", "7")):
        return f"1.{code}"
    return f"0.{code}"


def quote(code):
    """
    单股实时行情（东财 push2 备源）
    code: 6 位 A 股代码（无前缀）
    返回字段名对齐雪球：current / percent / chg / open / high / low / volume / amount
    """
    try:
        r = std_session().get(
            "https://push2.eastmoney.com/api/qt/stock/get",
            params={
                "secid": _secid_for(code),
                "fields": "f43,f44,f45,f46,f47,f48,f57,f58,f60,f116,f117,f162,f167,f168,f169,f170,f191,f192",
                "ut": "fa5fd1943c7b386f172d6893dbfba10b",
            },
            headers={
                "User-Agent": "Mozilla/5.0",
                "Referer": "https://quote.eastmoney.com/",
            },
            timeout=8,
        )
        if r.status_code != 200:
            log(f"东财 quote {code} HTTP {r.status_code}", "WARN")
            return {}
        d = r.json().get("data") or {}
        if not d or not d.get("f57"):
            log(f"东财 quote {code} 返回空 data", "WARN")
            return {}
        # f43=价格分 / f47=量手 / f48=金额元 / f170=涨跌幅%
        return {
            "code": d.get("f57"),
            "name": d.get("f58"),
            "current": (d.get("f43") or 0) / 100,
            "percent": (d.get("f170") or 0) / 100,
            "chg": (d.get("f169") or 0) / 100,
            "open": (d.get("f46") or 0) / 100,
            "high": (d.get("f44") or 0) / 100,
            "low": (d.get("f45") or 0) / 100,
            "last_close": (d.get("f60") or 0) / 100,
            "volume": d.get("f47") or 0,       # 手
            "amount": d.get("f48") or 0,       # 元
            "turnover_rate": (d.get("f168") or 0) / 100,
        }
    except Exception as e:
        log(f"东财 quote {code} 失败: {e}", "WARN")
        return {}


def kline(code, count=60, period="day"):
    """
    K 线（东财 push2his 备源）
    code: 6 位 A 股代码
    period: day / week / month（klt=101/102/103）
    """
    klt_map = {"day": "101", "week": "102", "month": "103"}
    klt = klt_map.get(period, "101")
    try:
        r = std_session().get(
            "https://push2his.eastmoney.com/api/qt/stock/kline/get",
            params={
                "secid": _secid_for(code),
                "klt": klt,
                # 注意：带 beg 时 lmt 失效（返回全量 6000+ 条），必须省略 beg
                "end": "20500101",
                "fqt": "1",
                "lmt": str(count),
                # K 线接口必须用 fields1/fields2 分开传，用单个 fields 会返回空数组
                "fields1": "f1,f2,f3,f4,f5,f6",
                "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
                "ut": "fa5fd1943c7b386f172d6893dbfba10b",
            },
            headers={
                "User-Agent": "Mozilla/5.0",
                "Referer": "https://quote.eastmoney.com/",
            },
            timeout=10,
        )
        if r.status_code != 200:
            log(f"东财 kline {code} HTTP {r.status_code}", "WARN")
            return []
        d = r.json().get("data") or {}
        if not d:
            log(f"东财 kline {code} 返回空 data", "WARN")
            return []
        lines = d.get("klines") or []
        if not lines:
            log(f"东财 kline {code} klines 为空", "WARN")
            return []
        out = []
        for line in lines:
            parts = line.split(",")
            if len(parts) < 6:
                continue
            # 形态：date,open,close,high,low,volume,amount,pct,chg,turnover,amplitude
            out.append({
                "date": parts[0],
                "open": float(parts[1]) if parts[1] else None,
                "close": float(parts[2]) if parts[2] else None,
                "high": float(parts[3]) if parts[3] else None,
                "low": float(parts[4]) if parts[4] else None,
                "volume": int(float(parts[5])) if parts[5] else None,
                "amount": float(parts[6]) if len(parts) > 6 and parts[6] else None,
                "pct": float(parts[7]) if len(parts) > 7 and parts[7] else None,
            })
        return out
    except Exception as e:
        log(f"东财 kline {code} 失败: {e}", "WARN")
        return []
