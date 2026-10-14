"""
风险股排除核查（重组股 + 事件类风险）
===============================
数据源：巨潮公告（scripts.feeds.announcements → sources/cninfo）

覆盖（全部自动判定）：
  1. 重组股：近 90 日「重大资产重组 / 借壳 / 控制权变更 / 要约收购」等
  2. 事件类：近 30 日「减持 / 立案 / 警示函 / 业绩预亏 / 商誉减值」等
  3. 基本面红线：质押率 > 60%、资产负债率 > 80% 且净利同比 < 0
     （雪球财务指标最新一期；取不到时记入 pending，**不当作通过**）
"""
import re

import webtool.stock.engine.feeds as cninfo

# ---- 基本面红线（雪球财务指标，取最新一期）----
PLEDGE_LIMIT = 60.0        # 质押率上限 %
DEBT_LIMIT = 80.0          # 资产负债率上限 %

# ---- 重组股（90 日窗口）----
RESTRUCTURE_KW = [
    "重大资产重组", "重大资产出售", "重大资产购买", "吸收合并", "换股吸收",
    "借壳", "要约收购", "收购报告书", "实际控制人变更", "控制权变更",
    "发行股份购买资产", "资产置换", "重整计划",
]

# ---- 事件类风险（30 日窗口）----
EVENT_KW = [
    "减持", "立案", "调查", "警示函", "监管函", "问询函",
    "业绩预亏", "业绩亏损", "商誉减值", "计提减值",
    "违规", "处罚", "退市风险",
]

# ---- 噪声标题（命中即豁免整条，避免把申报材料当风险）----
# 这几类是 IPO / 再融资 / 年报的**标准披露材料**，出现它们不代表当期出险：
#   「关于最近五年被证券监管部门和交易所采取监管措施或处罚情况的公告」→ 再融资申报附件
#   「审核问询函之回复」→ 发行审核常规程序（区别于「信息披露监管问询函」）
#   「吸收合并全资子公司」→ 内部架构调整，非重大资产重组
# 注意：「信息披露监管问询函」「控股股东减持」不属噪声，是真信号，照常命中。

NOISE_PATTERNS = [
    re.compile(r"最近五年.{0,20}(监管措施|处罚)"),
    re.compile(r"审核问询函"),
    re.compile(r"吸收合并全资子公司"),
    re.compile(r"保荐|申报稿|募集说明书|反馈意见回复"),
]

__all__ = ["scan", "scan_many", "RESTRUCTURE_KW", "EVENT_KW"]


def _titles(code, days):
    """拉 N 天公告标题；返回 (titles|None, err|None)。空列表不是错误。"""
    try:
        items = cninfo.announcements(code, days=days) or []
    except Exception as e:                                    # noqa: BLE001
        return None, f"{type(e).__name__}: {e}"
    return [str(it.get("title") or "") for it in items], None


def _fundamentals(code):
    """
    拉最新一期财务指标做基本面红线核查。
    数据源：雪球财务指标（clients.financials → stock_indicators）
    返回 (hit_list, err|None)；拉不到时 err 非空，调用方须标 pending 而非放行。
    """
    from webtool.stock.engine import clients as C

    try:
        r = C.financials(code)
    except Exception as e:                                    # noqa: BLE001
        return [], f"{type(e).__name__}: {e}"

    if not r.get("ok"):
        return [], str(r.get("error") or "财务指标接口失败")[:80]

    items = ((r.get("data") or {}).get("items") or [])
    if not items:
        return [], "财务指标为空"

    # 取最新一期（items[0] 为最新报告期）
    f = items[0]
    pledge = f.get("pledge_ratio")
    debt = f.get("asset_liab_ratio")
    np_yoy = f.get("net_profit_atsopc_yoy")
    period = f.get("report_date") or "最新期"

    hits = []
    if isinstance(pledge, (int, float)) and pledge > PLEDGE_LIMIT:
        hits.append({"type": "基本面", "keyword": f"质押率 {pledge:.1f}% > {PLEDGE_LIMIT:g}%",
                     "title": f"{period} 质押率 {pledge:.1f}%"})
    if (isinstance(debt, (int, float)) and debt > DEBT_LIMIT
            and isinstance(np_yoy, (int, float)) and np_yoy < 0):
        hits.append({"type": "基本面",
                     "keyword": f"资产负债率 {debt:.1f}% > {DEBT_LIMIT:g}% 且净利同比 {np_yoy:.1f}%",
                     "title": f"{period} 资产负债率 {debt:.1f}% / 净利同比 {np_yoy:.1f}%"})
    return hits, None


def scan(code, name=None, restructure_days=90, event_days=30):
    """
    核查单只股票的风险排除项。

    返回:
      {
        code, name,
        hit:   [{type, keyword, title}],     # 命中即排除
        clean: bool,                          # 是否无命中
        pending: [str],                       # 无法自动判定、需人工的项
        err: str|None                         # 数据拉取失败时非空
      }
    """
    res = {"code": code, "name": name, "hit": [], "pending": [], "err": None}

    # 一次拉 90 天，覆盖重组（90 日）与事件（30 日）两个窗口
    titles, err = _titles(code, max(restructure_days, event_days))
    if err:
        res["err"] = f"公告拉取失败：{err}"
    else:
        seen = set()
        for title in titles:
            # 申报材料 / 程序性披露属噪声，整条豁免
            if any(p.search(title) for p in NOISE_PATTERNS):
                continue
            for kw in RESTRUCTURE_KW:
                if kw in title and (kw, title) not in seen:
                    seen.add((kw, title))
                    res["hit"].append({"type": "重组股", "keyword": kw,
                                       "title": title[:80]})
            for kw in EVENT_KW:
                if kw in title and (kw, title) not in seen:
                    seen.add((kw, title))
                    res["hit"].append({"type": "事件风险", "keyword": kw,
                                       "title": title[:80]})

    # 基本面红线（质押率 / 资产负债率）
    fhit, ferr = _fundamentals(code)
    res["hit"] += fhit
    if ferr:
        res["pending"].append(f"基本面红线未核查（{ferr}）")

    res["clean"] = not res["hit"]
    return res


def scan_many(codes):
    """批量核查，返回 {code: scan 结果}"""
    out = {}
    for c in codes:
        out[c] = scan(c)
    return out


if __name__ == "__main__":
    import json
    import sys

    args = sys.argv[1:]
    if not args:
        print("用法: python3 -m scripts.screening.risk_check <代码> [代码...]")
        raise SystemExit(1)
    print(json.dumps(scan_many(args), ensure_ascii=False, indent=2))
