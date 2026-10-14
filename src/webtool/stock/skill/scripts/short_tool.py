#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
短线工具包 · short_tool.py
=========================
stock-master skill 的命令行工具层（短选 / 打板 / 日常行情）。
仅用标准库（urllib），无第三方依赖。

用法：
  python3 short_tool.py quote 600121 000001        # 行情（含涨停/跌停/量比/换手）
  python3 short_tool.py check 600121 600519        # 可买入性预检（含 8 项闸门）
  python3 short_tool.py filter 300913 688559 600121 002068
  python3 short_tool.py pool --date 20261009       # 涨停池（东财，含连板/封单/行业）
  python3 short_tool.py pool --date last --only-buy         # 只要主板可买
  python3 short_tool.py calendar                   # 交易日判断 + 上/下交易日
  python3 short_tool.py calendar --date 20261009
  python3 short_tool.py header --mode pre          # 输出标准表头（纪律卡片+声明）

新增/修改接口后务必先跑 `check` 自测字段，再改上层 SOP。
"""
import json
import argparse
import urllib.request
from datetime import datetime, timedelta

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

# ---- 腾讯行情字段索引（0-based，实测校验：600519 茅台 + 600121 郑州煤电）----
# 校验法：涨停价 == 昨收×1.1、换手 == 成交量÷流通股本、振幅 == (高-低)÷昨收
F = {
    "现价": 3, "昨收": 4, "今开": 5, "成交量手": 6,
    "时间": 30, "涨跌": 31, "涨跌幅": 32, "最高": 33, "最低": 34,
    "成交额万": 37, "换手": 38, "PE动": 39,
    "振幅": 43, "流通市值": 44, "总市值": 45, "PB": 46,
    "涨停价": 47, "跌停价": 48, "量比": 49, "均价": 51,
}

# ---- 不可买板块硬过滤 ----
# 唯一口径在 scripts/_common.py: unbuyable_reason()。
# 本文件保持零依赖：优先调用 _common，缺席时用下面这张表兜底（两处必须同步）。
try:
    from webtool.stock.skill.scripts._common import unbuyable_reason as _unbuyable
except Exception:                                              # noqa: BLE001
    _unbuyable = None

BLOCK = ("300", "301", "688", "689", "8", "920", "430", "900", "200")
BLOCK_NAME = {"300": "创业板", "301": "创业板", "688": "科创板", "689": "科创板",
              "8": "北交所", "920": "北交所", "430": "北交所",
              "900": "沪市B股", "200": "深市B股"}


def _get(url, encoding="utf-8", timeout=15):
    from webtool.stock.bridge._stockmaster_net import get_opener
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with get_opener(url).open(req, timeout=timeout) as r:
        return r.read().decode(encoding, errors="replace")


def _f(x, d=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return d


# ---- 指数别名（避免 000001/000300 这类与个股同号的歧义）----
IDX = {
    "上证指数": "sh000001", "上证": "sh000001", "上证50": "sh000016",
    "深证成指": "sz399001", "创业板指": "sz399006", "科创50": "sh000688",
    "沪深300": "sh000300", "中证500": "sh000905", "中证1000": "sh000852",
    "北证50": "bj899050", "国证2000": "sz399303",
}
IDX_NUM = {"000300": "sh000300", "000905": "sh000905", "000852": "sh000852",
           "000688": "sh000688", "000016": "sh000016", "899050": "bj899050"}


def _norm(code):
    """标准化为 sh/sz/bj + 6 位；显式前缀优先，中文别名与指数号自动映射"""
    s = str(code).lower().strip()
    if s in IDX:
        return IDX[s]
    if s[:2] in ("sh", "sz", "bj"):
        return s
    if s in IDX_NUM:
        return IDX_NUM[s]
    c = s
    if c.startswith(("6", "9")):
        return "sh" + c
    if c.startswith(("0", "2", "3")):
        return "sz" + c
    if c.startswith(("4", "8")):
        return "bj" + c
    return "sh" + c


def code_ok(code, name=None, mode=None):
    """不可买板块硬过滤（创业板 / 科创板 / 北交所 / B 股 / ST 均不可买）"""
    if _unbuyable:
        reason = _unbuyable(code, name)
        if reason:
            return False, reason
        c = str(code).strip().upper()
        if c.startswith(("SH", "SZ", "BJ")):
            c = c[2:]
        c = c.zfill(6)
        return True, "沪市主板" if c.startswith("6") else "深市主板"
    c = str(code).lower().replace("sh", "").replace("sz", "").replace("bj", "").strip()
    if not (c[:1].isdigit() and len(c) >= 6):
        return False, "非数字代码（ST 等风险警示）"
    for p in BLOCK:
        if c.startswith(p):
            return False, f"{BLOCK_NAME[p]} {p} 不可买"
    if c.startswith(("600", "601", "603", "605")):
        return True, "沪市主板"
    if c.startswith(("000", "001", "002", "003")):
        return True, "深市主板"
    return False, "未知前缀，默认排除"


# ---------------- quote ----------------
def quote(codes):
    out = []
    for code in codes:
        sym = _norm(code)
        try:
            raw = _get(f"https://qt.gtimg.cn/q={sym}", encoding="gbk")
        except Exception as e:
            out.append({"input": code, "ok": False, "err": f"网络失败 {e}"})
            continue
        if '="' not in raw or "~" not in raw:
            out.append({"input": code, "ok": False, "err": "无返回（代码错误或停牌）"})
            continue
        f = raw.split('="', 1)[1].rstrip('";\n').split("~")
        if len(f) < 49 or not f[F["现价"]]:
            out.append({"input": code, "ok": False, "err": "字段不足/停牌"})
            continue
        price = _f(f[F["现价"]])
        zt, dt = _f(f[F["涨停价"]]), _f(f[F["跌停价"]])
        up, down = _f(f[F["最高"]]), _f(f[F["最低"]])
        rec = {
            "input": code, "ok": True, "symbol": sym, "name": f[1],
            "现价": price, "昨收": _f(f[F["昨收"]]), "今开": _f(f[F["今开"]]),
            "涨跌幅": _f(f[F["涨跌幅"]]), "最高": up, "最低": down,
            "涨停价": zt, "跌停价": dt,
            "距涨停%": round((zt - price) / price * 100, 2) if price else None,
            "换手%": _f(f[F["换手"]]), "量比": _f(f[F["量比"]]),
            "振幅%": _f(f[F["振幅"]]),
            "流通市值亿": _f(f[F["流通市值"]]), "总市值亿": _f(f[F["总市值"]]),
            "PB": _f(f[F["PB"]]), "PE动": _f(f[F["PE动"]]),
            "成交额万": _f(f[F["成交额万"]]),
            "行情时间": f[F["时间"]],
        }
        risk, why = code_ok(code)
        rec["权限"] = ("✅ " + why) if risk else ("❌ " + why)
        out.append(rec)
    return out


# ---------------- filter（纯代码板过滤，不打行情）----------------
def filter(codes):
    """只按代码前缀做可买性过滤，不请求行情（快、可离线）"""
    return [{"code": c, "通过": code_ok(c)[0], "板块": code_ok(c)[1]}
            for c in codes]

# ---------------- check（权限关 + 8 项闸门 + 三档结论）----------------
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
        if zt <= 0 or not r["今开"]:
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


# ---------------- pool（东财涨停池）----------------
def pool(date=None, mode="all"):
    if date in (None, "last", "prev"):
        date = calendar()["上一交易日"]      # 非交易日/盘前默认用上一交易日
    d = str(date).replace("-", "")
    if len(d) != 8:
        return {"ok": False, "err": f"日期格式应为 YYYYMMDD 或 YYYY-MM-DD，收到 {date}"}
    url = ("https://push2ex.eastmoney.com/getTopicZTPool?ut=7eea3edcaed734bea9cbfc24409ed989"
           f"&dpt=wz.ztzt&Pageindex=0&pagesize=300&sort=fbt:asc&date={d}")
    try:
        js = json.loads(_get(url))
    except Exception as e:
        return {"ok": False, "err": f"接口失败 {e}", "date": d}
    dd = js.get("data") or {}
    # 东财会忽略无效日期：请求 20261011 也返回 20261009 的数据。
    # 必须用响应里的 qdate 作为真实数据日期，并对不上时告警，否则会拿旧数据当今天。
    data_date = str(dd.get("qdate") or d)
    mismatch = data_date != d
    data = dd.get("pool") or []
    if not data:
        warn = ("非交易日或当日无数据（请求 %s，返回 qdate=%s）；"
                "若确为交易日，可能是接口限流或日期超出可查范围" % (d, data_date))
        return {"ok": True, "date": data_date, "请求日期": d,
                "日期回退": f"接口返回 {data_date}，与请求 {d} 不符" if mismatch else None,
                "涨停总数": 0,
                "主板可买数": 0, "主板可买占比": "—", "连板梯队": {},
                "shown": 0, "rows": [], "warning": warn}
    rows = []
    for it in data:
        code = str(it.get("c", ""))
        nm = it.get("n")
        perm, why = code_ok(code, nm)     # 必须传名称，否则 ST 只能靠代码段识别
        zttj = it.get("zttj") or {}
        lbc = it.get("lbc") or 1
        fbt = str(it.get("fbt", "")).zfill(6)
        rows.append({
            "code": code, "name": nm, "行业": it.get("hybk"),
            "涨跌幅": round(_f(it.get("zdp")), 2),
            "连板": lbc, "涨停统计": f"{zttj.get('days','')}天{zttj.get('ct','')}板",
            "首封": f"{fbt[:2]}:{fbt[2:4]}:{fbt[4:6]}" if len(fbt) == 6 else fbt,
            "炸板次数": it.get("zbc"),
            "封单亿": round(_f(it.get("fund")) / 1e8, 2),
            "换手%": round(_f(it.get("hs")), 2),
            "流通市值亿": round(_f(it.get("ltsz")) / 1e8, 2),
            "可买": "✅" if perm else "❌",
            "剔除原因": "" if perm else why,
        })
    # 排序：连板数 → 首封时间
    rows.sort(key=lambda x: (x["连板"], x["首封"]))
    total_zt = len(data)
    total_buy = sum(1 for r in rows if r["可买"] == "✅")
    if mode == "buy":
        rows = [r for r in rows if r["可买"] == "✅"]
    tiers = {}
    for r in rows:
        tiers[r["连板"]] = tiers.get(r["连板"], 0) + 1
    return {"ok": True, "date": data_date, "请求日期": d,
            "日期回退": f"接口返回 {data_date}，与请求 {d} 不符" if mismatch else None,
            "涨停总数": total_zt, "主板可买数": total_buy,
            "主板可买占比": f"{total_buy / total_zt * 100:.0f}%" if total_zt else "0%",
            "连板梯队": dict(sorted(tiers.items())),
            "shown": len(rows), "rows": rows}


# ---------------- calendar ----------------
def _holidays(year):
    """读取本地节假日缓存；缺则返回空并提示"""
    p = "/var/minis/shared/短线复盘/holidays-%d.json" % year
    try:
        with open(p, encoding="utf-8") as fh:
            js = json.load(fh)
        return {x["date"] for x in js.get("non_trading", [])}
    except Exception:
        return set()


def is_trading_day(d):
    return d.weekday() < 5 and d.strftime("%Y-%m-%d") not in _holidays(d.year)


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


# ---------------- header ----------------
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


# ---------------- main ----------------
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
