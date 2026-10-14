"""
单股深度分析
============
整合 stock-analysis 的"输入股票代码 → 决策看板"逻辑
数据源: 雪球 quote/K线/f10/industry（替代原 akshare 方案，沙盒稳定）
"""
from datetime import datetime, date

import pandas as pd

import webtool.stock.skill.scripts.feeds as xueqiu
import webtool.stock.skill.scripts.feeds as cninfo
from webtool.stock.skill.scripts.analysis import tech_indicators as ti
from webtool.stock.skill.scripts._common import to_xueqiu_symbol, market_of, stock_links


def _date_default(o):
    if isinstance(o, (datetime, date)):
        return o.strftime("%Y-%m-%d")
    raise TypeError


def _kline_df(items):
    """雪球 K 线 list → DataFrame"""
    if not items:
        return pd.DataFrame()
    rows = []
    for it in items:
        rows.append({
            "date": datetime.strptime(it["date"], "%Y-%m-%d"),
            "open": it.get("open"),
            "high": it.get("high"),
            "low": it.get("low"),
            "close": it.get("close"),
            "volume": it.get("volume"),
            "amount": it.get("amount"),
        })
    return pd.DataFrame(rows)


def analyze(code, news_items=None):
    """
    单只股票深度分析
    code: 6 位 A 股代码 / SH600519 / SZ000001
    news_items: 可选，新闻标题/文本列表（喂给 score_general 的消息面 30 分）。
                不传时消息面按中性 15/30 计，由调用方补新闻后再复核评分。
    返回: 决策看板 dict
    """
    symbol = to_xueqiu_symbol(code)

    # 1. 实时 quote
    quote = xueqiu.quote(symbol)
    if not quote or "error" in quote:
        return {"code": code, "error": "quote 拉取失败"}

    name = quote.get("name") or code

    # 2. K 线（60 天）
    kline_items = xueqiu.kline_list(symbol, period="day", count=60)
    if not kline_items:
        return {"code": code, "name": name, "error": "K 线拉取失败"}

    df = _kline_df(kline_items)
    df = ti.calc(df)

    # 3. 评分（通用版）
    score, breakdown, last, warnings = ti.score_general(
        df, news_items=news_items)  # 0-100：技术60+消息30+宏观10

    # 4. 技术位
    levels = ti.technical_levels(df, last)

    # 5. 行业归属
    industry = xueqiu.industry(symbol)

    # 6. 公告（最近 7 天）
    ann = cninfo.announcements(code, days=7)

    # 7. 流通市值（雪球单位是元，转亿元）
    float_cap_yi = (quote.get("float_market_capital") or 0) / 1e8

    # 8. 决策信号
    signal = "持有"
    if score is not None:
        if warnings:
            signal = "观望（触发禁买规则）"
        elif score >= 80:
            signal = "强买入"
        elif score >= 60:
            signal = "买入"
        elif score >= 40:
            signal = "持有"
        elif score >= 20:
            signal = "减仓"
        else:
            signal = "卖出"

    # 9. 公司画像（官网 / 法人 / 主营 / 上市日期）+ 市场前缀 + 数据源链接
    market = market_of(code)
    profile = _extract_profile(cninfo.company_intro(code))
    links = stock_links(code)

    return {
        "code": code,
        "symbol": symbol,
        "market": market,
        "name": name,
        "as_of": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "quote": {
            "current": quote.get("current"),
            "percent": quote.get("percent"),
            "open": quote.get("open"),
            "high": quote.get("high"),
            "low": quote.get("low"),
            "volume": quote.get("volume"),
            "amount": quote.get("amount"),
            "turnover_rate": quote.get("turnover_rate"),
            "pe_ttm": quote.get("pe_ttm"),
            "pb": quote.get("pb"),
            "float_market_capital_yi": round(float_cap_yi, 2),
        },
        "technical": levels,
        "score": score,
        "score_breakdown": breakdown,
        "warnings": warnings,
        "signal": signal,
        "industry": industry,
        "profile": profile,
        "links": links,
        "announcements_7d": ann[:5],
        "last_date": str(df["date"].iloc[-1]) if "date" in df.columns else None,
    }


def _extract_profile(intro):
    """
    从 cninfo company_intro 返回中提取画像字段
    返回: {full_name, legal_rep, website, address, listing_date, founded_date, main_business, industry_csrc}
    """
    if not intro or not isinstance(intro, dict):
        return {}
    recs = (intro.get("data") or {}).get("records") or []
    if not recs:
        return {}
    basic = (recs[0].get("basicInformation") or [{}])[0]
    listing = (recs[0].get("listingInformation") or [{}])[0]
    return {
        "full_name": basic.get("ORGNAME"),
        "legal_rep": basic.get("F003V"),
        "website": basic.get("F011V"),
        "address": basic.get("F005V"),
        "founded_date": basic.get("F010D"),
        "listing_date": basic.get("F006D"),
        "main_business": basic.get("F015V"),
        "industry_csrc": basic.get("F032V"),
        "phone": basic.get("F013V"),
        "email": basic.get("F012V"),
        "underwriter": listing.get("F047V"),
    }