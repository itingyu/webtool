#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
短线工具包 · engine/short_tool.py
===============================
短选 / 打板 / 日常行情的**业务口径层**（可买性闸门、连板梯队、纪律卡片）。

取数一律经 `engine/clients`（再往下是 `bridge/sources`），本模块不发 HTTP、
不解析任何原始行情串 —— 字段索引表与端点地址都归数据源层。

口径纪律：
  - 不可买板块判定唯一实现是 `_common.unbuyable_reason()`（创业板/科创板/
    北交所/B 股/ST 一票否决），本模块不自带前缀表
  - 涨停池必带真实数据日（接口对无效日期静默回旧数据）

用法（调试用；正常入口是 `webtool stock *`）：
  python3 -m webtool.stock.engine.short_tool quote 600121 000001
  python3 -m webtool.stock.engine.short_tool check 600121 600519
  python3 -m webtool.stock.engine.short_tool pool --date last --only-buy
  python3 -m webtool.stock.engine.short_tool calendar
  python3 -m webtool.stock.engine.short_tool header --mode pre
"""
import json
import argparse
from datetime import datetime, timedelta

from webtool.stock.engine import clients as C
from webtool.stock.engine._common import unbuyable_reason

# 数据源层的腾讯富字段行情由 clients.quote 负责；这里只留业务侧需要的别名表，
# 指数别名/前缀归一的实现都在 clients.to_symbol → sources/_symbol。
_norm = C.to_symbol


def code_ok(code, name=None, mode=None):
    """不可买板块硬过滤（创业板 / 科创板 / 北交所 / B 股 / ST 均不可买）

    返回 (是否可买, 说明)。判定委托 `_common.unbuyable_reason()` —— 全仓唯一
    口径，本函数只负责把它翻成 (bool, 板块名) 的形态。
    """
    reason = unbuyable_reason(code, name)
    if reason:
        return False, reason
    c = str(code).strip().upper()
    if c.startswith(("SH", "SZ", "BJ")):
        c = c[2:]
    c = c.zfill(6)
    return True, "沪市主板" if c.startswith("6") else "深市主板"


# quote
def quote(codes):
    return C.quote(codes)


# filter（纯代码板过滤，不打行情）
def filter(codes):
    """只按代码前缀做可买性过滤，不请求行情（快、可离线）"""
    return [{"code": c, "通过": code_ok(c)[0], "板块": code_ok(c)[1]}
            for c in codes]


# check（权限关 + 8 项闸门 + 三档结论）
def check(codes):
    """可买入性预检：先过权限关（不可买板块/ST 一票否决），再过 8 项盘口闸门。"""
    rows = []
    for r in quote(codes):
        if not r.get("ok"):
            rows.append(r)
            continue
        # 权限判定必须最先做：ST/退市整理、创业板等不能因「像指数/无涨跌停」而漏判
        okperm, why = code_ok(r["input"], r.get("name"))
        r["权限"] = ("✅ " + why) if okperm else ("❌ " + why)
        if not okperm:
            r["结论"] = "❌ 删除（权限）"
            rows.append(r)
            continue
        p, pc = r["现价"], r["涨跌幅"]
        zt = r["涨停价"]
        if not zt or zt <= 0 or not r["今开"]:
            r["结论"] = "— 指数/无涨跌停，跳过可买入性检查"
            rows.append(r)
            continue
        dt = r["跌停价"]
        op = r["今开"]
        gates = {
            "1_未封涨停": not (p >= zt - 0.001),
            "2_未封跌停": not (p <= dt + 0.001),
            "3_非一字板": not (op >= zt - 0.001 and p >= zt - 0.001),
            "4_非一字跌停": not (op <= dt + 0.001 and p <= dt + 0.001),
            "5_距涨停空间≥3%": (r["距涨停%"] or 0) >= 3,
            "6_量比≥0.8": (r["量比"] or 0) >= 0.8,
            "7_换手0.5-25%": 0.5 <= (r["换手%"] or 0) <= 25,
            "8_流通市值≥50亿": (r["流通市值亿"] or 0) >= 50,
        }
        hard = all(gates[k] for k in ("1_未封涨停", "2_未封跌停", "3_非一字板",
                                      "4_非一字跌停", "5_距涨停空间≥3%"))
        r["闸门"] = gates
        if not hard:
            r["结论"] = "❌ 删除（买不到/无空间）"
        elif 5 <= pc <= 9.5:
            r["结论"] = "✅ 可追（温和区 5-9.5%）"
        elif 0 < pc < 5:
            r["结论"] = "⚠️ 降观察（涨幅<5%，需资金承接）"
        else:
            r["结论"] = "⚠️ 降观察（弱势/回落）"
        if r["结论"].startswith(("✅", "⚠")) and not all(gates.values()):
            bad = [k for k, v in gates.items() if not v]
            r["结论"] += " ｜软项不达标：" + "、".join(bad)
        rows.append(r)
    return rows


# pool（东财涨停池 + 连板梯队 + 可买统计）
def pool(date=None, mode="all"):
    """涨停池。date=None/last/prev = 上一交易日；mode='buy' 只留可买

    取数在 `clients.limit_up_pool`（→ sources.em_zt_pool），本层只做业务加工：
    逐只标可买/剔除原因、算连板梯队与主板可买占比。
    """
    if date not in (None, "last", "prev"):
        d = str(date).replace("-", "")
        if len(d) != 8:
            return {"ok": False, "err": f"日期格式应为 YYYYMMDD 或 YYYY-MM-DD，收到 {date}"}
    r = C.limit_up_pool(date)
    if not r.get("ok"):
        return r
    rows = []
    for it in r.get("rows") or []:
        perm, why = code_ok(it.get("code"), it.get("name"))
        row = dict(it)
        row["可买"] = "✅" if perm else "❌"
        row["剔除原因"] = "" if perm else why
        rows.append(row)
    # 排序：连板数 → 首封时间
    rows.sort(key=lambda x: (x.get("连板") or 0, x.get("首封") or ""))
    total_zt = len(rows)
    total_buy = sum(1 for x in rows if x["可买"] == "✅")
    if mode == "buy":
        rows = [x for x in rows if x["可买"] == "✅"]
    tiers = {}
    for x in rows:
        t = x.get("连板") or 0
        tiers[t] = tiers.get(t, 0) + 1
    if not total_zt:
        return {**r, "涨停总数": 0, "主板可买数": 0, "主板可买占比": "—",
                "连板梯队": {}, "shown": 0, "rows": [],
                "warning": (f"非交易日或当日无数据（请求 {r.get('请求日期')}，"
                            f"返回 qdate={r.get('date')}）")}
    return {**r, "涨停总数": total_zt, "主板可买数": total_buy,
            "主板可买占比": f"{total_buy / total_zt * 100:.0f}%",
            "连板梯队": dict(sorted(tiers.items())),
            "shown": len(rows), "rows": rows}


# calendar
def _holidays(year):
    return C._holidays(year)


def is_trading_day(d):
    return C.is_trading_day(d)


def calendar(date=None, n=3):
    if date:
        s = str(date).replace("-", "")
        base = datetime(int(s[:4]), int(s[4:6]), int(s[6:8]))
    else:
        base = datetime.now()
    prev, nxt = [], []
    d = base - timedelta(days=1)
    while len(prev) < n:
        if is_trading_day(d):
            prev.append(d.strftime("%Y-%m-%d"))
        d -= timedelta(days=1)
    d = base + timedelta(days=1)
    while len(nxt) < n:
        if is_trading_day(d):
            nxt.append(d.strftime("%Y-%m-%d"))
        d += timedelta(days=1)
    return {
        "今天": base.strftime("%Y-%m-%d %A"),
        "是否交易日": is_trading_day(base),
        "上一交易日": prev[0], "下一交易日": nxt[0],
        "近期": {"上": prev, "下": nxt},
        "节假日表": "已加载" if _holidays(base.year) else "缺失（需补 holidays-%d.json）" % base.year,
    }


# header
CARDS = {
    "screener": """D1 涨停买不到,一字板必删。
D2 止损 -7% 不调整,目标可上调不下移。
D3 单票仓位 ≤ 10%,持仓 ≤ 3 只。
D4 不补仓,不摊薄,不心存侥幸。
D5 尾盘涨停的次日溢价显著低于早盘板,尾盘不做首仓。
D6 集合竞价高开 > 5% 不市价追,等回踩企稳或挂对手价。
D7 北向 status=3 时资金面维度写 ⚠️ 并跳过该项,禁止当 0 或占位打分。
D8 代码前缀硬过滤:300/301/688/8/920/900/200/ST 一律不碰。""",
    "limitup": """D1 涨停/一字板直接不挂单。
D2 09:30:00-09:30:30 是打板黄金 30 秒。
D3 单票 ≤ 5%,持仓 ≤ 2 只,日总仓 ≤ 10%。
D4 止损 -7% 不可调整,跌破 30 分钟未收回即出。
D5 看竞价定价、挂对手价;高开 >9.5% 删,5-9.5% 可挂。
D6 不补仓不摊薄,跌 7% 全出。
D7 尾盘板次日低开概率 40%,尾盘不做首仓。
D8 代码前缀硬过滤:300/301/688/8/920/900/200/ST 一律不碰。""",
}
STAGES = {"pre": "盘前", "intra": "盘中", "noon": "午休", "after": "盘后", "close": "盘后"}


def header(mode="pre", kind="screener", date=None):
    cal = calendar(date)
    d = cal["今天"][:10]
    stage = STAGES.get(mode, "盘中")
    line = f"# 短线候选清单 | {d} {stage}"
    if not cal["是否交易日"]:
        line = f"# 非交易日预案 | {d}（{stage}）"
    return "\n".join([
        line,
        "",
        "```", CARDS[kind], "```",
        "",
        "> ⚠️ A 股短线不存在稳定盈利股票，以下为公开信息研究，不构成投资建议。",
        f"> 阶段：**{stage}** ｜ 上一交易日：{cal['上一交易日']} ｜ 下一交易日：{cal['下一交易日']}",
        f"> 数据时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}（所有行情须现拉，禁用缓存）",
    ])


# main
def main():
    ap = argparse.ArgumentParser(description="短线工具包")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("quote"); p.add_argument("codes", nargs="+")
    p = sub.add_parser("check"); p.add_argument("codes", nargs="+")
    p = sub.add_parser("filter"); p.add_argument("codes", nargs="+")
    p = sub.add_parser("pool"); p.add_argument("--date", default=None)
    p.add_argument("--only-buy", action="store_true", help="只输出主板可买")
    p = sub.add_parser("calendar"); p.add_argument("--date", default=None)
    p.add_argument("--n", type=int, default=3)
    p = sub.add_parser("header"); p.add_argument("--mode", default="pre")
    p.add_argument("--kind", default="screener", choices=["screener", "limitup"])
    p.add_argument("--date", default=None)

    a = ap.parse_args()
    if a.cmd == "quote":
        res = quote(a.codes)
    elif a.cmd == "check":
        res = check(a.codes)
    elif a.cmd == "filter":
        res = filter(a.codes)
    elif a.cmd == "pool":
        res = pool(a.date, "buy" if a.only_buy else "all")
    elif a.cmd == "calendar":
        res = calendar(a.date, a.n)
    else:
        print(header(a.mode, a.kind, a.date)); return
    print(json.dumps(res, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
