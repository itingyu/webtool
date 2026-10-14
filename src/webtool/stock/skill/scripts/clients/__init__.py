"""
数据层单点入口（clients）
=========================
所有数据获取的**唯一入口**。工作流一律调这里，不直接调 `fetchers.*`，
改调这里 —— 这样数据源切换、fallback、单位统一只在一处维护。

设计原则：
  1. 每个函数返回**统一结构**（dict / list[dict]），字段名固定
  2. 多源自动 fallback，全部失败返回 `{"ok": False, "err": ...}`，绝不抛异常
  3. 单位统一：市值 = 亿元，金额 = 亿元，成交量 = 手
  4. 数据缺失标 `None` 或显式 `status`，**不填 0**
"""
import json
import subprocess
import urllib.parse
import urllib.request

from webtool.stock.skill.scripts._common import log

UA = "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/126 Mobile Safari/537.36"


# ============ 基础 HTTP ============

def _http(url, timeout=12, encoding="utf-8", headers=None):
    from webtool.stock.bridge._stockmaster_net import get_opener
    req = urllib.request.Request(url, headers=headers or {"User-Agent": UA,
                                                          "Referer": "https://quote.eastmoney.com/"})
    with get_opener(url).open(req, timeout=timeout) as r:
        return r.read().decode(encoding, errors="ignore")


def _num(v, default=None):
    try:
        f = float(v)
        return f
    except (TypeError, ValueError):
        return default


# ============ 行情（腾讯主源 → 雪球 → 东财）============

IDX = {
    "上证指数": "sh000001", "上证": "sh000001", "上证50": "sh000016",
    "深证成指": "sz399001", "创业板指": "sz399006", "科创50": "sh000688",
    "沪深300": "sh000300", "中证500": "sh000905", "中证1000": "sh000852",
    "北证50": "bj899050", "国证2000": "sz399303",
}
IDX_NUM = {"000300": "sh000300", "000905": "sh000905", "000852": "sh000852",
           "000688": "sh000688", "000016": "sh000016", "899050": "bj899050"}

# 腾讯行情字段索引（0-based）—— 每次改动必须用「涨停价 == 昨收×1.1」断言自证
TF = {"现价": 3, "昨收": 4, "今开": 5, "成交量手": 6, "时间": 30, "涨跌": 31,
      "涨跌幅": 32, "最高": 33, "最低": 34, "成交额万": 37, "换手": 38,
      "PE动": 39, "振幅": 43, "流通市值": 44, "总市值": 45, "PB": 46,
      "涨停价": 47, "跌停价": 48, "量比": 49, "均价": 51}


def to_symbol(code):
    """标准化为 sh/sz/bj + 6 位；指数别名与指数号自动映射（避免 000001 歧义）"""
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


def quote(codes):
    """实时行情。codes: 代码 / 指数别名 / 带前缀代码（可混用）。返回 list[dict]"""
    if isinstance(codes, str):
        codes = [codes]
    syms = [to_symbol(c) for c in codes]
    out = []
    try:
        txt = _http("https://qt.gtimg.cn/q=" + ",".join(syms), encoding="gbk")
        for line in txt.strip().split(";"):
            if "=" not in line:
                continue
            body = line.split('="', 1)
            if len(body) < 2:
                continue
            sym = body[0].replace("v_", "").strip()
            f = body[1].rstrip('"').split("~")
            if len(f) < 55 or not f[TF["现价"]]:
                continue
            p, pc = _num(f[TF["现价"]]), _num(f[TF["涨跌幅"]])
            zt = _num(f[TF["涨停价"]])
            out.append({
                "input": sym[2:], "symbol": sym, "ok": True, "源": "tencent",
                "name": f[1], "现价": p, "昨收": _num(f[TF["昨收"]]),
                "今开": _num(f[TF["今开"]]), "涨跌幅": pc, "涨跌": _num(f[TF["涨跌"]]),
                "最高": _num(f[TF["最高"]]), "最低": _num(f[TF["最低"]]),
                "涨停价": zt, "跌停价": _num(f[TF["跌停价"]]),
                "距涨停%": round((zt / p - 1) * 100, 2) if (p and zt) else None,
                "换手%": _num(f[TF["换手"]]), "量比": _num(f[TF["量比"]]),
                "振幅%": _num(f[TF["振幅"]]),
                "流通市值亿": _num(f[TF["流通市值"]]), "总市值亿": _num(f[TF["总市值"]]),
                "PB": _num(f[TF["PB"]]), "PE动": _num(f[TF["PE动"]]),
                "成交额万": _num(f[TF["成交额万"]]), "行情时间": f[TF["时间"]],
            })
    except Exception as e:                                  # noqa: BLE001
        log(f"tencent quote 失败: {type(e).__name__}: {e}", level="WARN")
    got = {r["symbol"] for r in out}
    for s, c in zip(syms, codes):
        if s not in got:
            out.append({"input": c, "symbol": s, "ok": False,
                        "err": "无返回（代码错误 / 停牌 / 指数别名未覆盖）"})
    return out


# ============ 涨停池（东财）============

def limit_up_pool(date=None):
    """涨停池。含连板数 / 首封时间 / 炸板次数 / 封单 / 行业"""
    if date in (None, "last"):
        date = prev_trading_day()
        if not date:
            return {"ok": False, "error": "无法确定上一交易日（节假日表缺失？）"}
    d = str(date).replace("-", "")
    url = ("https://push2ex.eastmoney.com/getTopicZTPool?ut=7eea3edcaed734bea9cbfc24409ed989"
           f"&dpt=wz.ztzt&Pageindex=0&pagesize=300&sort=fbt:asc&date={d}")
    try:
        js = json.loads(_http(url))
        data = (js.get("data") or {}).get("pool") or []
    except Exception as e:                                  # noqa: BLE001
        return {"ok": False, "err": f"涨停池接口失败 {type(e).__name__}: {e}", "date": d}
    rows = []
    for it in data:
        zt = it.get("zttj") or {}
        fbt = str(it.get("fbt", "")).zfill(6)
        rows.append({
            "code": str(it.get("c", "")), "name": it.get("n"), "行业": it.get("hybk"),
            "涨跌幅": round(_num(it.get("zdp"), 0), 2),
            "连板": it.get("lbc") or 1,
            "涨停统计": f"{zt.get('days','')}天{zt.get('ct','')}板",
            "首封": f"{fbt[:2]}:{fbt[2:4]}:{fbt[4:6]}" if len(fbt) == 6 else fbt,
            "炸板次数": it.get("zbc"),
            "封单亿": round(_num(it.get("fund"), 0) / 1e8, 2),
            "换手%": round(_num(it.get("hs"), 0), 2),
            "流通市值亿": round(_num(it.get("ltsz"), 0) / 1e8, 2),
        })
    return {"ok": True, "date": d, "count": len(rows), "rows": rows}


# ============ 交易日历 ============

def _holidays(year):
    p = f"/var/minis/shared/短线复盘/holidays-{year}.json"
    try:
        with open(p, encoding="utf-8") as fh:
            return {x["date"] for x in json.load(fh).get("non_trading", [])}
    except Exception:                                       # noqa: BLE001
        log(f"节假日表缺失 {p}，仅按周末判断", level="WARN")
        return set()


def is_trading_day(d):
    return d.weekday() < 5 and d.strftime("%Y-%m-%d") not in _holidays(d.year)


def prev_trading_day(date=None):
    """上一个交易日。找不到（15 天内全是非交易日）时返回 None，调用方须判空"""
    from datetime import datetime, timedelta
    d = datetime.strptime(str(date), "%Y-%m-%d") if date else datetime.now()
    for _ in range(15):
        d -= timedelta(days=1)
        if is_trading_day(d):
            return d.strftime("%Y-%m-%d")
    return None


# ============ 数据接口桥（财务 / 公告 / 新闻 / 资金流）============

def mcp(tool, **kwargs):
    """调用 stock 动作, 返回解析后的 dict

    进程内一次函数调用: 直接落到 `bridge/srv.py` → `bridge/orchestrate.py`,
    不起子进程、不走协议、不套信封。返回形状固定 (dict), 下面的
    announcements/news/financials/capital_flow 及所有调用方都按 `ok`/`data` 取。
    """
    try:
        from webtool.stock.bridge import srv
        res = srv.call(tool, kwargs)
        if isinstance(res, str):
            # 服务端少数工具返回原始 text 而非 JSON
            try:
                return json.loads(res)
            except Exception:                               # noqa: BLE001
                return {"ok": False, "err": f"{tool} 返回非 JSON: {res[:80]}"}
        return res
    except Exception as e:                                  # noqa: BLE001
        log(f"stock {tool} 失败: {type(e).__name__}: {e}", level="WARN")
        return {"ok": False, "err": f"{type(e).__name__}: {e}"}


def announcements(code, page_size=10):
    return mcp("stock_announcement", symbol=code, page_size=page_size)


def news(code):
    return mcp("stock_news", symbol=code)


def financials(code):
    return mcp("stock_indicators", symbol=code)


def capital_flow(scope="industry"):
    """资金流。北向 status=3 = 数据不可用，调用方必须显式标注，不得当 0"""
    r = mcp("stock_capital_flow", scope=scope)
    if scope == "north" and r.get("ok"):
        d = (r.get("data") or {}).get("data") or {}
        bad = [k for k, v in d.items() if isinstance(v, dict) and v.get("status") == 3]
        if bad:
            r["unavailable"] = bad
            r["note"] = "北向 status=3：数据不可用，禁止当 0 使用"
    return r


# ============ 网页搜索（消息面 / 黑天鹅扫描）============

def web_search(query, max_n=8):
    """走 webtool 搜索管线 (Bing/搜狗/百度), 返回 [{title,url,snippet}]

    直调 `webtool.cli.app.main(['search', ...])` —— 不起 `webtool` 子进程,
    省掉一次解释器启动与配置加载。

    刻意走 `cli.app.main()` 而不是直接调 `pipeline.search.do_search`:
    后者要一个 29 字段的 args 对象, 自己拼等于在 skill 侧复制一份 CLI 契约,
    之后 CLI 加参数这里就静默漂移 (拿不到新选项, 也不会报错)。

    实现说明: webtool 运行时会在 `bridge/master.py::_patch_inproc` 把本函数
    覆盖成同一条实现。这里保留的版本是**独立可用**的兜底 (skill 被单独拿出来
    跑时没有那层注入), 产物形状与补丁版一致: `{"ok","query","results"}`。
    """
    import contextlib
    import io as _io
    buf = _io.StringIO()
    try:
        from webtool.cli.app import main
        with contextlib.redirect_stdout(buf):
            rc = main(['search', query, '-n', str(max_n), '-f', 'json'])
        out = json.loads(buf.getvalue() or '{}')
        return {"ok": rc == 0 and bool(out.get('results')),
                "query": query, "results": out.get('results', [])}
    except Exception as e:                                  # noqa: BLE001
        log(f"webtool 搜索失败: {type(e).__name__}: {e}", level="WARN")
        return {"ok": False, "query": query, "err": str(e), "results": []}


# ============ 不可买板块 ============
# 唯一实现在 scripts/_common.unbuyable_reason()，此处仅转发，避免第三份拷贝。


def code_ok(code, name=None):
    """返回 (是否可买, 说明)。判定逻辑见 _common.unbuyable_reason()。"""
    from webtool.stock.skill.scripts._common import unbuyable_reason
    reason = unbuyable_reason(code, name)
    if reason:
        return False, reason
    c = str(code).strip().upper()
    if c.startswith(("SH", "SZ", "BJ")):
        c = c[2:]
    c = c.zfill(6)
    return True, "沪市主板" if c.startswith("6") else "深市主板"
