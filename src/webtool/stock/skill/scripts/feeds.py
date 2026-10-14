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
    """近 days 天公告; keyword 非空则当标题过滤 (fetchers 原签名)

    源: 东财 np-anotice (稳)。巨潮 hisAnnouncement/query 对本沙盒出口
    稳定回空 (orgId 查得到、公告列表恒 0 条, 已多轮复测), 巨潮只留作
    cninfo_announcement 直调的后备。
    """
    from datetime import datetime, timedelta
    c = client()
    end = datetime.now()
    start = end - timedelta(days=int(days))
    # 东财时间窗参数对部分时段不稳定 (9/14~10/14 窗口回 0, 无窗口有数据),
    # 所以不带时间窗拉 30 条, 回来按 days 过滤 —— 30 条足够覆盖 7~30 天
    r = c.np_notice_ann(code, page_size=30, page_index=page)
    if not r.get('ok'):                       # 东财失败 → 回退巨潮
        r = c.cninfo_announcement(
            code, se_date=f'{start:%Y-%m-%d}~{end:%Y-%m-%d}',
            page=page, page_size=30)
        src = 'cninfo'
    else:
        src = 'em'
    out = []
    if src == 'em':
        for a in ((r.get('data') or {}).get('data') or {}).get('list') or []:
            date = (a.get('notice_date') or '')[:10]
            if date and date < f'{start:%Y-%m-%d}':
                continue                       # 早于窗口, 丢
            title = a.get('title') or ''
            if keyword and keyword not in title:
                continue
            out.append({'title': title, 'date': date,
                        'url': (a.get('attach_url') or '')})
    else:
        for a in (r.get('data') or {}).get('announcements') or []:
            title = a.get('announcementTitle') or a.get('title') or ''
            if keyword and keyword not in title:
                continue
            out.append({'title': title,
                        'date': _ann_date(a),
                        'url': a.get('adjunctUrl') or ''})
    return out


def _ann_date(a):
    """公告日期归一成 YYYY-MM-DD。

    announcementTime 在 cninfo 源里是 epoch 毫秒 **int** (cninfo.py 原样透传),
    直接 [:10] 会 TypeError。URL 形态 (…/2026-10-14/…) 才适合切片。
    """
    t = a.get('announcementTime')
    if isinstance(t, (int, float)) and t > 0:
        from datetime import datetime as _dt
        return _dt.fromtimestamp(t / 1000).strftime('%Y-%m-%d')
    if isinstance(t, str) and t.isdigit() and len(t) >= 13:
        from datetime import datetime as _dt
        return _dt.fromtimestamp(int(t) / 1000).strftime('%Y-%m-%d')
    return (t or a.get('adjunctUrl') or '')[:10]


# ── 排行 (新浪) ─────────────────────────────────────────────────────

def rank_list(kind='涨幅榜', count=20):
    """新浪排行榜; kind 保留 fetchers 的中文入参, 内部走 sina_market_sort

    原先写的是 `sina_market_sort(mapping.get(kind,'涨幅'), count=count)` ——
    中文 kind 被当成 node 下发 (node 要的是 hs_a 这样的节点名), 而 count 又
    绑到了 num 上, 真正的 sort 落到默认值。参数错位, 取回空。
    """
    mapping = {'涨幅榜': ('changepercent', 0), '跌幅榜': ('changepercent', 1),
               '成交额榜': ('amount', 0), '成交量榜': ('volume', 0),
               '换手率榜': ('turnoverratio', 0), '量比榜': ('volume', 0)}
    sort, asc = mapping.get(kind, ('changepercent', 0))
    d = client().sina_market_sort(
        node='hs_a', num=count, sort=sort, asc=asc).get('data')
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
    """行业板块列表 (sources 版: 只有板块名列表)"""
    return client().ths_industry_list().get('data') or []


def ths_industry_rows(limit=10):
    """行业板块结构化行: [{name, pct, up, down, leader, leader_pct}]

    sources/ths.py::ths_industry_list 只回 `{'names': [...]}` —— 板块名,
    没有涨跌幅也没有领涨股。但本项目的调用方 (screening/) 要的是
    name/pct/leader 这套字段, 原先靠一句 "sources 版本补了 code/pct/leader"
    的注释蒙混, 实际 short_pool 直接 KeyError/切片失败。

    这里按同花顺 thshy 列表页的真实列序解析:
      序号 | 板块 | 涨跌幅% | 成交量(万手) | 成交额(亿) | 净流入(亿)
      | 上涨家数 | 下跌家数 | 均价 | 领涨股 | 最新价 | 涨跌幅%

    **领涨股代码这个接口拿不到** —— td 里只有名字, 没有 /stock/detail/code/
    链接, 所以 leader_code 恒为空, 调用方必须自己判空。
    """
    import re
    c = client()
    r = c._ths_data('/thshy/index/field/199112/order/desc/page/1/ajax/1/free/1/',
                    host='q.10jqka.com.cn')
    html = (r.get('data') or {}).get('html') or ''
    if not html:
        # q 站偶发回 401 验证页 (html 为空), 换 v cookie 重试一次
        # (实测带 Cookie: v=xxx 可过, sources 层会话缺这个头)
        import requests as _rq
        from webtool.stock.bridge.sources import _routing
        s = _rq.Session()
        s.proxies = _routing.proxies_for('https://q.10jqka.com.cn/') or {}
        s.headers.update({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
                          'Referer': 'https://q.10jqka.com.cn/',
                          'Cookie': 'v=04c14a7127bb44e8b1d99bcbd2735b30'})
        try:
            resp = s.get('https://q.10jqka.com.cn/thshy/index/field/199112/'
                         'order/desc/page/1/ajax/1/free/1/', timeout=10)
            if resp.status_code == 200 and len(resp.content) > 1000:
                html = resp.content.decode('gbk', errors='replace')
        except Exception:
            pass
    if not html:
        return []
    m = re.search(r'<tbody.*?</tbody>', html, re.S)
    if not m:
        return []
    rows = []
    for tr in re.findall(r'<tr.*?</tr>', m.group(0), re.S):
        tds = re.findall(r'<td[^>]*>(.*?)</td>', tr, re.S)
        if len(tds) < 12:
            continue
        cells = [re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', t)).strip()
                 for t in tds]

        def _f(v):
            try:
                return float(v)
            except (TypeError, ValueError):
                return None
        rows.append({
            'rank': cells[0],
            'name': cells[1],
            'pct': _f(cells[2]),
            'turnover': _f(cells[4]),
            'up': _f(cells[6]),
            'down': _f(cells[7]),
            'leader': cells[9],
            'leader_pct': _f(cells[11]),
            'leader_code': '',      # 该接口不返回, 恒空 (见 docstring)
        })
        if len(rows) >= max(int(limit or 0), 1):
            break
    return rows


def ths_industry_kline(code, year=None):
    return client().ths_bk_kline(code, year or _this_year()).get('data') or {}


def _this_year():
    from datetime import date
    return date.today().year


# ── 工具 ────────────────────────────────────────────────────────────

def _xq_symbol(code):
    """6 位代码 -> 雪球 symbol

    归一只有一处事实来源: sources/_symbol.py。原先这里调
    `XueqiuSource._norm(code)` —— 该类没有这个方法, 一调就 AttributeError,
    stock analyze / screen 的 K 线与行业链路全断在该行。
    """
    from webtool.stock.bridge.sources._symbol import xueqiu as _xq
    return _xq(code)


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
    # 列序以雪球 column 为准 (不同品种可能增减列), 不写死下标:
    #   [timestamp, volume, open, high, low, close, chg, percent,
    #    turnoverrate, amount, volume_post, amount_post]
    # 原先按 [开,收,高,低] 猜的位置是错的 —— open 实际在 [2],
    # close 在 [5], 之前展平出来的 OHLC 全部错位
    cols = data.get('column') or ['timestamp', 'volume', 'open', 'high',
                                  'low', 'close', 'chg', 'percent',
                                  'turnoverrate', 'amount']
    ix = {name: i for i, name in enumerate(cols)}

    def _g(it, name, default=None):
        i = ix.get(name)
        return it[i] if i is not None and i < len(it) else default
    out = []
    for it in data.get('item') or []:
        if not isinstance(it, (list, tuple)) or len(it) < 6:
            continue
        out.append({
            'date': _ymd(_g(it, 'timestamp', 0)),
            'open': _g(it, 'open'), 'close': _g(it, 'close'),
            'high': _g(it, 'high'), 'low': _g(it, 'low'),
            'chg': _g(it, 'chg'), 'pct': _g(it, 'percent'),
            'turnover': _g(it, 'turnoverrate'),
            'amount': _g(it, 'amount'), 'volume': _g(it, 'volume'),
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
    """fetchers.ths.industry_list 的等价物。

    fetchers 版回的是**结构化行** [{name, pct, leader, leader_code, ...}],
    而 sources 版的 ths_industry_list() 只有 {'names': [...]} —— 调用方
    (screening/short_pool) 要按 leader_code 字段取值, 必须给结构化行。
    """
    return industry_rows(limit=30)


def industry_rows(limit=10):
    """结构化行业行; 实现在 ths_industry_rows, 这里是调用方命名入口"""
    return ths_industry_rows(limit=limit)


def industry_kline(code, year=None):
    """fetchers.ths.industry_kline 的等价物"""
    return ths_industry_kline(code, year=year)


def industry_detail(code):
    """fetchers.ths.industry_detail 的等价物"""
    return ths_industry_kline(code)
