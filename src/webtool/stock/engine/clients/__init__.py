"""
数据层单点入口（engine/clients）
==============================
业务层取数的**唯一入口**。工作流不直接碰 `bridge/sources`，
改调这里 —— 数据源切换、字段形状、单位统一只在一处维护。

设计原则：
  1. 每个函数返回**统一结构**（dict / list[dict]），字段名固定
  2. 取数全部经 `bridge/sources` 的 `APIClient`（本模块**不发 HTTP**）
  3. 单位统一：市值 = 亿元，金额 = 亿元，成交量 = 手
  4. 数据缺失标 `None` 或显式 `status`，**不填 0**
  5. 代码归一只有一处事实来源：`sources/_symbol.py`

字段名保留中文（现价 / 涨跌幅 / 涨停价 …）：screening / analysis / short_tool
全部按这些键取值，改英文等于让十几个调用点跟着改，收益为零。
"""
import json
import os
import subprocess
from datetime import datetime, timedelta

from webtool.stock.engine._common import log
from webtool.stock.bridge.sources import _symbol

# 指数别名（避免 000001/000300 这类与个股同号的歧义）。
# 裸指数代码在 _symbol 里判不出市场（000001 是平安银行不是上证指数），
# 所以别名表必须在本层先过一遍，再交给 _symbol 定前缀。
IDX = {
    "上证指数": "sh000001", "上证": "sh000001", "上证50": "sh000016",
    "深证成指": "sz399001", "创业板指": "sz399006", "科创50": "sh000688",
    "沪深300": "sh000300", "中证500": "sh000905", "中证1000": "sh000852",
    "北证50": "bj899050", "国证2000": "sz399303",
}
IDX_NUM = {"000300": "sh000300", "000905": "sh000905", "000852": "sh000852",
           "000688": "sh000688", "000016": "sh000016", "899050": "bj899050"}


def to_symbol(code):
    """代码 / 指数别名 / 带前缀代码 → 腾讯形态 `sh600519`

    别名与指数号先查表，其余一律走 `_symbol.tencent` —— 前缀规则（含
    920xxx 北交所）只有那一处实现，本模块不再自带一份必然漂移的拷贝。

    `2414` 这种不足 6 位的输入先补零：`_symbol` 对它的判定是"不像 A 股代码"
    （4-5 位在雪球那边是港股），补零是**调用契约**的一部分，不是前缀规则。
    """
    s = str(code).strip()
    if s in IDX:
        return IDX[s]
    if s.lower() in IDX_NUM:
        return IDX_NUM[s.lower()]
    if not _symbol.parse(s):
        s = s.zfill(6)
    return _symbol.tencent(s)


# ============ 行情（腾讯富字段）============

def quote(codes):
    """实时行情。codes: 代码 / 指数别名 / 带前缀代码（可混用）。返回 list[dict]

    取数在 `sources.gtimg_quote_flat`（含涨跌停价/量比/换手/市值），本层只把
    字段名翻成业务契约的键名，并给每只补 `ok` / `err` —— 调用方按输入顺序
    逐只取，缺一只不影响其余。
    """
    if isinstance(codes, str):
        codes = [codes]
    syms = [to_symbol(c) for c in codes]
    r = _client().gtimg_quote_flat(syms)
    if not r.get("ok"):
        err = r.get("error") or "取数失败"
        return [{"input": c, "symbol": s, "ok": False, "err": err}
                for c, s in zip(codes, syms)]
    rows = {row["symbol"]: row for row in (r.get("data") or {}).get("rows") or []}
    out = []
    for c, s in zip(codes, syms):
        row = rows.get(s)
        if not row:
            out.append({"input": c, "symbol": s, "ok": False,
                        "err": "无返回（代码错误 / 停牌 / 指数别名未覆盖）"})
            continue
        out.append({
            "input": c, "symbol": s, "ok": True, "源": row.get("source"),
            "name": row.get("name"), "现价": row.get("current"),
            "昨收": row.get("prev_close"), "今开": row.get("open"),
            "涨跌幅": row.get("percent"), "涨跌": row.get("change"),
            "最高": row.get("high"), "最低": row.get("low"),
            "涨停价": row.get("limit_up"), "跌停价": row.get("limit_down"),
            "距涨停%": row.get("to_limit_pct"),
            "换手%": row.get("turnover_rate"), "量比": row.get("volume_ratio"),
            "振幅%": row.get("amplitude"),
            "流通市值亿": row.get("float_mktcap"),
            "总市值亿": row.get("total_mktcap"),
            "PB": row.get("pb"), "PE动": row.get("pe"),
            "成交额万": row.get("amount_wan"),
            "行情时间": row.get("quote_time"),
        })
    return out


# ============ 涨停池（东财）============

def limit_up_pool(date=None):
    """涨停池。含连板数 / 首封时间 / 炸板次数 / 封单 / 行业

    取数在 `sources.em_zt_pool`；这里补三件业务口径：
      - `date` 缺失时用上一交易日（不在数据源层做，那是业务默认值）
      - **数据日 = 请求日**：该接口的 `qdate` 恒等于"最近交易日"（同日请求
        20261009 也回 qdate=20261014），拿它当数据日会把旧池子标成今天
      - 空池时按交易日历定性：非交易日属正常，交易日空池要人工确认
    """
    if date in (None, "last", "prev"):
        date = prev_trading_day()
        if not date:
            return {"ok": False, "err": "无法确定上一交易日（节假日表缺失？）"}
    d = str(date).replace("-", "")
    r = _client().em_zt_pool(d)
    if not r.get("ok"):
        return {"ok": False, "err": r.get("error") or "涨停池取数失败", "date": d}
    dd = r.get("data") or {}
    rows = [{
        "code": it.get("code"), "name": it.get("name"), "行业": it.get("industry"),
        "涨跌幅": it.get("percent"), "连板": it.get("lbc"),
        "涨停统计": f"{it.get('days','')}天{it.get('boards','')}板",
        "首封": it.get("first_seal"), "炸板次数": it.get("break_count"),
        "封单亿": it.get("seal_fund"), "换手%": it.get("turnover_rate"),
        "流通市值亿": it.get("float_mktcap"),
    } for it in dd.get("rows") or []]
    note = None
    if not rows:
        if is_trading_day(d):
            note = (f"{d} 是交易日却返回空池 —— 可能尚未开盘/收盘快照未生成，"
                    f"或接口限流；换个日期或稍后重试")
        else:
            note = f"{d} 非交易日（节假日表），接口返回空池属正常"
    return {"ok": True, "date": d, "请求日期": d, "qdate": dd.get("qdate"),
            "提示": note, "count": len(rows), "rows": rows}


# ============ 客户端单例 ============

_CLIENT = None


def _client():
    """`sources.APIClient` 单例 —— 复用连接池、token 与 cookie 缓存

    与 `feeds.client()` 是同一份（都从 sources 拿），数据源层的 session
    全进程只有一份，这也是"数据源只有一套实现"的落点。
    """
    global _CLIENT
    if _CLIENT is None:
        from webtool.stock.bridge.sources import APIClient
        _CLIENT = APIClient()
    return _CLIENT


# ============ 交易日历 ============

# 交易日历随包分发 (stock/data/trading_calendar/holidays-<年>.json)。
# 曾经读项目外的 /var/minis/shared/短线复盘/holidays-YYYY.json —— 换台机器、
# 换个用户目录就没有, 而"节假日被当成交易日"的后果是把 10-01 之类的日期
# 交给接口, 涨跌停池对这种日期**静默回旧数据**, 报出来的错完全指不到日历。
_CAL_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "trading_calendar")
_HOLIDAYS = {}


def holidays_path(year):
    """内置节假日表路径 —— "数据在哪"的唯一答案 (测试与排错都问这里)"""
    return os.path.join(_CAL_DIR, f"holidays-{year}.json")


def _holidays(year):
    """该年的非交易日集合 (含法定假日与调休); 表缺失时返回空集并告警

    进程内缓存: 一次筛选会反复问"这天是不是交易日", 表却不会变。
    """
    if year in _HOLIDAYS:
        return _HOLIDAYS[year]
    p = holidays_path(year)
    try:
        with open(p, encoding="utf-8") as fh:
            days = {x["date"] for x in json.load(fh).get("non_trading", [])}
    except Exception as e:                                  # noqa: BLE001
        log(f"内置节假日表读不到 {p} ({type(e).__name__}: {e}), 仅按周末判断; "
            f"补该年日历后重试 (节假日当交易日会让涨停池静默回旧数据)",
            level="WARN")
        days = set()
    _HOLIDAYS[year] = days
    return days


def is_trading_day(d):
    """`d` 认 datetime / date / 'YYYY-MM-DD' / 'YYYYMMDD'"""
    if isinstance(d, str):
        d = datetime.strptime(d.replace("-", ""), "%Y%m%d")
    return d.weekday() < 5 and d.strftime("%Y-%m-%d") not in _holidays(d.year)


def prev_trading_day(date=None):
    """上一个交易日。找不到（15 天内全是非交易日）时返回 None，调用方须判空"""
    d = datetime.strptime(str(date), "%Y-%m-%d") if date else datetime.now()
    for _ in range(15):
        d -= timedelta(days=1)
        if is_trading_day(d):
            return d.strftime("%Y-%m-%d")
    return None


# ============ 数据接口桥（财务 / 公告 / 新闻 / 资金流）============

def mcp(tool, **kwargs):
    """调用编排层动作，返回解析后的 dict

    进程内一次函数调用（bridge.srv → orchestrate），不起子进程。返回形状固定
    (dict)，下面的 announcements/news/financials/capital_flow 及所有调用方都按
    `ok`/`data` 取。
    """
    try:
        from webtool.stock.bridge import srv
        res = srv.call(tool, kwargs)
        if isinstance(res, str):
            # 少数动作返回原始 text 而非 JSON
            try:
                return json.loads(res)
            except Exception:                              # noqa: BLE001
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
    """走 webtool（Bing/搜狗/百度），返回 [{title,url,snippet}]"""
    try:
        r = subprocess.run(["webtool", "search", query, "-n", str(max_n), "-f", "json"],
                           capture_output=True, text=True, timeout=90)
        js = json.loads(r.stdout or "{}")
        return {"ok": True, "query": query, "results": js.get("results", [])}
    except Exception as e:                                  # noqa: BLE001
        log(f"webtool 搜索失败: {type(e).__name__}: {e}", level="WARN")
        return {"ok": False, "query": query, "err": str(e), "results": []}


# ============ 不可买板块 ============
# 唯一实现在 engine/_common.unbuyable_reason()，此处仅转发，避免第三份拷贝。


def code_ok(code, name=None):
    """返回 (是否可买, 说明)。判定逻辑见 _common.unbuyable_reason()。"""
    from webtool.stock.engine._common import unbuyable_reason
    reason = unbuyable_reason(code, name)
    if reason:
        return False, reason
    c = str(code).strip().upper()
    if c.startswith(("SH", "SZ", "BJ")):
        c = c[2:]
    c = c.zfill(6)
    return True, "沪市主板" if c.startswith("6") else "深市主板"
