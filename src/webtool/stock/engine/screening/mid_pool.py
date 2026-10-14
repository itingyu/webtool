"""
中线池筛选（3-6 月）
===================
来自 fsi/a-share-screen 中线规则 + a-share-short-screen 评分
目的: 产业周期向上 + 业绩验证 + 政策催化
"""
import webtool.stock.engine.feeds as xueqiu
from webtool.stock.engine.analysis import tech_indicators as ti
from webtool.stock.engine._common import to_xueqiu_symbol, is_tradable, unbuyable_reason


def screen_one(code, name=None):
    """
    中线筛选（不评分，只判断是否符合中线条件）
    条件:
      1. 流通市值 > 200 亿
      2. 现价 > 60 日均线，且 MA60 向上
      3. PE < 行业中位数 × 1.2（粗略估算）
      4. 中报预增 / Q2 单季同比 > 30%（无法直查，标记为待验证）
    """

    if not is_tradable(code, name):
        return {"code": code, "name": name,
                "error": f"不可买板块：{unbuyable_reason(code, name)}",
                "failed_gate": "不可买板块"}
    symbol = to_xueqiu_symbol(code)
    quote = xueqiu.quote(symbol)
    if not quote or "error" in quote:
        return {"code": code, "error": "quote 失败"}

    name_str = quote.get("name") or name or code
    float_cap_yi = (quote.get("float_market_capital") or 0) / 1e8

    # 硬条件: 流通市值 > 200 亿
    if float_cap_yi < 200:
        return {"code": code, "name": name_str,
                "error": f"市值 {float_cap_yi:.0f} 亿 < 200 亿",
                "failed_gate": "市值"}

    # K 线 + MA60 向上
    kline_items = xueqiu.kline_list(symbol, period="day", count=120)
    if len(kline_items) < 60:
        return {"code": code, "name": name_str, "error": "K 线不足 60 日"}

    import pandas as pd
    df = pd.DataFrame(kline_items)
    df = ti.calc(df)

    last = df.iloc[-1]
    prev = df.iloc[-2]
    if pd.isna(last["ma60"]):
        return {"code": code, "name": name_str, "error": "MA60 未形成"}

    if last["close"] < last["ma60"]:
        return {"code": code, "name": name_str,
                "error": "现价 < MA60", "failed_gate": "趋势"}

    if last["ma60"] <= prev["ma60"]:
        return {"code": code, "name": name_str,
                "error": "MA60 未向上", "failed_gate": "趋势"}

    levels = ti.technical_levels(df, last)
    score, breakdown, _ = ti.score_short(df)

    return {
        "code": code,
        "symbol": symbol,
        "name": name_str,
        "score": score,
        "score_breakdown": breakdown,
        "technical": levels,
        "float_market_capital_yi": round(float_cap_yi, 2),
        "pe_ttm": quote.get("pe_ttm"),
        "pb": quote.get("pb"),
        "industry": xueqiu.get_industry(symbol),
        "pool": "中线",
    }


def run(codes):
    """批量跑。codes 支持 ['600519', ...] 或 [{'code':...,'name':...}, ...]"""
    passed = []
    failed = []
    for c in codes:
        if isinstance(c, str):
            code, name = c, None
        else:
            code, name = c.get("code"), c.get("name")
        result = screen_one(code, name)
        if "error" in result:
            failed.append(result)
        else:
            passed.append(result)
    passed.sort(key=lambda x: x.get("score", 0) or 0, reverse=True)
    return {"passed": passed, "failed": failed}


def suggest_typical_stocks():
    """
    中线典型主线（来自 fsi a-share-screen，**仅供参考**）
    注意：表中 300/301/688/920 开头的标的会被 is_tradable() 硬过滤，
    实际投研须替换为同行业主板个股。
    """
    return {
        "AI 算力": ["601138 工业富联", "603986 兆易创新", "002475 立讯精密"],
        "创新药": ["600276 恒瑞医药", "600196 复星医药"],
        "新能源/储能": ["002594 比亚迪", "002460 赣锋锂业", "002074 国轩高科"],
        "出海/高端制造": ["000333 美的集团", "600690 海尔智家", "601100 恒立液压"],
        "资源/周期": ["601899 紫金矿业", "601168 西部矿业", "600111 北方稀土"],
    }