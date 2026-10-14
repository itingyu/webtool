"""
雪球 fetcher
============
沙盒验证：quote / K 线 / f10 / industry / 批量实时报价 全部通
关键修复：curl_cffi Chrome110 impersonate + 3 页 warmup

鲁棒性：
  - quote 失败 → 自动 fallback 到东财 push2（接口指南.md §东方财富）
  - kline 失败 → 自动 fallback 到东财 push2his
  - 空 data/0 字节 → 打 WARN 日志，不静默吞
"""
import time
from datetime import datetime

from webtool.stock.skill.scripts._common import xq_session, to_xueqiu_symbol, log


# ============================================================
#  单股 / 批量实时行情
# ============================================================
def quote(symbol, with_fallback=True):
    """
    单股实时 quote
    symbol: SH600519 / SZ000001 / BJ920178
    返回字段：current / percent / chg / open / high / low / volume / amount
              pe_ttm / pb / market_capital(元) / float_market_capital(元)

    with_fallback=True 时，失败/字段缺失会 fallback 到东财 push2
    """
    result = None
    try:
        r = xq_session().get(
            "https://stock.xueqiu.com/v5/stock/quote.json",
            params={"symbol": symbol, "extend": "detail"},
            headers={"Referer": "https://xueqiu.com/hq"},
        )
        q = r.json().get("data", {}).get("quote", {})
        if not q:
            log(f"雪球 quote {symbol} 返回空 quote", "WARN")
        else:
            # 字段健全性检查
            if q.get("current") is None:
                log(f"雪球 quote {symbol} 缺少 current（可能停牌）", "WARN")
            result = {
                "symbol": q.get("symbol"),
                "code": q.get("code"),
                "name": q.get("name"),
                "current": q.get("current"),
                "percent": q.get("percent"),
                "chg": q.get("chg"),
                "open": q.get("open"),
                "high": q.get("high"),
                "low": q.get("low"),
                "last_close": q.get("last_close"),
                "volume": q.get("volume"),
                "amount": q.get("amount"),
                "turnover_rate": q.get("turnover_rate"),
                "pe_ttm": q.get("pe_ttm"),
                "pb": q.get("pb"),
                "market_capital": q.get("market_capital"),         # 元
                "float_market_capital": q.get("float_market_capital"),  # 元
            }
    except Exception as e:
        log(f"雪球 quote {symbol} 异常: {type(e).__name__}: {str(e)[:80]}", "WARN")

    # Fallback：缺关键字段时尝试东财
    if with_fallback and (not result or result.get("current") is None):
        code = symbol[-6:]
        from webtool.stock.skill.scripts.fetchers import eastmoney
        em_q = eastmoney.quote(code)
        if em_q and em_q.get("current") is not None:
            log(f"  → {symbol} fallback 到东财成功", "INFO")
            # 字段对齐
            em_q["symbol"] = symbol
            return em_q
        else:
            log(f"  → {symbol} 东财 fallback 也失败", "WARN")

    if result is None:
        return {"symbol": symbol, "error": "quote 拉取失败（雪球 + 东财 双源失败）"}
    return result


def quote_batch(codes):
    """
    批量实时报价
    codes: ['SH600519', 'SZ000001'] 或裸码 ['600519', '000001'] 均可（自动补前缀）
    """
    codes = [c if c[:2].upper() in ("SH", "SZ", "BJ") else to_xueqiu_symbol(c)
             for c in codes]
    try:
        r = xq_session().get(
            "https://stock.xueqiu.com/v5/stock/realtime/quotec.json",
            params={"symbol": ",".join(codes)},
            headers={"Referer": "https://xueqiu.com/hq"},
        )
        data = r.json().get("data", [])
        if not data:
            log(f"雪球 quote_batch {len(codes)} 只返回空", "WARN")
            return []
        out = []
        for d in data:
            sym = d.get("symbol") or ""
            out.append({
                "symbol": sym,
                "code": d.get("code") or sym[-6:],
                "name": d.get("name"),
                "current": d.get("current"),
                "percent": d.get("percent"),
                "chg": d.get("chg"),
                "last_close": d.get("last_close"),
                "volume": d.get("volume"),
                "amount": d.get("amount"),
                "open": d.get("open"),
                "high": d.get("high"),
                "low": d.get("low"),
                "turnover_rate": d.get("turnover_rate"),
                "amplitude": d.get("amplitude"),
                "market_capital": d.get("market_capital"),
            })
        return out
    except Exception as e:
        log(f"雪球 quote_batch 失败: {type(e).__name__}: {str(e)[:80]}", "WARN")
        return []


# ============================================================
#  K 线
# ============================================================
def kline(symbol, period="day", count=60, with_fallback=True):
    """
    雪球 K 线（日/周/月）
    period: day / week / month
    count: 60 (默认) / -N 表示全部历史

    关键：begin 必须用相对时间（now_ms - span*86400000），否则返回空
    Fallback：失败/空 → 东财 push2his
    """
    items = []
    try:
        now_ms = int(time.time() * 1000)
        if count > 0:
            # begin 决定实际可取条数。必须按**周期**反推自然日跨度并留余量，
            # 否则请求 250 条也只回 58 条 —— 长周期指标（MA60/年线）会全部算错。
            #   day   : 1.6 倍覆盖周末 + 长假
            #   week  : ×7 再留 1.4 倍
            #   month : ×30 再留 1.3 倍
            mult = {"day": 1.6, "week": 7 * 1.4, "month": 30 * 1.3}[period]
            cal_days = int(count * mult) + 15
        else:
            cal_days = {"day": 365 * 6, "week": 365 * 12, "month": 365 * 20}[period]
        r = xq_session().get(
            "https://stock.xueqiu.com/v5/stock/chart/kline.json",
            params={
                "symbol": symbol, "period": period, "type": "before",
                "count": count if count > 0 else -120,  # 负值=全部
                "begin": now_ms - cal_days * 86400000,
                "end": now_ms,
                "indicator": "kline",
            },
            headers={"Referer": "https://xueqiu.com/hq"},
        )
        d = r.json().get("data", {})
        cols = d.get("column", [])
        items = d.get("item", [])
        if not items or not cols:
            log(f"雪球 kline {symbol} 返回空 item (cols={len(cols)})", "WARN")
            items = []
        else:
            idx = {c: i for i, c in enumerate(cols)}
            out = []
            for it in items:
                out.append({
                    "timestamp": it[idx["timestamp"]],
                    "date": datetime.fromtimestamp(it[idx["timestamp"]] / 1000).strftime("%Y-%m-%d"),
                    "open": it[idx.get("open", -1)] if "open" in idx else None,
                    "high": it[idx.get("high", -1)] if "high" in idx else None,
                    "low": it[idx.get("low", -1)] if "low" in idx else None,
                    "close": it[idx.get("close", -1)] if "close" in idx else None,
                    "volume": it[idx.get("volume", -1)] if "volume" in idx else None,
                    "amount": it[idx.get("amount", -1)] if "amount" in idx else None,
                    "pct": it[idx.get("percent", -1)] if "percent" in idx else None,
                })
            items = out
    except Exception as e:
        log(f"雪球 kline {symbol} 异常: {type(e).__name__}: {str(e)[:80]}", "WARN")
        items = []

    # Fallback：空数据时尝试东财
    if with_fallback and not items:
        code = symbol[-6:]
        from webtool.stock.skill.scripts.fetchers import eastmoney
        em_kl = eastmoney.kline(code, count=count, period=period)
        if em_kl:
            log(f"  → {symbol} kline fallback 到东财成功 ({len(em_kl)} 条)", "INFO")
            items = em_kl
        else:
            log(f"  → {symbol} kline 东财 fallback 也失败", "WARN")
    return items


# ============================================================
#  公司 f10（公司概况 / 主营业务）
# ============================================================
def f10_company(symbol):
    """公司全称/简介"""
    try:
        r = xq_session().get(
            "https://stock.xueqiu.com/v5/stock/f10/cn/company.json",
            params={"symbol": symbol},
            headers={"Referer": "https://xueqiu.com/hq"},
        )
        company = r.json().get("data", {}).get("company", {})
        if not company:
            log(f"雪球 f10/company {symbol} 返回空", "WARN")
        return company
    except Exception as e:
        log(f"雪球 f10/company {symbol} 失败: {type(e).__name__}: {str(e)[:80]}", "WARN")
        return {}


def f10_business(symbol):
    """主营业务分析（21KB 文本，含经营分析说明）"""
    try:
        r = xq_session().get(
            "https://stock.xueqiu.com/v5/stock/f10/cn/business_analysis.json",
            params={"symbol": symbol},
            headers={"Referer": "https://xueqiu.com/hq"},
        )
        data = r.json().get("data", {})
        if not data:
            log(f"雪球 f10/business {symbol} 返回空", "WARN")
        return data
    except Exception as e:
        log(f"雪球 f10/business {symbol} 失败: {type(e).__name__}: {str(e)[:80]}", "WARN")
        return {}


# ============================================================
#  所属行业 / 概念
# ============================================================
def industry(symbol):
    """symbol 的所属行业与概念板块"""
    try:
        r = xq_session().get(
            "https://stock.xueqiu.com/v5/stock/industry/quote.json",
            params={"symbol": symbol},
            headers={"Referer": "https://xueqiu.com/hq"},
        )
        items = r.json().get("data", {}).get("items", [])
        if not items:
            log(f"雪球 industry {symbol} 返回空", "WARN")
            return []
        out = []
        for it in items:
            out.append({
                "ind_code": it.get("ind_code"),
                "ind_name": it.get("ind_name"),
                "ind_type": it.get("ind_type"),  # 1=行业 2=概念
                "percent": it.get("percent"),
            })
        return out
    except Exception as e:
        log(f"雪球 industry {symbol} 失败: {type(e).__name__}: {str(e)[:80]}", "WARN")
        return []


# ============================================================
#  便捷封装
# ============================================================
def get(code):
    """便捷：传 A 股代码，返回雪球 quote（带东财 fallback）"""
    return quote(to_xueqiu_symbol(code))


def get_kline(code, period="day", count=60):
    """便捷：传 A 股代码，返回雪球 K 线（带东财 fallback）"""
    return kline(to_xueqiu_symbol(code), period, count)


def get_industry(code):
    """便捷：传 A 股代码，返回所属行业"""
    return industry(to_xueqiu_symbol(code))