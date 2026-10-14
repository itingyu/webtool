"""取数契约适配层 —— 把 `sources/` 的结果转成 stock-master 内部用的形状。

取数只有 `sources/` 一套实现, 本模块只负责**形状适配**:
- sources 统一返回 `{ok, data, error}`, 内部 stock-master 要的是展平结构;
- 字段名沿用既有契约 (current/percent/turnover_rate/...), 这样
  single_analysis / short_pool / long_pool / mid_pool / risk_check 的调用点
  一行都不用改。

真正的 HTTP、解析、fallback、代理路由全在 sources 那边, 这里不建 session。
"""

from __future__ import annotations

import functools

_CLIENT = None


def client():
    """全局单例 —— 复用连接池和 session (建一次约 1~2s)"""
    global _CLIENT
    if _CLIENT is None:
        from webtool.stock.bridge.sources import APIClient
        _CLIENT = APIClient()
    return _CLIENT


# ── 行情 ────────────────────────────────────────────────────────────

def quote(codes):
    """{原始代码: 展平行情}; 雪球取不到自动兜底东财 (fetchers 原行为)"""
    return client().xueqiu_quote_flat(codes)


# ── K 线 ────────────────────────────────────────────────────────────

def get_kline(symbol, count=120, period='day'):
    """fetchers.xueqiu.kline 的等价物, 直接透传 sources (含 begin 修复)"""
    return client().xueqiu_kline(symbol, period, count)


def kline(code, count=120, period='day'):
    """按 6 位代码取 K 线 (内部归一前缀)"""
    return get_kline(_xq_symbol(code), count, period)


# ── 公司资料 ────────────────────────────────────────────────────────

def f10_company(code):
    return client().xueqiu_company(_xq_symbol(code)).get('data') or {}


def f10_business(code):
    return client().xueqiu_business_analysis(_xq_symbol(code)).get('data') or {}


def get_company(code):
    return client().cninfo_company_profile(code).get('data') or {}


# ── 行业 / 板块 ─────────────────────────────────────────────────────

def get_industry(symbol):
    """单股所属行业: {name, code, pct}"""
    d = client().xueqiu_industry(_xq_symbol(symbol)).get('data') or {}
    items = d.get('items') or []
    if not items:
        return {'name': '', 'code': '', 'pct': None}
    it = items[0]
    return {'name': it.get('ind_name') or '', 'code': it.get('ind_code') or '',
            'pct': it.get('percent')}


def industry(code):
    return get_industry(code)


# ── 公告 / 资讯 ─────────────────────────────────────────────────────

def announcements(code, days=7, keyword='', page=1):
    """近 days 天公告; keyword 非空则当标题过滤 (fetchers 原签名)"""
    from datetime import datetime, timedelta
    c = client()
    end = datetime.now()
    start = end - timedelta(days=int(days))
    r = c.cninfo_announcement(
        code,
        se_date=f'{start:%Y-%m-%d}~{end:%Y-%m-%d}',
        page=page, page_size=30,
    )
    out = []
    for a in (r.get('data') or {}).get('announcements') or []:
        title = a.get('announcementTitle') or a.get('title') or ''
        if keyword and keyword not in title:
            continue
        out.append({'title': title,
                    'date': (a.get('announcementTime') or a.get('adjunctUrl') or '')[:10],
                    'url': a.get('adjunctUrl') or ''})
    return out


# ── 排行 (新浪) ─────────────────────────────────────────────────────

def rank_list(kind='涨幅榜', count=20):
    """新浪排行榜; kind 保留 fetchers 的中文入参, 内部走 sina_market_sort"""
    mapping = {'涨幅榜': '涨幅', '跌幅榜': '跌幅', '成交额榜': '成交额',
               '换手率榜': '换手', '量比榜': '量比'}
    d = client().sina_market_sort(mapping.get(kind, '涨幅'), count=count).get('data')
    return _sina_rows(d)


def _sina_rows(d):
    rows = []
    it = (d or {}).get('list') if isinstance(d, dict) else d
    for r in (it or []):
        if isinstance(r, dict):
            rows.append(r)
    return rows


# ── 同花顺板块 ──────────────────────────────────────────────────────

def ths_industry_list():
    """行业板块列表; sources 版本补了 code/pct/leader (fetchers 只提取了名字)"""
    return client().ths_industry_list().get('data') or []


def ths_industry_kline(code, year=None):
    return client().ths_bk_kline(code, year or _this_year()).get('data') or {}


def _this_year():
    from datetime import date
    return date.today().year


# ── 工具 ────────────────────────────────────────────────────────────

def _xq_symbol(code):
    """6 位代码 -> 雪球 symbol"""
    from webtool.stock.bridge.sources.xueqiu import XueqiuSource
    return XueqiuSource._norm(code)


# ── 调用方用的名字别名 ───────────────────────────────────────────
# 调用方 (analysis/、screening/) 沿用 fetchers 时代的命名, 这里补齐,
# 免得为了改名字去动 14 个调用点。函数名不同但语义一一对应。

def kline_list(code, count=120, period='day'):
    """展平成调用方要的 dict 列表。

    雪球 v5 的 item 是位置数组:
        [时间戳, 开, 收, 高, 低, 涨额, 涨跌幅, 换手率, 成交额, ...]
    而 analysis/ 与 screening/ 全部按 `k['date'] / k['close'] / k['high']`
    取值 —— 透传数组会让下游把 int 当日期用, 所以这层展平不能省。
    """
    r = kline(code, count=count, period=period)
    data = (r or {}).get('data') or {}
    out = []
    for it in data.get('item') or []:
        if not isinstance(it, (list, tuple)) or len(it) < 9:
            continue
        out.append({
            'date': _ymd(it[0]),
            'open': it[1], 'close': it[2], 'high': it[3], 'low': it[4],
            'chg': it[5], 'pct': it[6], 'turnover': it[7], 'amount': it[8],
            'volume': it[9] if len(it) > 9 else None,
        })
    return {'symbol': data.get('symbol', _xq_symbol(code)),
            'period': data.get('period', period),
            'count': len(out), 'items': out}


def _ymd(ms):
    """毫秒时间戳 → YYYY-MM-DD (调用方当日期字符串用)"""
    import time as _t
    return _t.strftime('%Y-%m-%d', _t.localtime(ms / 1000))


def company_intro(code):
    """fetchers.cninfo.company_intro 的等价物"""
    return get_company(code)


def industry_list():
    """fetchers.ths.industry_list 的等价物 (同花顺行业板块)"""
    return ths_industry_list()


def industry_kline(code, year=None):
    """fetchers.ths.industry_kline 的等价物"""
    return ths_industry_kline(code, year=year)


def industry_detail(code):
    """fetchers.ths.industry_detail 的等价物"""
    return ths_industry_kline(code)
