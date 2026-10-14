"""
短线池筛选（1-5 个交易日持有周期，T+1 短线）
===========================
整合 a-share-short-screen 短线池 + fsi a-share-screen 短线规则
候选池来源: 新浪涨幅榜 TopN + 同花顺行业领涨股
"""
import pandas as pd

import webtool.stock.engine.feeds as xueqiu
import webtool.stock.engine.feeds as ths
import webtool.stock.engine.feeds as sina
from webtool.stock.engine.analysis import tech_indicators as ti
from webtool.stock.engine.screening import risk_check
from webtool.stock.engine._common import to_xueqiu_symbol, log, is_tradable, unbuyable_reason


def _kline_df(items):
    if not items:
        return pd.DataFrame()
    rows = []
    for it in items:
        rows.append({
            "date": it["date"],
            "open": it.get("open"),
            "high": it.get("high"),
            "low": it.get("low"),
            "close": it.get("close"),
            "volume": it.get("volume"),
            "amount": it.get("amount"),
        })
    return pd.DataFrame(rows)


def build_candidate_pool(top_n_movers=30, top_n_sectors=10):
    """
    构建短线候选池
    合并: 新浪涨幅榜 Top N + 同花顺行业领涨股

    过滤：
      - **不可买板块**（`_common.is_tradable`，唯一口径）：创业板 / 科创板 /
        北交所 / B 股 / ST 一律不进入候选池
    """
    candidates = {}

    # 来源 1: 涨幅榜。不可买板块（300/301/688/8/920）常占据涨幅榜前列，
    # 因此取更宽的名单再过滤，最终只保留涨幅 2%-8% 的「温和强势」区间。
    movers = sina.rank_list(kind='涨幅榜', count=max(top_n_movers, 300))
    for m in movers:
        c = m.get("code")
        if not c:
            continue
        if not is_tradable(c, m.get("name")):
            continue
        try:
            pct = float(m.get("changepercent") or 0)
        except (TypeError, ValueError):
            continue
        if not (2.0 <= pct <= 8.0):
            continue
        candidates[c] = {
            "code": c,
            "name": m.get("name"),
            "source": "涨幅榜(2-8%)",
            "changepercent": pct,
            "nmc_wan": m.get("nmc"),  # 万
        }

    # 来源 2: 行业领涨股
    sectors = ths.industry_rows(limit=top_n_sectors)
    for s in sectors:
        leader_code = s.get("leader_code") or ""
        leader_name = s.get("leader")
        if not leader_code or len(leader_code) != 6:
            continue
        if not is_tradable(leader_code, leader_name):
            continue
        candidates[leader_code] = {
            "code": leader_code,
            "name": leader_name,
            "source": f"行业领涨({s.get('name')})",
            "changepercent": float(s.get("leader_pct") or 0),
            "nmc_wan": None,
        }

    return list(candidates.values())


def _position_pct(df, window=60):
    """
    现价在近 window 日区间中的分位（0 = 区间最低，1 = 区间最高）。
    K 线不足 window 日时用实际长度并标注，不硬凑。
    """
    tail = df.tail(window)
    if tail.empty:
        return None, 0
    hi, lo = tail["high"].max(), tail["low"].min()
    if hi is None or lo is None or hi <= lo:
        return None, len(tail)
    return (tail["close"].iloc[-1] - lo) / (hi - lo), len(tail)


def _sw1(raw):
    """从雪球行业列表里取申万一级（ind_type=1）名称，取不到返回 None"""
    if isinstance(raw, str):
        return raw or None
    if not isinstance(raw, list):
        return None
    for it in raw:
        if it.get("ind_type") == 1:
            return it.get("ind_name")
    return raw[0].get("ind_name") if raw else None


def screen_one(code, name=None, min_score=60):
    """
    单只股票短线筛选：6 项工具自动闸门，任一不过即剔除并写明 `failed_gate`。
    闸门清单见 references/data/screen-criteria.md 的 A 层。
    """
    if not is_tradable(code, name):
        return {"code": code, "name": name,
                "error": f"不可买板块：{unbuyable_reason(code, name)}",
                "failed_gate": "不可买板块"}

    symbol = to_xueqiu_symbol(code)

    # 1. quote; feeds.quote 回 {原始代码: 行情}, 单只取任一值
    qmap = xueqiu.quote(symbol)
    quote = (qmap.get(symbol) or next(iter(qmap.values()), None)) \
        if isinstance(qmap, dict) and qmap else None
    if not quote or quote.get("error"):
        return {"code": code, "name": name, "error": "quote 失败"}

    # 2. 硬门槛: 流通市值 ≥ 50 亿（雪球单位元，无上限）
    #    feeds.quote → _flat_quote 的键是 float_mktcap (fetchers 契约),
    #    原先取 float_market_capital 恒为 None → 市值闸门把所有票错杀
    float_cap_yi = (quote.get("float_mktcap")
                    or quote.get("float_market_capital") or 0) / 1e8
    if float_cap_yi < 50:
        return {"code": code, "name": quote.get("name"),
                "error": f"流通市值 {float_cap_yi:.1f} 亿 < 50 亿",
                "failed_gate": "市值"}

    # 3. 硬门槛: 非 ST（雪球名字不带 ST / *ST）
    name_str = quote.get("name", "") or ""
    if "ST" in name_str or "*ST" in name_str:
        return {"code": code, "name": name_str,
                "error": "ST/*ST 排除", "failed_gate": "ST"}

    # 4. K 线; kline_list 回 {symbol, period, count, items}, 取 items
    kres = xueqiu.kline_list(symbol, period="day", count=60)
    kline_items = (kres.get('items') if isinstance(kres, dict) else kres) or []
    if len(kline_items) < 30:
        return {"code": code, "name": name_str, "error": "K 线不足 30 日"}

    # 5. 流动性: 20 日均成交额 ≥ 1 亿
    df = _kline_df(kline_items)
    avg_amount_yi = df["amount"].tail(20).mean() / 1e8 if "amount" in df.columns else 0
    if avg_amount_yi < 1:
        return {"code": code, "name": name_str,
                "error": f"20 日均成交 {avg_amount_yi:.2f} 亿 < 1 亿",
                "failed_gate": "流动性"}

    # 6. 指标 + 评分
    df = ti.calc(df)
    score, breakdown, last = ti.score_short(df)

    if score is None or score < min_score:
        return {"code": code, "name": name_str,
                "score": score, "error": f"评分 {score} < {min_score}",
                "failed_gate": "评分"}

    # 7. 风险股核查（重组 / 事件类）—— 命中即剔除
    risk = risk_check.scan(code, name_str)
    if risk["hit"]:
        kw = "、".join(sorted({h["keyword"] for h in risk["hit"]}))
        return {"code": code, "name": name_str, "score": score,
                "error": f"风险股命中：{kw}",
                "risk_detail": risk["hit"][:3],
                "failed_gate": "风险股"}

    # 8. 技术位 + 60 日位置分位（供 agent 做高位股判定，见 screen-criteria B 层）
    levels = ti.technical_levels(df, last)
    pos, pos_n = _position_pct(df, 60)
    pos_tag = ("高位（近 60 日 >90% 分位）" if pos is not None and pos > 0.9
               else "中位" if pos is not None and 0.3 <= pos <= 0.9
               else "低位" if pos is not None else "无法判定")

    return {
        "code": code,
        "symbol": symbol,
        "name": name_str,
        "score": score,
        "score_breakdown": breakdown,
        "technical": levels,
        "position_60d": round(pos, 3) if pos is not None else None,
        "position_tag": pos_tag,
        "position_window": pos_n,
        "float_market_capital_yi": round(float_cap_yi, 2),
        "avg_amount_20d_yi": round(avg_amount_yi, 2),
        "pe_ttm": quote.get("pe_ttm"),
        "pb": quote.get("pb"),
        "industry": _sw1(xueqiu.get_industry(symbol)),
        "risk_pending": risk["pending"],
    }


def run(top_n_movers=300, top_n_sectors=10, min_score=60):
    """
    主入口：跑一次短线筛选
    返回: 通过硬门槛的候选，按评分排序

    排序后再加**组合层提示**：
      - `position_60d` > 0.9 → 高位股，进卡片前须确认 60 日涨幅（B 层人工项）
      - `industry` 去重后 < 3 个申万一级 → 板块过度集中，须人工取舍
    组合层只提示、不剔除 —— 取舍权留给 agent（分散度与集中度是策略选择，不是硬错）。
    """
    log("构建候选池...")
    pool = build_candidate_pool(top_n_movers, top_n_sectors)
    log(f"候选池 {len(pool)} 只")

    passed = []
    failed = []
    for c in pool:
        result = screen_one(c["code"], c.get("name"), min_score=min_score)
        result["source"] = c.get("source", "")
        result["candidate_changepercent"] = c.get("changepercent")

        if "error" in result:
            failed.append(result)
        else:
            passed.append(result)

    passed.sort(key=lambda x: x.get("score", 0), reverse=True)

    industries = [p.get("industry") for p in passed if p.get("industry")]
    uniq_ind = sorted(set(industries))
    high_pos = [p["code"] for p in passed
                if (p.get("position_60d") or 0) > 0.9]

    portfolio_notes = []
    if len(uniq_ind) < 3 and len(passed) >= 3:
        portfolio_notes.append(
            f"板块分散不足：仅 {len(uniq_ind)} 个申万一级（{uniq_ind}），要求 ≥ 3 个，须人工取舍")
    if high_pos:
        portfolio_notes.append(
            f"高位股（近 60 日 >90% 分位）：{high_pos}，进卡片前确认 60 日涨幅是否已透支")

    return {
        "pool_size": len(pool),
        "passed": passed,
        "failed": failed,
        "passed_count": len(passed),
        "failed_count": len(failed),
        "min_score_threshold": min_score,
        "industry_dispersion": len(uniq_ind),
        "industries": uniq_ind,
        "high_position_codes": high_pos,
        "portfolio_notes": portfolio_notes,
    }