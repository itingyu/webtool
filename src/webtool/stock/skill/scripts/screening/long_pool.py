"""
长线池筛选（6-18 月）
===================
来自 fsi/a-share-screen 长线规则
目的: 高股息 + 破净 + 核心资产底仓
"""
import webtool.stock.skill.scripts.feeds as xueqiu
from webtool.stock.skill.scripts._common import to_xueqiu_symbol, is_tradable, unbuyable_reason


def screen_one(code, name=None):
    """
    长线筛选（条件更宽松，重点是基本面）
    条件:
      1. 流通市值 > 500 亿
      2. PE 合理（< 行业中位数，粗略判断）
      3. 趋势向上（不强制）
    注: 股息率、PB 破净、ROE 等需要财务数据，雪球 f10/indicators 已下线
        这部分标记为待验证，由 agent 用 clients.web_search 补充
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

    if float_cap_yi < 500:
        return {"code": code, "name": name_str,
                "error": f"市值 {float_cap_yi:.0f} 亿 < 500 亿",
                "failed_gate": "市值"}

    pe = quote.get("pe_ttm")
    pb = quote.get("pb")

    return {
        "code": code,
        "symbol": symbol,
        "name": name_str,
        "float_market_capital_yi": round(float_cap_yi, 2),
        "pe_ttm": pe,
        "pb": pb,
        "industry": xueqiu.get_industry(symbol),
        "pool": "长线",
        "待验证": [
            "PB < 1.0x（破净优先）",
            "股息率 > 4.0%",
            "ROE > 8%（连续 3 年）",
            "资产负债率 < 70%",
        ],
    }


def suggest_typical_stocks():
    """
    长线典型标的（来自 fsi a-share-screen）
    """
    return {
        "银行": ["601288 农业银行", "601939 建设银行", "601398 工商银行"],
        "煤炭": ["601088 中国神华", "601225 陕西煤业", "601699 潞安环能"],
        "公用": ["600900 长江电力", "600886 国投电力", "600025 华能水电"],
        "高速铁路": ["001965 招商公路", "601006 大秦铁路", "600377 宁沪高速"],
        "保险": ["601601 中国太保", "601628 中国人寿", "601318 中国平安"],
        "运营商": ["600941 中国移动", "600050 中国联通"],
    }