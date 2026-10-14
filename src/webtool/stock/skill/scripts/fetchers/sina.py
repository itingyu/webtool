"""
新浪 fetcher
============
沙盒验证：涨幅榜（7581B）/ 全市场列表（3715B）/ 单股 5 档行情（287B）全通
关键：Referer: https://finance.sina.com.cn/

注意：
  - 涨幅榜含北交所（bj 前缀），上层调用方需自行过滤
  - 行情 0 字节或字段全 0 时打 WARN 日志
"""
import json
from webtool.stock.skill.scripts._common import std_session, to_sina_symbol, log


def _rank_page(sort, asc, page, num):
    r = std_session().get(
        "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
        "Market_Center.getHQNodeData",
        params={"node": "hs_a", "sort": sort, "asc": asc,
                "num": num, "page": page},
        headers={"Referer": "https://finance.sina.com.cn/"},
        timeout=10,
    )
    if r.status_code != 200 or len(r.text) < 100:
        return None
    return json.loads(r.text)


def rank_list(num=100, sort="changepercent", asc=0, max_pages=5):
    """
    排行列表（hs_a 全市场，自动翻页）
    sort: changepercent / amount / volume / mktcap / turnoverratio
    asc: 0 降序（默认）
    单页上限 100 条，num 超过 100 时自动翻页直到取够或 max_pages 用尽
    """
    out, page = [], 1
    per = min(num, 100)
    try:
        while len(out) < num and page <= max_pages:
            items = _rank_page(sort, asc, page, per)
            if items is None:
                if page == 1:
                    log(f"新浪 rank_list({sort}) 第 1 页失败", "WARN")
                break
            if not items:
                break
            out += _norm_items(items)
            if len(items) < per:
                break
            page += 1
        out = out[:num]
        bj = sum(1 for it in out if (it.get("symbol") or "").startswith("bj"))
        if bj:
            log(f"  rank_list({sort}) 含 {bj}/{len(out)} 只北交所（上层过滤）", "INFO")
        return out
    except Exception as e:
        log(f"新浪 rank_list({sort}) 失败: {type(e).__name__}: {str(e)[:80]}", "WARN")
        return out


def _norm_items(items):
    out = []
    for it in items:
        out.append({
            "symbol": it.get("symbol"), "code": it.get("code"),
            "name": it.get("name"), "trade": it.get("trade"),
            "changepercent": it.get("changepercent"),
            "pricechange": it.get("pricechange"),
            "volume": it.get("volume"), "amount": it.get("amount"),
            "open": it.get("open"), "high": it.get("high"), "low": it.get("low"),
            "settlement": it.get("settlement"), "pe": it.get("per"),
            "pb": it.get("pb"), "mktcap": it.get("mktcap"), "nmc": it.get("nmc"),
            "turnoverratio": it.get("turnoverratio"),
        })
    return out


def changepercent_top(num=30, asc=0):
    """
    涨幅榜 / 跌幅榜 Top N
    asc=0 涨幅降序（默认）
    asc=1 跌幅降序
    """
    try:
        r = std_session().get(
            "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
            "Market_Center.getHQNodeData",
            params={"node": "hs_a", "sort": "changepercent", "asc": asc, "num": num},
            headers={"Referer": "https://finance.sina.com.cn/"},
            timeout=10,
        )
        if r.status_code != 200:
            log(f"新浪 changepercent_top HTTP {r.status_code}", "WARN")
            return []
        if len(r.text) < 100:
            log(f"新浪 changepercent_top 返回空（{len(r.text)}B，可能停盘）", "WARN")
            return []
        items = json.loads(r.text)
        if not items:
            log("新浪 changepercent_top 解析为空列表", "WARN")
            return []
        # 北交所统计
        bj_count = sum(1 for it in items if (it.get("symbol") or "").startswith("bj"))
        if bj_count:
            log(f"  涨幅榜含 {bj_count}/{len(items)} 只北交所股票（上层需过滤）", "INFO")
        out = []
        for it in items:
            out.append({
                "symbol": it.get("symbol"),
                "code": it.get("code"),
                "name": it.get("name"),
                "trade": it.get("trade"),
                "changepercent": it.get("changepercent"),
                "pricechange": it.get("pricechange"),
                "volume": it.get("volume"),          # 手
                "amount": it.get("amount"),          # 元
                "open": it.get("open"),
                "high": it.get("high"),
                "low": it.get("low"),
                "settlement": it.get("settlement"),  # 昨收
                "pe": it.get("per"),                  # 动态 PE
                "pb": it.get("pb"),
                "mktcap": it.get("mktcap"),          # 万
                "nmc": it.get("nmc"),                # 万（流通市值）
                "turnoverratio": it.get("turnoverratio"),
            })
        return out
    except Exception as e:
        log(f"新浪 changepercent_top 失败: {type(e).__name__}: {str(e)[:80]}", "WARN")
        return []


def hq(symbol):
    """
    单股 5 档行情
    symbol: 形如 sh600519 / sz000001 / bj920178
    """
    try:
        r = std_session().get(
            f"https://hq.sinajs.cn/list={symbol}",
            headers={"Referer": "https://finance.sina.com.cn/"},
            timeout=6,
        )
        if r.status_code != 200:
            log(f"新浪 hq {symbol} HTTP {r.status_code}", "WARN")
            return {"symbol": symbol, "error": f"status={r.status_code}"}
        # 停牌时新浪返回 var hq_str_xxx="";，body[0] 为空字符串
        parts = r.text.split('"')
        if len(parts) < 2 or not parts[1]:
            log(f"新浪 hq {symbol} 返回空字符串（停牌/无数据）", "WARN")
            return {"symbol": symbol, "error": "empty response（停牌？）"}
        body = parts[1].split(',')
        return {
            "symbol": symbol,
            "name": body[0],
            "open": float(body[1] or 0),
            "prev_close": float(body[2] or 0),
            "current": float(body[3] or 0),
            "high": float(body[4] or 0),
            "low": float(body[5] or 0),
            "volume": float(body[8] or 0),
            "amount": float(body[9] or 0),
        }
    except Exception as e:
        log(f"新浪 hq {symbol} 失败: {type(e).__name__}: {str(e)[:80]}", "WARN")
        return {"symbol": symbol, "error": str(e)[:80]}


def market_list(num=100, sort_field="changepercent", asc=0):
    """
    全市场列表（分页）
    sort_field: changepercent / amount / volume / mktcap
    """
    return changepercent_top(num=num, asc=asc)


def get(code):
    """便捷：传 A 股代码"""
    return hq(to_sina_symbol(code))