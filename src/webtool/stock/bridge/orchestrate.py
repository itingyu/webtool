"""多源编排层 —— 一个动作横跨多个数据源时的回退策略与代码归一

## 它是什么

每个动作声明一串 `(源名, 取数闭包)`, 按序尝试, 取首个通过质检的结果:
"HTTP 200 + 合法 JSON" 不等于有数据 (封禁页、空 SPA), `_fallback` 因此除
`ok` 外还查 NaN/空 —— 否则会把"成功"的空壳当真数据往下传。

    ops = [("tencent", lambda: c.tencent_a(sym["tencent_a"])),
           ("xueqiu",  lambda: c.xueqiu_quote(sym["xq"])),
           ("em",      lambda: c.em_stock_get(sym["em"]))]
    return _fallback(ops)

另有 `normalize()` 把用户随手写的代码转成各源要的格式 (`600519` / `sh600519` /
`600519.SH` / `SH600519`), 格式拼装统一委托 `bridge/sources/_symbol.py`,
不在这里二次实现。

## 动作分组

  行情      stock_quote, stock_kline
  公司      stock_company, stock_business_analysis, stock_indicators
  财报三表  stock_balance_sheet, stock_income_statement, stock_cashflow
  股东      stock_top_holders, stock_holder_change
  板块      stock_industry_list, stock_concept_list, stock_industry_concept, stock_screener
  指数      stock_index, stock_index_constituent
  信息流    stock_announcement, stock_news
  资金/排行 stock_capital_flow, stock_dividend_rank, stock_margin_list, stock_ipo
  辅助      stock_search_tools, stock_health_check

## 怎么调

经 `bridge/srv.py` 的 `call('stock_xxx', params)` —— 它按命名约定找到本模块的
`t_stock_xxx` 并直接调用, 纯进程内 (不起子进程、不走协议握手、结果不在信封里
JSON 编解码)。
"""

from __future__ import annotations

import re
import time
import warnings
from typing import Any, Callable

from webtool.stock.bridge.sources import _symbol

warnings.filterwarnings("ignore")

try:
    from webtool.stock.bridge.sources import APIClient  # type: ignore
    _IMPORT_OK = True
    _IMPORT_ERR = None
except Exception as _e:
    _IMPORT_OK = False
    _IMPORT_ERR = repr(_e)



# ============================================================
# Client 单例
# ============================================================
_CLIENT: APIClient | None = None
_HEALTH: dict | None = None


def get_client() -> APIClient:
    global _CLIENT
    if _CLIENT is None:
        if not _IMPORT_OK:
            raise RuntimeError(f"数据源层 import 失败: {_IMPORT_ERR}")
        _CLIENT = APIClient()
    return _CLIENT


# ============================================================
# Symbol 规范化
# ============================================================
def normalize(symbol: str) -> dict[str, Any]:
    """
    把任意格式的股票代码转成各数据源需要的格式。

    支持：
      A 股: 688825 / sh688825 / SH688825 / 688825.SH / 600519.SH
      港股: 00700 / hk00700 / HK00700 / 01810
      美股: TSLA / usTSLA / us.TSLA / AAPL
      ETF: 510050 / sh510050 (归 cn)
      指数: 000300 / sh000300 / 399006 / sz399006

    返回 dict：
      market: cn / hk / us / index
      exchange: sh / sz / bj / hk / us / -
      code: 纯数字 / 字母
      ef: efinance 格式 (688825 / hk01810 / usTSLA)
      xq: 雪球格式 (SH688825 / HK00700 / usTSLA)
      em: 东财纯代码 (688825)
      em_finance: 东财财务 (688825.SH)
      tencent_a / tencent_hk / tencent_us / tencent_index
      sina_a / sina_hk
      cninfo: 巨潮 (688825)
      ths: 同花顺 (688825)
    """
    if not symbol or not isinstance(symbol, str):
        raise ValueError(f"symbol must be non-empty string, got {symbol!r}")
    s = symbol.strip()

    # A 股三形态 (前缀 / 后缀 / 裸 6 位) 的解析委托 `_symbol.parse` —— 本模块
    # 不自己判市场, 自己判会出错: "首位 in 5/6/7/9 → 沪" 会把北交所 `92xxxx`
    # 判成沪市 (`920000` → `SH920000`); 指数分支 `^\d{6}$ and s[:3] in
    # ("000","399")` 也永远不可达 (6 位已被上一步吃光, 从未执行)。
    p = _symbol.parse(s)
    if p:
        return _build(p[0].lower(), p[1])

    # 港股: hk00700 / 00700 (5 位数字)
    if re.match(r"^(hk|HK)\d{4,5}$|^\d{5}$", s):
        return _build("hk", re.sub(r"^(hk|HK)", "", s).zfill(5))

    # 美股: usTSLA / TSLA
    m = re.match(r"^(?:us|US)?([A-Za-z]{1,6})$", s)
    if m:
        return _build("us", m.group(1).upper())

    raise ValueError(f"cannot normalize symbol: {symbol!r}")


def _build(exch: str, code: str) -> dict:
    """构造 A 股 / 港股 / 美股 dict

    格式拼装全部委托 `sources._symbol`, 本函数不自己拼字符串 —— 自己拼会漂:
    裸 6 位若按 `s[0] in ("5","6","7","9") → 沪` 判, `920001` (北交所) 会被
    判成沪市。以 `_symbol` 为准 (它按 92 开头判北交所)。
    """
    if exch in ("sh", "sz", "bj"):
        # 市场由调用方从代码判出, 这里按它给定的前缀组装, 不重新推断
        sym = f"{exch}{code}"
        return {
            "market": "cn", "exchange": exch, "code": code,
            "ef": _symbol.em(sym),
            "xq": _symbol.xueqiu(sym),
            "em": _symbol.em(sym),
            "em_finance": _symbol.em_secucode(sym),
            "tencent_a": _symbol.tencent(sym),
            "sina_a": _symbol.sina(sym),
            "cninfo": _symbol.em(sym),
            "ths": _symbol.em(sym),
        }
    if exch == "hk":
        sym = f"hk{code}"
        return {
            "market": "hk", "exchange": "hk", "code": code,
            "ef": _symbol.tencent(sym),
            "xq": _symbol.xueqiu(sym),
            "tencent_hk": _symbol.tencent(sym),
            "sina_hk": code,
        }
    if exch == "us":
        sym = f"us{code}"
        return {
            "market": "us", "exchange": "us", "code": code,
            "ef": _symbol.tencent(sym),
            "xq": code.upper(),          # 雪球要裸 ticker (TSLA), 不是 usTSLA
            "tencent_us": _symbol.tencent(sym),
        }
    raise ValueError(f"unknown exchange: {exch}")


def _build_board(code: str, name: str = '') -> dict:
    """板块代码 dict (东财行业/概念 BKxxxx) —— K 线/分时/快照都走东财 90. 市场

    中文名 ('半导体') 在 `_resolve_board` 里换成 BK 再进来; 这里存 name 供
    K 线标题直接用, 免得再打一次行情请求换名字。
    """
    return {'market': 'board', 'exchange': 'em', 'code': code, 'name': name,
            'em': code}


_BOARD_CACHE: dict = {'at': 0.0, 'items': ()}


def _boards_cached(client) -> list:
    """东财行业+概念板块目录 [(code, name)], 进程内缓存 1h"""
    now = time.monotonic()
    if _BOARD_CACHE['items'] and now - _BOARD_CACHE['at'] < 3600:
        return _BOARD_CACHE['items']
    items: list = []
    for kind in ('industry', 'concept'):
        r = client.em_board_list(kind)
        for b in (r.get('data') or {}).get('boards') or []:
            if b.get('code') and b.get('name'):
                items.append((str(b['code']).upper(), str(b['name'])))
    if items:
        _BOARD_CACHE.update({'at': now, 'items': items})
    return items


def _resolve_board(symbol: str) -> dict | None:
    """'BK0480' / '半导体' / '半导体行业' → 板块 sym dict; 非板块返回 None

    匹配规则: 目录里先找**精确名**, 再找**去后缀前缀匹配** —— '半导体行业'
    去掉 '行业' 后精确命中, 用户手打变体不至于落空。
    """
    s = (symbol or '').strip()
    if re.fullmatch(r'(?i)bk\d{4}', s):
        return _build_board(s.upper())
    if not any('\u4e00' <= ch <= '\u9fff' for ch in s):
        return None
    # 可能带行业性后缀; 纯英文名不是板块
    client = get_client()
    if not _boards_cached(client):
        return None
    norm = re.sub(r'(行业|指数|板块)$', '', s)
    for code, name in _BOARD_CACHE['items']:
        if name == s or name == norm:
            return _build_board(code, name)
    for code, name in _BOARD_CACHE['items']:
        if name.startswith(norm) or norm in name:
            return _build_board(code, name)
    return None


def _build_index(exch: str, code: str) -> dict:
    """指数代码 dict"""
    return {
        "market": "index", "exchange": exch, "code": code,
        "tencent_a": f"{exch}{code}",  # 指数在腾讯走 tencent_a
        "tencent_index": f"s_{exch}{code}",  # 带 s_ 前缀
        "gtimg_index": f"{exch}{code}",
        "sse_yunhq": code,
        "em": code,
    }


def normalize_index(symbol: str) -> dict[str, Any]:
    """专门给 stock_index 用: 接受 idx:000300 / sh000300 / 000300 / 399006"""
    if not symbol or not isinstance(symbol, str):
        raise ValueError(f"symbol must be non-empty string, got {symbol!r}")
    s = symbol.strip()
    # 去掉前缀
    if s.lower().startswith("idx:"):
        s = s[4:]
    elif s.lower().startswith("index:"):
        s = s[6:]
    # 带 sh/sz 前缀
    m = re.match(r"^(sh|sz|SH|SZ)(\d{6})$", s)
    if m:
        return _build_index(m.group(1).lower(), m.group(2))
    # 纯 6 位: 0 开头 → 沪, 3 开头 → 深 (中证指数的代码段)
    if re.match(r"^\d{6}$", s):
        if s[0] == "0":
            return _build_index("sh", s)
        if s[0] == "3":
            return _build_index("sz", s)
    raise ValueError(f"not a valid index code: {symbol!r}")


# ============================================================
# Fallback 链辅助
# ============================================================
def _is_data_quality_ok(data: Any) -> bool:
    """检查返回数据是否有效 (不是空 dict/全 NaN/空数组/上游 success=False)

    东财部分 F10 端点在查无数据时 HTTP 200 + `{"success": false,
    "message": "返回数据为空"}` —— 对调用方这就是失败, 必须让 fallback 继续,
    不能当成功透出 (曾致 income 动作首源空结果后不换源)。
    """
    if data is None:
        return False
    if isinstance(data, (list, tuple, str)):
        return len(data) > 0
    if not isinstance(data, dict):
        return True  # 未知类型放行
    if not data:
        return False
    # 上游显式失败 (东财 datacenter/F10 风格)
    if data.get("success") is False:
        return False
    if data.get("result") is None and data.get("message"):
        return False
    # 关键价格字段 NaN 检测 (NaN != NaN)
    for k in ("最新价", "current", "now", "price", "close", "last_close"):
        if k in data:
            v = data[k]
            if isinstance(v, float) and v != v:
                return False
            if v in (None, "", "nan", "NaN"):
                return False
    return True


def _fallback(ops: list[tuple[str, Callable[[], Any]]], quality_check: bool = True) -> dict:
    """
    按顺序尝试调用，每个 op 是 (source_name, fn)。
    返回首个 ok 的结果，统一格式 {ok, source, data, attempts}。
    quality_check=True 时，还会检查数据质量（NaN/空）。
    """
    attempts = []
    for src, fn in ops:
        t0 = time.time()
        try:
            r = fn()
        except Exception as e:
            attempts.append({"source": src, "ok": False, "error": repr(e)[:120],
                             "took_ms": int((time.time() - t0) * 1000)})
            continue
        took = int((time.time() - t0) * 1000)
        if isinstance(r, dict) and r.get("ok"):
            data = r["data"]
            if quality_check and not _is_data_quality_ok(data):
                attempts.append({"source": src, "ok": False,
                                 "error": "data quality failed (NaN/empty)",
                                 "took_ms": took})
                continue
            return {
                "ok": True, "source": src, "data": data,
                "raw_size": r.get("raw_size", 0),
                "took_ms": took,
                "attempts": attempts,
            }
        err = (r.get("error") if isinstance(r, dict) else None) or "no result"
        attempts.append({"source": src, "ok": False, "error": str(err)[:120], "took_ms": took})
    return {"ok": False, "error": "all sources failed",
            "attempts": attempts}


# ============================================================
# Tool 实现
# ============================================================
def t_stock_quote(args: dict) -> dict:
    """实时行情"""
    sym = normalize(args["symbol"])
    client = get_client()

    if sym["market"] == "cn":
        ops = [
            ("tencent",  lambda: client.tencent_a(sym["tencent_a"])),   # 最稳最快
            ("efinance", lambda: client.ef_snapshot(sym["ef"])),
            ("xueqiu",   lambda: client.xueqiu_quote(sym["xq"])),
            ("sina",     lambda: client.sina_hq_a(sym["sina_a"])),
            ("em",       lambda: client.em_stock_get(sym["em"])),
        ]
    elif sym["market"] == "hk":
        ops = [
            ("tencent",  lambda: client.tencent_hk(sym["tencent_hk"])),  # 沙盒上 tencent 最稳
            ("sina",     lambda: client.sina_hq_hk(sym["sina_hk"])),
            ("xueqiu",   lambda: client.xueqiu_quote(sym["xq"])),
        ]
    elif sym["market"] == "us":
        ops = [
            ("tencent",  lambda: client.tencent_us(sym["tencent_us"])),  # 主源：沙盒 tencent 稳
            ("xueqiu",   lambda: client.xueqiu_quote(sym["xq"])),
        ]
    else:
        return {"ok": False, "error": f"unsupported market: {sym['market']}"}
    return _fallback(ops)


def _tail_ef_history(ef_result: dict, count: int) -> dict:
    """ef_history 返回全量 (~6000 行), 取尾部 count 行节省带宽/token"""
    if not (isinstance(ef_result, dict) and ef_result.get("ok")):
        return ef_result
    data = ef_result["data"]
    if isinstance(data, list) and len(data) > count:
        return {**ef_result, "data": data[-count:]}
    return ef_result


def t_stock_kline(args: dict) -> dict:
    """K 线 (period: day/week/month)"""
    period = args.get("period", "day")
    count = args.get("count", 60)
    sym = _resolve_board(args['symbol'])
    if sym:
        client = get_client()
        klt = {"day": 101, "week": 102, "month": 103}.get(period, 101)
        return _fallback([("em_kline",
                           lambda: client.em_kline(sym["em"], klt=klt, lmt=count))])
    sym = normalize(args["symbol"])
    client = get_client()

    if sym["market"] == "cn":
        ops = [
            ("tencent_kline", lambda: client.tencent_kline_global(sym["xq"].lower(), period, count, "qfq")),
            ("xueqiu",        lambda: client.xueqiu_kline(sym["xq"], period, count)),
            ("em",            lambda: client.em_kline(
                sym["em"], klt={"day": 101, "week": 102, "month": 103}.get(period, 101),
                lmt=count)),
            ("efinance",      lambda: _tail_ef_history(client.ef_history(sym["ef"]), count)),
        ]
    elif sym["market"] == "hk":
        ops = [
            ("tencent_kline", lambda: client.tencent_kline_global(sym["tencent_hk"], period, count)),
            ("efinance",      lambda: _tail_ef_history(client.ef_history(sym["ef"]), count)),
        ]
    elif sym["market"] == "us":
        ops = [
            # 东财在前: 腾讯 usfqkline 上游退化只回 2 根, 且它"成功但残缺",
            # 放前面会把 2 根 K 线当成结果返回 (质量检查拦不住"少"不拦"空")。
            ("em_us_kline",      lambda: client.em_us_kline(sym["code"],
                                                            klt={"day": 101, "week": 102, "month": 103}.get(period, 101),
                                                            lmt=count)),
            ("tencent_us_kline", lambda: client.tencent_us_kline(sym["tencent_us"], period, count)),
            ("tencent_global",   lambda: client.tencent_global(sym["code"])),  # 美股无 K 线则退化
            ("efinance",         lambda: _tail_ef_history(client.ef_history(sym["ef"]), count)),
        ]
    else:
        return {"ok": False, "error": f"unsupported market: {sym['market']}"}
    return _fallback(ops)



# ── 分时 (当日/五日) ────────────────────────────────────────────────
def _vol_mult(price, cum_amt, cum_vol):
    """成交量单位换算系数: A 股腾讯/东财都是"手"(100 股), 港美股是"股"

    不按市场硬编码 (港股通/ETF/美股指数各有例外), 直接看末行的
    额/量 与价格之比: 约 100 就是手, 约 1 就是股。
    """
    if not (price and cum_vol):
        return 100.0
    ratio = cum_amt / (cum_vol * price)
    return 100.0 if 20 < ratio < 1000 else 1.0


def _secs(t):
    """'HH:MM:SS' / 'HH:MM' → 当日秒数"""
    f = str(t).split(':')
    try:
        h = int(f[0]); m = int(f[1]) if len(f) > 1 else 0
        sec = int(float(f[2])) if len(f) > 2 else 0
    except ValueError:
        return 0
    return h * 3600 + m * 60 + sec


def _bucket_ticks(rows, gran):
    """逐笔成交 → 每 gran 秒一根: 价取桶内最后一笔, 量按桶累加, 均价走累计口径

    分钟接口给不了更细的粒度, 只能回到逐笔自己合; gran=30 就是 480 根,
    配合自适应图宽刚好每根还有 1px 以上。
    """
    buckets, order = {}, []
    for r in rows or []:
        try:
            t, price = str(r[0]), float(r[1])
            vol, amt = float(r[2] or 0), float(r[3] or 0)
        except (IndexError, TypeError, ValueError):
            continue
        if not price:
            continue
        k = _secs(t) // gran
        b = buckets.get(k)
        if b is None:
            hh, mm, ss = k * gran // 3600, k * gran % 3600 // 60, k * gran % 60
            b = {'t': f'{hh:02d}:{mm:02d}:{ss:02d}', 'price': price,
                 'vol': 0.0, 'amt': 0.0}
            buckets[k] = b
            order.append(k)
        b['price'] = price
        b['vol'] += vol
        b['amt'] += amt
    if not order:
        return []
    tail = buckets[order[-1]]
    mult = _vol_mult(tail['price'], tail['amt'], tail['vol'])
    out, cv, ca = [], 0.0, 0.0
    for k in order:
        b = buckets[k]
        cv += b['vol']
        ca += b['amt']
        out.append({'t': b['t'], 'price': b['price'],
                    'avg': round(ca / (cv * mult), 3) if cv else b['price'],
                    'vol': round(b['vol'], 2), 'amount': round(b['amt'], 2)})
    return out


def _norm_minute_points(rows, mult=None):
    """腾讯 'HHMM price 累计量 累计额' / 东财 [t, price, 累计量, 累计额] → 点列表

    两条源的量额都是**当日累计**, 所以逐分钟量要做差; 均价用 累计额/(累计量×系数),
    与行情软件的黄线同口径。系数常规走 `_vol_mult` 的比值窗口判 (手/股);
    板块指数的分值来自成分股加权, 比值会飘出窗口 (板块均价 ~70 vs 点位 2346),
    这类调用方直接给 mult=100, 判不出也得画对黄线。
    """
    recs = []
    for r in rows or []:
        try:
            if isinstance(r, str):
                f = r.split()
                t, price = f[0][:5], float(f[1])
                cv, ca = float(f[2] or 0), float(f[3] or 0) if len(f) > 3 else 0.0
            else:
                t, price = str(r[0])[:5].replace(':', ''), float(r[1])
                cv, ca = float(r[2] or 0), float(r[3] or 0) if len(r) > 3 else 0.0
        except (IndexError, TypeError, ValueError):
            continue
        if not price:
            continue
        recs.append((t if ':' in t else f'{t[:2]}:{t[2:]}', price, cv, ca))
    if not recs:
        return []
    mult = mult or _vol_mult(recs[-1][1], recs[-1][3], recs[-1][2])
    out, pcv = [], 0.0
    for t, price, cv, ca in recs:
        vol = cv - pcv if cv >= pcv else cv
        pcv = cv
        out.append({'t': t, 'price': price,
                    'avg': round(ca / (cv * mult), 3) if cv else price,
                    'vol': round(vol, 2), 'amount': round(ca, 2)})
    return out


def _daily_closes(client, sym: dict) -> dict:
    """近 N 个交易日收盘价 (给五日图算每日昨收); 失败不拦主流程"""
    try:
        if sym['market'] == 'cn':
            r = client.tencent_kline_global(sym['tencent_a'], 'day', 12, 'qfq')
        elif sym['market'] == 'hk':
            r = client.tencent_kline_global(sym['tencent_hk'], 'day', 12)
        else:
            return {}
        rows = ((r or {}).get('data') or {}).get('klines') or []
        return {str(x[0])[:10]: float(x[2]) for x in rows if len(x) > 2}
    except Exception:                                        # noqa: BLE001
        return {}


def _fill_preclose(days: list, closes: dict) -> None:
    """每日昨收: 取该日在收盘价序列里的前一个交易日; 缺失则退化为当日首点"""
    dates = sorted(closes)
    for d in days:
        i = dates.index(d['date']) if d['date'] in dates else -1
        if i > 0:
            d['preclose'] = closes[dates[i - 1]]
        elif d.get('preclose') in (None, 0):
            d['preclose'] = d['points'][0]['price'] if d['points'] else None
    if days:
        for prev, cur in zip(days, days[1:]):
            if not cur.get('preclose') and prev['points']:
                cur['preclose'] = prev['points'][-1]['price']


def _auction_from_ticks(client, tsym: str):
    """只抓逐笔第 0 页, 用首行 (09:25:00) 还原竞价成交价/量。

    东财 trends2 不可达时的兜底: 没有 09:15-09:25 的匹配价曲线,
    但最终成交价、成交量、成交额都有, 竞价那一格不至于空着。
    """
    if not tsym:
        return None
    try:
        r = client.tencent_ticks(tsym, max_pages=1)      # 1 次请求
    except Exception:                                     # noqa: BLE001
        return None
    rows = ((r.get('data') or {}).get('rows') or []) if r.get('ok') else []
    if not rows:
        return None
    t, price, vol, amt = (list(rows[0]) + [None] * 4)[:4]
    if not t or t > '09:26' or not price:
        return None
    return {'t': '09:25', 'price': float(price), 'avg': float(price),
            'vol': float(vol or 0), 'amount': float(amt or 0)}


def _merge_auction(days: list, em_days: list) -> int:
    """把东财的盘前竞价点 (09:15-09:25) 拼到腾讯日线前面; 返回拼上的天数"""
    by_date = {d['date']: d for d in em_days or []}
    merged = 0
    for d in days:
        e = by_date.get(d['date'])
        if not e:
            continue
        # 竞价段只到 09:25: 东财的 09:26-09:29 是静默期(价格冻结、量为 0),
        # 当成竞价点画进去会让竞价区比标注宽 4 分钟
        pre = [p for p in e['points'] if p['t'] <= '09:25']
        if not pre:
            continue
        if d['points'] and d['points'][0]['t'] < '09:30':
            continue                                  # 源里本来就带
        # 东财把竞价成交记在 09:26, 行情软件一律画在 09:25, 这里归位
        auc_vol = 0.0
        trade = next((p for p in e['points']
                      if p['t'] > '09:25' and (p.get('vol') or 0) > 0), None)
        if trade:
            last = dict(pre[-1])
            last['price'] = trade['price']
            last['vol'] = trade['vol']
            # 东财的 amount 口径偏高 (含虚拟撮合), 用主源开盘那笔累计额更准
            head0 = d['points'][0] if d['points'] else {}
            last['amount'] = head0.get('amount') or trade.get('amount') or 0
            last['avg'] = head0.get('avg') or trade['price']
            pre = pre[:-1] + [last]
            auc_vol = trade['vol']
        rest = list(d['points'])
        # 主源首根 (09:30) 的累计量本来就含竞价成交, 不扣会重复计一遍
        if auc_vol and rest and (rest[0].get('vol') or 0) >= auc_vol:
            head = dict(rest[0])
            head['vol'] = round((head.get('vol') or 0) - auc_vol, 2)
            rest[0] = head
        d['points'] = pre + rest
        d['auction'] = True
        merged += 1
    return merged


def t_stock_intraday(args: dict) -> dict:
    """分时 (ndays=1 当日 / 5 五日), 默认带集合竞价

    竞价只有一个源: 东财 trends2 的 `iscr=1`。腾讯的 minute 端点从 09:30 起,
    没有 09:15-09:25 段 —— 所以主图走腾讯 (稳), 竞价单独向东财要一段再拼。
    东财不可达时不静默: `auction=False` + `auction_note` 明说, 图照出。
    """
    sym = _resolve_board(args['symbol'])
    if sym:
        client = get_client()
        # 板块的"竞价段"不存在撮合 (板块指数是合成价), 不向 iscr=1 要
        em_days = client.em_trends(sym['em'], args.get('ndays') or 1)
        days = [{'date': d.get('date'), 'points': _norm_minute_points(d.get('rows'), mult=100.0)}
                for d in (em_days.get('data') or {}).get('days') or []]
        return {'ok': True, 'source': 'em_trends', 'data': {'symbol': sym['code'], 'market': 'board',
                    'name': sym['name'], 'via': 'em_trends', 'source': 'em_trends',
                    'preclose': (em_days.get('data') or {}).get('preclose'),
                    'days': days, 'auction': False,
                    'note': '板块分时: 仅东财 (无竞价段)'}}
    sym = normalize(args["symbol"])
    ndays = 5 if int(args.get('ndays') or 1) > 1 else 1
    want_auc = bool(args.get('auction', True)) and ndays == 1
    client = get_client()

    if sym['market'] == 'cn':
        ops = [('tencent', lambda: client.tencent_minute_days(sym['tencent_a'], ndays)),
               ('em', lambda: client.em_trends(sym['xq'], ndays))]
        em_code = sym['xq']
    elif sym['market'] == 'hk':
        ops = [('tencent', lambda: client.tencent_minute_days(sym['tencent_hk'], ndays)),
               ('em', lambda: client.em_trends('116.' + sym['code'], ndays))]
        em_code = '116.' + sym['code']
    elif sym['market'] == 'us':
        ops = [('em', lambda: client.em_trends('105.' + sym['code'], ndays)),
               ('tencent', lambda: client.tencent_minute_days(sym['tencent_us'], ndays))]
        em_code = '105.' + sym['code']
    elif sym['market'] == 'index':
        ops = [('tencent', lambda: client.tencent_minute_days(sym['tencent_a'], ndays)),
               ('em', lambda: client.em_trends(sym['tencent_a'], ndays))]
        em_code = sym['tencent_a']
    else:
        return {'ok': False, 'error': f"unsupported market: {sym['market']}"}

    res = _fallback(ops)
    if not res.get('ok'):
        return res
    raw = res.get('data') or {}
    days = []
    for d in raw.get('days') or []:
        pts = _norm_minute_points(d.get('rows'))
        if pts:
            days.append({'date': d.get('date') or '', 'points': pts,
                         'preclose': raw.get('preclose')})
    if not days:
        return {'ok': False, 'error': 'empty minute rows'}

    # 每日昨收 (五日图要按各自昨收算涨幅)
    if len(days) > 1:
        _fill_preclose(days, _daily_closes(client, sym))
    elif not days[0].get('preclose'):
        days[0]['preclose'] = days[0]['points'][0]['price']

    # 细粒度 (gran < 60 秒): 分钟接口给不出更细的粒度, 回到逐笔自己合
    gran = int(args.get('gran') or 60)
    tick_note = None
    days_1m = None                 # 细粒度时留一份分钟序列, 供组合图复用
    if gran and gran < 60 and ndays == 1:
        days_1m = days
        tick_sym = (sym.get('tencent_a') or sym.get('tencent_hk')
                    or sym.get('tencent_us'))
        tr = client.tencent_ticks(tick_sym) if tick_sym else {'ok': False}
        if tr.get('ok'):
            pts = _bucket_ticks(tr['data']['rows'], gran)
            if not want_auc:      # 逐笔自带 09:25 竞价成交, 不要竞价就剔掉
                pts = [p for p in pts if p['t'] >= '09:30']
            if pts:
                days = [{'date': days[0]['date'], 'points': pts,
                         'preclose': days[0]['preclose'],
                         'auction': bool(want_auc and pts[0]['t'] < '09:30')}]
                tick_note = f'{gran}秒'
            else:
                tick_note = f'{gran}秒失败, 退回分钟'
        else:
            tick_note = f'{gran}秒失败, 退回分钟'

    # 集合竞价: 主源不带就单独补
    # 盘后固定价格交易 (15:05-15:30): 价格恒定、量极小, 混进连续竞价里会把
    # 右端拉成一条直线。默认剔掉, --after-hours 才保留 (科创板等确实有这个时段)。
    if not args.get('after_hours'):
        for d in days:
            d['points'] = [p for p in d['points'] if p['t'] <= '15:00']
    if not want_auc:      # 源自带盘前点时, 不要竞价也要剔掉
        for d in days:
            d['points'] = [p for p in d['points'] if p['t'] >= '09:30']

    auction = any(d.get('auction') for d in days)
    note = None
    if want_auc and not auction:
        em = client.em_trends(em_code, 1, premarket=True)
        if em.get('ok'):
            em_days = [{'date': d.get('date'), 'points': _norm_minute_points(d.get('rows'))}
                       for d in (em['data'].get('days') or [])]
            auction = bool(_merge_auction(days, em_days))
            if not auction:
                note = '该日无竞价数据'
        else:
            note = '集合竞价源不可达'
        # 兜底: 东财断连/无数据时, 用逐笔第一页首行补"最终成交价+量"。
        # 拿不到 09:15-09:25 的匹配价序列, 但竞价那一格不会空着。
        if not auction:
            tsym = (sym.get('tencent_a') or sym.get('tencent_hk')
                    or sym.get('tencent_us'))
            ap = _auction_from_ticks(client, tsym) if tsym else None
            if ap:
                if not any(p['t'] == '09:25' for p in days[0]['points']):
                    days[0]['points'].insert(0, ap)
                days[0]['auction'] = True
                auction = True
                note = '竞价价量取自逐笔，无匹配价序列'

    return {'ok': True, 'source': res.get('source'),
            'data': {'symbol': sym['code'], 'market': sym['market'],
                     'name': raw.get('name'),
                     'ndays': len(days), 'auction': auction,
                     'gran': gran,
                     'gran_note': tick_note,
                     'days_1m': days_1m,
                     'auction_note': note if want_auc else None,
                     'auction_error': (str(em.get('error'))[:200]
                                       if want_auc and not auction and em.get('error') else None),
                     'preclose': days[-1].get('preclose'), 'days': days},
            'attempts': res.get('attempts', []), 'took_ms': res.get('took_ms')}

def t_stock_company(args: dict) -> dict:
    """公司基本信息+简介"""
    sym = normalize(args["symbol"])
    client = get_client()

    if sym["market"] == "cn":
        ops = [
            ("efinance", lambda: client.ef_base_info(sym["ef"])),
            ("xueqiu",   lambda: client.xueqiu_company(sym["xq"])),
            ("cninfo",   lambda: client.cninfo_company_profile(sym["cninfo"])),
            ("em",       lambda: client.em_company_survey(sym["xq"])),
        ]
    elif sym["market"] == "hk":
        ops = [("xueqiu", lambda: client.xueqiu_company(sym["xq"]))]
    elif sym["market"] == "us":
        ops = [("xueqiu", lambda: client.xueqiu_company(sym["xq"]))]
    else:
        return {"ok": False, "error": f"unsupported market: {sym['market']}"}
    return _fallback(ops)


def t_stock_business_analysis(args: dict) -> dict:
    """主营业务分析 (A 股有效)"""
    sym = normalize(args["symbol"])
    if sym["market"] != "cn":
        return {"ok": False, "error": "business_analysis 仅支持 A 股"}
    client = get_client()
    ops = [
        ("xueqiu", lambda: client.xueqiu_business_analysis(sym["xq"])),
        ("xueqiu_v2", lambda: client.xueqiu_f10_business(sym["xq"])),
    ]
    return _fallback(ops)


def t_stock_indicators(args: dict) -> dict:
    """核心财务指标 (PE/PB/ROE/毛利率等)"""
    sym = normalize(args["symbol"])
    count = args.get("count", 3)
    client = get_client()

    if sym["market"] == "cn":
        ops = [
            ("xueqiu", lambda: client.xueqiu_indicator(sym["xq"], count)),
            ("em",     lambda: client.em_f10_main_finadata(sym["em_finance"])),
        ]
    elif sym["market"] == "us":
        ops = [("xueqiu", lambda: client.xueqiu_f10_indicator_us(sym["code"]))]
    else:
        return {"ok": False, "error": f"unsupported market: {sym['market']}"}
    return _fallback(ops)


def t_stock_balance_sheet(args: dict) -> dict:
    """资产负债表"""
    sym = normalize(args["symbol"])
    if sym["market"] != "cn":
        return {"ok": False, "error": "balance_sheet 仅支持 A 股"}
    page_size = args.get("page_size", 3)
    client = get_client()
    ops = [
        ("em_f10",  lambda: client.em_f10_balance(sym["em_finance"], page_size)),
        ("em_dmsk", lambda: client.em_dmsk_balance(sym["em_finance"], page_size)),
    ]
    return _fallback(ops)


def t_stock_income_statement(args: dict) -> dict:
    """利润表"""
    sym = normalize(args["symbol"])
    if sym["market"] != "cn":
        return {"ok": False, "error": "income_statement 仅支持 A 股"}
    page_size = args.get("page_size", 5)
    client = get_client()
    ops = [
        ("em_f10",  lambda: client.em_f10_income(sym["em_finance"], page_size)),
        ("em_dmsk", lambda: client.em_dmsk_income(sym["em_finance"], page_size)),
    ]
    return _fallback(ops)


def t_stock_cashflow(args: dict) -> dict:
    """现金流量表"""
    sym = normalize(args["symbol"])
    if sym["market"] != "cn":
        return {"ok": False, "error": "cashflow 仅支持 A 股"}
    page_size = args.get("page_size", 3)
    client = get_client()
    ops = [("em_f10", lambda: client.em_f10_cashflow(sym["em_finance"], page_size)),
           ("em_dmsk", lambda: client.em_dmsk_cashflow(sym["em_finance"], page_size))]
    return _fallback(ops)


def t_stock_top_holders(args: dict) -> dict:
    """十大股东 (A 股老股有效, 新股空)"""
    sym = normalize(args["symbol"])
    if sym["market"] != "cn":
        return {"ok": False, "error": "top_holders 仅支持 A 股"}
    client = get_client()
    ops = [("xueqiu", lambda: client.xueqiu_top_holders(sym["xq"]))]
    return _fallback(ops)


def t_stock_holder_change(args: dict) -> dict:
    """股东变动 (A 股老股有效)"""
    sym = normalize(args["symbol"])
    if sym["market"] != "cn":
        return {"ok": False, "error": "holder_change 仅支持 A 股"}
    client = get_client()
    ops = [("xueqiu", lambda: client.xueqiu_skholderchg(sym["xq"]))]
    return _fallback(ops)


def t_stock_industry_list(args: dict) -> dict:
    """行业板块列表"""
    page = args.get("page", 1)
    client = get_client()
    ops = [
        ("ths", lambda: client.ths_industry_list(page)),
        ("em",  lambda: client.em_industry_list(50)),
    ]
    return _fallback(ops)


def t_stock_concept_list(args: dict) -> dict:
    """概念板块列表"""
    page = args.get("page", 1)
    client = get_client()
    ops = [
        ("ths", lambda: client.ths_concept_list(page)),
        ("em",  lambda: client.em_concept_list(50)),
    ]
    return _fallback(ops)


def t_stock_industry_concept(args: dict) -> dict:
    """个股所属行业+概念"""
    sym = normalize(args["symbol"])
    client = get_client()

    if sym["market"] == "cn":
        ops = [("xueqiu", lambda: client.xueqiu_concept_industry(sym["xq"]))]
    elif sym["market"] == "hk":
        ops = [("xueqiu", lambda: client.xueqiu_f10_industry_hk(sym["xq"]))]
    elif sym["market"] == "us":
        ops = [("xueqiu", lambda: client.xueqiu_f10_industry_us(sym["code"]))]
    else:
        return {"ok": False, "error": f"unsupported market: {sym['market']}"}
    return _fallback(ops)


def t_stock_screener(args: dict) -> dict:
    """涨跌幅/成交额等排行 (market: cn_a/cn_b/hk/us, sort: changepercent/amount/volume/per/pb)"""
    market = args.get("market", "cn_a")
    sort = args.get("sort", "changepercent")
    num = args.get("num", 20)
    client = get_client()

    # sina 节点映射
    sina_node = {
        "cn_a": "hs_a", "cn_b": "hs_b",
        "sz_a": "sz_a", "hk": "hk",
    }.get(market)
    ops = []
    if sina_node and sort in ("changepercent", "amount", "volume", "per", "pb", "mktcap", "turnoverratio"):
        ops.append(("sina", lambda: client.sina_market_sort(sina_node, num, sort)))
    if market in ("cn_a", "cn_b"):
        type_ = {"cn_a": "sha", "cn_b": "shb"}.get(market, "sha")
        ops.append(("xueqiu_sha", lambda: client.xueqiu_screener(type_, sort, "desc", 1, num)))
    elif market == "hk":
        ops.append(("xueqiu_hk", lambda: client.xueqiu_screener("hk", sort, "desc", 1, num)))
    elif market == "us":
        ops.append(("xueqiu_us", lambda: client.xueqiu_screener("us", sort, "desc", 1, num)))
    if not ops:
        return {"ok": False, "error": f"no source for market={market}, sort={sort}"}
    return _fallback(ops)


def t_stock_index(args: dict) -> dict:
    """指数实时 / 历史收益 (kind: quote/history)"""
    try:
        sym = normalize_index(args["symbol"])
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    kind = args.get("kind", "quote")
    client = get_client()

    if kind == "quote":
        ops = [
            ("gtimg",     lambda: client.gtimg_index(sym["gtimg_index"])),  # 沙盒最稳
            ("tencent",   lambda: client.tencent_index(sym["tencent_index"])),
            ("sse_yunhq", lambda: client.sse_yunhq_index(sym["sse_yunhq"])),
        ]
    elif kind == "history":
        # 中证 csindex 不一定覆盖所有指数，先尝试
        ops = [("csindex", lambda: client.csindex_perf(
            sym["sse_yunhq"],
            args.get("start_date", "20260101"),
            args.get("end_date", "20260809"),
        ))]
    else:
        return {"ok": False, "error": f"kind must be quote or history, got {kind!r}"}
    return _fallback(ops)


def t_stock_index_constituent(args: dict) -> dict:
    """指数成分股"""
    try:
        sym = normalize_index(args["symbol"])
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    page_size = args.get("page_size", 50)
    client = get_client()
    ops = [("em", lambda: client.em_index_constituent(sym["sse_yunhq"], page_size))]
    return _fallback(ops)


def t_stock_announcement(args: dict) -> dict:
    """公告列表 (A 股)"""
    sym = normalize(args["symbol"])
    if sym["market"] != "cn":
        return {"ok": False, "error": "announcement 仅支持 A 股"}
    page = args.get("page", 1)
    page_size = args.get("page_size", 10)
    # (原 se_date 默认值从未被 ops 引用 —— t_stock_announcement 走东财源,
    #  巨潮日期窗在 np_notice_ann 失败回退时才用, 由调用方传)
    # 推断 org_id: 主板 gssh0600519, 科创板 9920000008 等 (简化: 给个默认尝试)
    # 实际更可靠: 先 np_notice_ann 拿 art_code, 再 cninfo_announcement 拉 PDF
    client = get_client()
    ops = [
        ("em_np",  lambda: client.np_notice_ann(sym["em"], page_size, page)),
        # cninfo 需要 org_id 复杂处理，退而求其次走全文搜索
        ("cninfo_search", lambda: client.cninfo_fulltext_search(sym["em"], page, page_size)),
    ]
    return _fallback(ops)


def t_stock_news(args: dict) -> dict:
    """个股新闻"""
    sym = normalize(args["symbol"])
    if sym["market"] != "cn":
        return {"ok": False, "error": "news 仅支持 A 股"}
    client = get_client()
    ops = [("ths", lambda: client.ths_stockpage_news(sym["ths"]))]
    return _fallback(ops)


def t_stock_capital_flow(args: dict) -> dict:
    """资金流向 (scope: industry/individual/north)"""
    scope = args.get("scope", "industry")
    client = get_client()
    if scope == "industry":
        ops = [("ths", lambda: client.ths_funds_hyzjl())]
    elif scope == "individual":
        ops = [("ths", lambda: client.ths_funds_ggzjl())]
    elif scope == "north":
        ops = [
            ("em_kamt", lambda: client.em_kamt()),
            ("em_mutual", lambda: client.em_mutual_hold(50)),
        ]
    else:
        return {"ok": False, "error": "scope must be industry/individual/north"}
    return _fallback(ops)


def t_stock_dividend_rank(args: dict) -> dict:
    """分红排行"""
    page_size = args.get("page_size", 50)
    client = get_client()
    ops = [("em", lambda: client.em_dividend_rank(page_size))]
    return _fallback(ops)


def t_stock_margin_list(args: dict) -> dict:
    """融资融券列表"""
    page_size = args.get("page_size", 50)
    client = get_client()
    ops = [("em", lambda: client.em_margin_list(page_size))]
    return _fallback(ops)


def t_stock_ipo(args: dict) -> dict:
    """IPO 列表 (page_size)"""
    page_size = args.get("page_size", 50)
    client = get_client()
    ops = [
        ("em_gem",   lambda: client.em_gem_list(page_size)),
        ("ths_xgyp", lambda: client.ths_ipo_xgyp()),
        ("ths_xgpt", lambda: client.ths_ipo_xgpt()),
    ]
    return _fallback(ops)


def t_stock_search_tools(args: dict) -> dict:
    """按关键词搜动作 (返回匹配的 name + description)

    动作清单向 `srv.do_tools()` 要 —— 它扫本模块的 `t_stock_*` 函数, 是唯一
    事实来源; 自己再维护一份清单会漏改, 且坏了不报错。
    """
    from webtool.stock.bridge import srv as _srv
    kw = str(args.get('keyword', '')).lower().strip()
    r = _srv.do_tools(kw)
    rows = [{'name': t['name'], 'description': t.get('desc', '')}
            for t in r.get('tools', [])]
    return {'ok': True, 'data': rows, 'count': r.get('count', len(rows))}


def t_stock_health_check(args: dict) -> dict:
    """健康检查：跑一个轻量接口 (tencent_a) 验证链路"""
    global _HEALTH
    t0 = time.time()
    try:
        client = get_client()
        r = client.tencent_a("sh600519")
        ok = bool(r and r.get("ok"))
        _HEALTH = {
            "ok": ok,
            "checked_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "took_ms": int((time.time() - t0) * 1000),
            "sources_import_ok": _IMPORT_OK,
            "sources_import_err": _IMPORT_ERR,
            "probe": "tencent_a sh600519",
            "probe_ok": ok,
        }
        return _HEALTH
    except Exception as e:
        _HEALTH = {"ok": False, "error": repr(e), "took_ms": int((time.time() - t0) * 1000)}
        return _HEALTH
