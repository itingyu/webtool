"""stock 子命令共用零件: 值格式化、表格切片、K 线取数、参数解析助手"""
"""webtool stock 子命令: 动作分发 + 输出渲染

两座桥 (bridge/engine.py 脚本层 / bridge/srv.py 编排层) 在这里汇合成一个扁平的动作表。动作分三类:

    数据动作  quote pool check calendar flow news announcement financials
              analyze screen risk            —— 走 engine 脚本层
    透传动作  mcp <tool>                     —— 按名调用 24 个动作 (未单独暴露的那些)
    元动作   tools health                    —— 能力清单与两侧探活

输出与 webtool 其他数据命令一致: 数据动作按 args.format 自己渲染 (json 全字段 /
text 行内可读 / markdown 表格), 走 cli.app._run 的 emit 落盘通道。

口径纪律 (从 stock-master 继承, 现由 engine 维护):
  - 接口返回 0/空 不当正常值, 由各桥透传 status, 渲染时显式标注
  - 北向资金不可用必须显式 ⚠, 不填 0
  - 池/榜单类结果必带数据日 (date), 涨停池尤其 —— 接口对无效日期会静默回旧数据
"""
import json
import re

from webtool.stock.bridge import http as _http



def _norm_fmt(v, default='text'):
    return v or default

def _unresolved(out):
    """检测"取数层回了但没解析出结构"的情况。

    engine 的 clients 把上游载荷原样透传, 所以会碰到两种形状:
    同花顺 stockpage 是 SPA, 上游站点解析不出列表就把 100KB 原始 HTML 塞进 data.html;
    另一路把结构化结果 json.dumps 成了字符串塞进 data。
    这两种都不是"没数据", 强行当结果渲染会把 HTML 噪声喂给 Agent ——
    按硬约束第 9 条显式标注, 由调用方决定是换源还是自行解析。
    """
    if not isinstance(out, dict):
        return None
    if not out.get('ok', True):
        return out.get('err') or out.get('error') or '接口返回失败'
    data = out.get('data')
    if isinstance(data, str) and data.lstrip()[:1] in '{[':
        try:
            return _unresolved(json.loads(data))
        except json.JSONDecodeError:
            return None
    if isinstance(data, dict):
        if data.get('error'):
            return f'数据源错误: {data["error"]}'
        if _table_of(data):
            return None                     # headers+rows 表结构, 各动作自己渲染
        if data.get('html') and _items_of(data) is None:
            return (f'源返回原始 HTML 未解析出条目 ({len(data["html"])} 字符, '
                    f'html_len={data.get("html_len")}); 换 news 源或用 webtool fetch 自行解析')
    return None

def _table_of(data):
    """headers+rows 表结构 (同花顺资金流)。识别到就返回 (headers, rows) 供渲染。"""
    if isinstance(data, dict) and isinstance(data.get('headers'), list) \
            and isinstance(data.get('rows'), list):
        return data['headers'], data['rows']
    return None

def _code(args, required=True):
    """单股动作取代码: 用位置参数 codes 的第一项。

    这些动作只对一只股票, 但 CLI 统一用 codes 位置参数收 (quote/check/risk 是
    多股), 这里取首个并校验 —— 没给就报错退 2, 不把空代码丢给数据源。
    required=False 用于 report/diagram 这类既可单股又可不带代码的动作。
    """
    codes = getattr(args, 'codes', None) or []
    if not codes:
        if not required:
            return None
        raise ValueError('需要一个股票代码, 例: webtool stock analyze 600519')
    return codes[0]

def _http_client(args):
    """每次动作新建连接, 避免跨动作串 cookie"""
    return _http.Http(timeout=getattr(args, 'http_timeout', None) or 20)

_DATA_DOMAINS = {
    '行情':    ('实时/历史行情, 指数点位', '行情快照',
               r'stock_zh_a_(spot|hist|minute|tick)|stock_zh_index|index_zh_a'
               r'|stock_bid|stock_individual_info|stock_sh_|stock_sz_|stock_bj_'
               r'|stock_hk_(spot|hist)|stock_us_(spot|hist)|stock_spot'),
    '龙虎榜':  ('龙虎榜/营业部/机构席位', '排行选股', r'lhb'),
    '资金流':  ('主力/北向/两融资金', '资金流向',
               r'fund_flow|money_flow|hsgt|margin|north|capital|stock_em_hy'
               r'|stock_sector_fund'),
    '财报':    ('三大报表/财务指标/业绩', '财务报表',
               r'indicator|report_|financial|balance|income|cashflow'
               r'|yysr|profit|zcfzb|xjllb|yjbb|yjkb|performance'),
    '股东':    ('十大股东/高管/股本', '股东股本',
               r'holder|shareholder|gdfx|gdhs|sharehold|restricted|unlock'
               r'|equity_change'),
    '板块':    ('行业/概念板块与成分', '板块行业',
               r'board|bk_|sector|industry|concept|stock_board'),
    '选股排行': ('排行/筛器/涨幅榜', '排行选股',
               r'rank|screen|top|screener|top_list|stock_zt|stock_dt'
               r'|stock_tfp|stock_dxsyl|stock_hot'),
    '公告资讯': ('公告/新闻/研报/电话会', '公告资讯',
               r'notice|announcement|news|info_|telegraph|report_'
               r'|research|stock_reply|conference'),
    '债券基金': ('债券/基金/ETF/理财', '其他/入口',
               r'bond_|cb_|fund_|etf|lof|convert|amc|amac'),
    '期货期权': ('期货/期权/贵金属', '其他/入口',
               r'futures|option|zh_|gue|gold|spot_goods|energy'),
    '外汇数字币': ('外汇/汇率/加密货币', '其他/入口',
               r'forex|currency|fx_|crypto|btc|coin'),
    '宏观':    ('宏观/行业景气/全球指标', '其他/入口',
               r'macro|gdp|cpi|ppi|pmi|china_|global|sw_|air_|movie|car'
               r'|energy_calendar|article_|fred|sunrise|migration|nlp|bank_'),
    '全球市场': ('港股/美股/中概/全球指数', '指数成分',
               r'hk_|us_|sk_|world|global_idx|usstock|hf_sp|qdii|reits'),
    '指数':    ('中外指数点位/成分/编制', '指数成分',
               r'^index_|_index$|index_value|index_detail'),
    '其他':    ('工具/配置/不便归类', '其他/入口', r'.')
}

def _domain_of_eco(name):
    """eco 接口名 → 域名 (表序先命中先用)"""
    for dom, (_desc, _cat, pat) in _DATA_DOMAINS.items():
        if re.search(pat, name):
            return dom
    return None

def _kline_rows(out):
    """从各源 K 线载荷里取 rows (统一成 render.kline_svg 认的形状)"""
    from webtool.render.kline_svg import normalize_rows
    d = (out or {}).get('data') or {}
    if not isinstance(d, dict):
        return []
    return normalize_rows(d.get('klines') or d.get('rows') or [])

def _kline_title(out, code):
    """源里带的证券名优先 (用户可能只给了代码)"""
    d = (out or {}).get('data') or {}
    qt = d.get('qt') if isinstance(d, dict) else None
    if isinstance(qt, dict):
        for v in qt.values():
            if isinstance(v, (list, tuple)) and len(v) > 2:
                return f'{v[1]} {v[2]}' if v[1] else str(v[2])
    for k in ('name', 'symbol'):
        if isinstance(d, dict) and d.get(k):
            return str(d[k])
    return code or '—'

def _write_kline_chart(out, args, code, bars, full_rows=None):
    from webtool.render.kline_svg import render_kline_svg
    rows = _kline_rows(out)
    period = args.period or 'day'
    cn = {'day': '日线', 'week': '周线', 'month': '月线'}.get(period, period)
    rng = ''
    if rows:
        rng = f' · {rows[0]["date"]} ~ {rows[-1]["date"]}'
    path = getattr(args, 'chart_out', None) or f'{code or "kline"}-{period}.svg'
    svg = render_kline_svg(rows, title=_kline_title(out, code),
                           subtitle=(f'{cn}{rng} · {len(rows)} 根 · '
                                     f'源 {out.get("source") or "—"}'),
                           ma=[m for m in (getattr(args, 'ma', None) or '5,10,20').split(',') if m.strip()],
                           bars=None, ma_rows=full_rows or rows,
                           macd=bool(getattr(args, 'macd', False)))
    return _chart_finish(path, svg, bool(getattr(args, 'png', False)))


def _kline_range(start, end):
    """区间 → 取数根数 (按每周 5 个交易日估 + 余量)

    源普遍只认"根数"不认起止日, 所以先按跨度多取一点, 拿回再按日期裁。
    只给 --end 时不需要往前推很远: 裁到最后 --bars 根即可。
    """
    from datetime import date
    if not start:
        return 600
    try:
        s = date.fromisoformat(start)
        date.fromisoformat(end) if end else date.today()
    except ValueError:
        return 260
    # 源只按"最近 N 根"给数 (腾讯按 count 从今天往前取), 所以根数必须覆盖
    # start→今天, 而不是 start→end —— 否则查一段老区间会取回空集。
    span = max((date.today() - s).days, 1)
    return max(60, min(3000, int(span * 0.72) + 30))


def _row_date(r):
    if isinstance(r, dict):
        return str(r.get('date') or r.get('time') or '')[:10]
    if isinstance(r, (list, tuple)) and r:
        return str(r[0])[:10]
    return ''


def _clip_kline_range(rows, start, end, limit=0):
    """按日期裁 (dict 行与 list 行都认); limit>0 时再取尾部 N 根"""
    out = []
    for r in rows or []:
        d = _row_date(r)
        if start and d < start:
            continue
        if end and d > end:
            continue
        out.append(r)
    if limit and len(out) > limit:
        out = out[-limit:]
    return out


# ── 分时图 / 通用出图 ────────────────────────────────────────────────
def _chart_finish(path, svg, png=False):
    """落盘: .png 走栅格化, 其余写 SVG 原文

    `--png` 但路径没写扩展名时补 .png; 显式给了 .svg 就尊重用户, 不改名。
    """
    low = str(path).lower()
    if low.endswith('.png'):
        from webtool.render.png import svg_to_png
        return svg_to_png(svg, path)
    if png and not low.endswith(('.svg', '.png')):
        path = f'{path}.png'
        from webtool.render.png import svg_to_png
        return svg_to_png(svg, path)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(svg)
    return path


def _intraday_days(out):
    d = (out or {}).get('data') or {}
    return (d.get('days') if isinstance(d, dict) else None) or []


def _limit_prices(code, name, pre):
    """A 股涨跌停价 (封板标注用)

    规则按板块: 主板 10%, 创业板/科创板 20%, 北交所 30%, ST 5%。
    新股上市首日/复牌等无涨跌幅限制的例外不特判 —— 那种日子算出来的线
    也画不上去 (价格没碰到), 不会误标成封板。
    """
    try:
        pre = float(pre or 0)
    except (TypeError, ValueError):
        return None
    if pre <= 0:
        return None
    c = str(code or '')
    nm = str(name or '').upper()
    if 'ST' in nm:
        pct = 0.05
    elif c.startswith(('688', '689', '300', '301')):
        pct = 0.20
    elif c.startswith(('4', '8', '92')):
        pct = 0.30
    else:
        pct = 0.10
    return {'pct': pct, 'up': round(pre * (1 + pct), 2),
            'down': round(pre * (1 - pct), 2)}


def _write_intraday_chart(out, args, code):
    """当日/五日分时图: 左轴价格 + 右轴涨幅 (同一组网格线)"""
    from webtool.render.intraday_svg import render_intraday_svg
    days = _intraday_days(out)
    d = (out or {}).get('data') or {}
    ndays = len(days)
    name = (d.get('name') or '') if isinstance(d, dict) else ''
    title = f'{name} {code}'.strip() or str(code)
    span = days[0]['date'] if days else ''
    if ndays > 1:
        span = f'{days[0]["date"]} ~ {days[-1]["date"]}'
    tag = '五日分时' if ndays > 1 else '分时'
    sub = f'{tag} · {span} · 源 {out.get("source") or "—"}'
    if d.get('preclose'):
        sub += f' · 涨幅基准 {d["preclose"]:.2f}'
    if ndays == 1:
        if int(d.get('gran') or 60) < 60:
            sub += f' · 量柱{int(d["gran"])}秒'
        sub += ' · 含集合竞价' if d.get('auction') else ' · 不含集合竞价'
        if d.get('auction_note'):
            _n = str(d['auction_note'])
            sub += _n if _n.startswith('(') else f' ({_n})'
    default = f'{code or "分时"}-{"五日分时" if ndays > 1 else "分时"}'
    path = getattr(args, 'chart_out', None) or f'{default}.svg'
    cn = d.get('market') == 'cn'
    svg = render_intraday_svg(days, title=title, subtitle=sub,
                              anchor=d.get('preclose'),
                              limits=(None if getattr(args, 'auto_y', False) else
                                      _limit_prices(code, name, d.get('preclose')))
                              if cn else None,
                              closing_auction=cn,
                              macd=bool(getattr(args, 'macd', False)),
                              limit_y=bool(getattr(args, 'limit_y', False)),
                              dma=d.get('dma') or [],
                              mavg=[m for m in (getattr(args, 'mavg', None) or '').split(',')
                                    if m.strip()])
    return _chart_finish(path, svg, bool(getattr(args, 'png', False)))

def _dma_levels(kline_out, spec='5,10,20,60'):
    """从日K取均线档位 [(MA5, 1321.3), ...], 供分时图叠横线"""
    rows = _kline_rows(kline_out)
    if not rows:
        return []
    closes = [r['close'] for r in rows]
    out = []
    for item in str(spec or '').split(','):
        item = item.strip()
        if not item.isdigit():
            continue
        n = int(item)
        if n > 0 and len(closes) >= n:
            out.append((f'MA{n}', round(sum(closes[-n:]) / n, 2)))
    return out


def _intraday_svg(days, d, code, name, tag, span, src, args, title=None,
                  macd=False):
    """分时 SVG 通用构建 (单图与组合图共用, 避免两套排版)"""
    from webtool.render.intraday_svg import render_intraday_svg
    sub = f'{tag} · {span} · 源 {src}'
    if d.get('preclose'):
        sub += f' · 涨幅基准 {d["preclose"]:.2f}'
    if len(days) == 1:
        if int(d.get('gran') or 60) < 60 and '量柱' not in tag:
            sub += f' · 量柱{int(d["gran"])}秒'
        sub += ' · 含集合竞价' if d.get('auction') else ''
    cn = d.get('market') == 'cn'
    return render_intraday_svg(
        days, title=title or (f'{name} {code}'.strip() or str(code)),
        subtitle=sub, anchor=d.get('preclose'),
        limits=(None if getattr(args, 'auto_y', False) else
                _limit_prices(code, name, d.get('preclose'))) if cn else None,
        closing_auction=cn,
        macd=macd,
        dma=([] if len(days) > 1 else (d.get('dma') or [])),
        limit_y=bool(getattr(args, 'limit_y', False)),
        mavg=[m for m in (getattr(args, 'mavg', None) or '5').split(',')
              if m.strip()])


def _write_intraday_combo(outs, args, code, kline=None):
    """一张长图看全: 当日分钟 / 当日细粒度 / 五日

    数据只取一次: 主调用 (gran<60) 里 `days_1m` 是复用下来的分钟序列,
    五日另取一次 —— 总共两次请求, 而不是分别跑三条命令。
    """
    import tempfile
    from pathlib import Path
    from PIL import Image
    from webtool.render.png import svg_to_png

    main = outs[0]
    d = (main or {}).get('data') or {}
    name = d.get('name') or ''
    src = main.get('source') or '—'
    date = (d.get('days') or [{}])[0].get('date') or ''
    root = f'{name} {code}'.strip() or str(code)

    panels = []
    fine = _intraday_days(main)
    d5 = (outs[1] or {}).get('data') if len(outs) > 1 else None
    if d5 and d5.get('days'):
        d5['dma'] = d.get('dma') or []      # 五日同样叠日线均线
        dd = d5['days']
        panels.append((dd, d5, '五日分时',
                       f'{dd[0]["date"]} ~ {dd[-1]["date"]}', root + ' · 五日'))
    gran_n = int(d.get('gran') or 60)
    if gran_n < 60:
        panels.append((fine, d, f'量柱 {gran_n}秒', date,
                       f'{root} · 当日 {gran_n}秒'))
    else:
        panels.append((fine, d, '分时 · 1分钟', date, root + ' · 当日'))

    svgs = []
    krows = _kline_rows(kline) if kline else []
    if krows:
        from webtool.render.kline_svg import render_kline_svg
        show = krows[-120:]                 # 看最近 120 根, 均线用全量预热
        svgs.append(render_kline_svg(
            show, title=f'{root} · 日K',
            subtitle=(f'日线 · {show[0]["date"]} ~ {show[-1]["date"]} · '
                      f'{len(show)} 根 · 源 {(kline or {}).get("source") or "—"}'),
            ma=['5', '10', '20', '60'], ma_rows=krows, macd=True))
    for days, dd, tag, span, title in panels:
        svgs.append(_intraday_svg(days, dd, code, name, tag, span, src, args,
                                  title=title, macd=True))

    tmp = Path(tempfile.mkdtemp(prefix='combo-'))
    imgs = []
    for i, svg in enumerate(svgs):
        p = tmp / f'p{i}.png'
        svg_to_png(svg, str(p), zoom=2)
        imgs.append(Image.open(p).convert('RGB'))
    w = max(i.width for i in imgs)
    gap = 18
    canvas = Image.new('RGB', (w, sum(i.height for i in imgs) + gap * (len(imgs) - 1)),
                       'white')
    y = 0
    for im in imgs:
        canvas.paste(im, (0, y))
        y += im.height + gap
    out = str(getattr(args, 'chart_out', None) or f'{code}-分时三合一.png')
    if not out.lower().endswith('.png'):
        out = out.rsplit('.', 1)[0] + '.png'
    canvas.save(out)
    return out


_IDX_ALIAS = {
    '上证指数': 'sh000001', '上证': 'sh000001', '上证50': 'sh000016',
    '深证成指': 'sz399001', '创业板指': 'sz399006', '科创50': 'sh000688',
    '沪深300': 'sh000300', '中证500': 'sh000905', '中证1000': 'sh000852',
    '北证50': 'bj899050', '国证2000': 'sz399303',
}

def _index_symbol(s):
    """中文别名 / 裸 6 位 → idx:交易所+代码 (编排层 normalize_index 的口径)"""
    s = (s or '').strip()
    if s in _IDX_ALIAS:
        return 'idx:' + _IDX_ALIAS[s]
    if re.fullmatch(r'\d{6}', s) and s[0] in '03':
        return 'idx:' + ('sh' if s[0] == '0' else 'sz') + s
    return s

def _looks_like_list(args):
    return (args.method or '') in ('api', 'sources') and not (args.codes or [])

def _args_dict(args):
    """把 --arg k=v 收成 dict (纯数字留字符串, 同 mcp 动作的口径)"""
    params = {}
    for kv in (getattr(args, 'params', None) or ()):
        if '=' not in kv:
            raise ValueError(f'--arg 需要 k=v 形式, 收到 {kv!r}')
        k, _, v = kv.partition('=')
        params[k.strip()] = _coerce(v)
    return params

def _coerce(v):
    """--arg 的值猜类型。与 cli/mcp.py 的差别: 纯数字一律留字符串。

    股票代码 (600519 / 00700) 恒是字符串标识, 动作参数也按 string 收;
    按 JSON 字面量猜成 int 会被拒 (symbol must be non-empty string, got 600519)。
    其余值 (排序字段/枚举/布尔/嵌套 JSON) 仍按 JSON 解析。
    """
    s = v.strip()
    if not s:
        return v
    if s.isdigit() or (s.startswith('-') and s[1:].isdigit()):
        return s
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        return v

def _passthrough(out, key):
    if isinstance(out, dict) and out.get(key):
        print(out[key])
    elif isinstance(out, dict):
        print(json.dumps(out, ensure_ascii=False, indent=1))
    else:
        print(out)

def _items_of(data, depth=6):
    """从动作返回的载荷里挖出条目列表 (广度优先下钻)。

    嵌套深度不固定: stock_news 是 data.items, stock_announcement 是 data.data.list,
    stock_capital_flow north 是 data.data.data.{hk2sh,sh2hk,...} (无列表)。
    只认显式的条目键 (items/list/rows) —— 其余 dict 键都往下钻一层。
    钻到底还没列表就返回 None 交给调用方标注, 不猜。
    """
    queue = [(data, 0)]
    while queue:
        node, d = queue.pop(0)
        if not isinstance(node, dict) or d > depth:
            continue
        for k in ('items', 'list', 'rows'):
            v = node.get(k)
            if isinstance(v, list):
                return v
        for v in node.values():
            if isinstance(v, dict):
                queue.append((v, d + 1))
    return None

def _fmt_vol(v):
    for unit, div in (('亿', 1e8), ('万', 1e4)):
        if abs(v) >= div:
            return f'{v / div:.2f}{unit}'
    return f'{v:.0f}'

def _j(v, n=200):
    """json.dumps 兜底 —— akshare/efinance 的列里常有 datetime.date、numpy 标量。

    这些类型不是 JSON 原生, 直接 dumps 会 TypeError 崩掉整条命令, 而崩在
    渲染层尤其冤 (数据已经取到了)。所以统一走这里, 非原生类型转字符串。
    """
    def default(o):
        for attr in ('isoformat', 'item'):        # date/datetime → 字符串, numpy 标量 → python
            m = getattr(o, attr, None)
            if callable(m):
                try:
                    return m()
                except Exception:                  # noqa: BLE001
                    pass
        return str(o)
    try:
        return json.dumps(v, ensure_ascii=False, default=default)
    except (TypeError, ValueError):
        return str(v)[:n]



def codes_input(args):
    """多代码动作的输入归一: 显式参数 > '-' / 管道 stdin

    `webtool stock quote -`、`cat codes.txt | webtool stock check` 都到这;
    单股动作 (kline 等) 取首个时也先过这里, 保证 '-' 不会当代码去查。
    """
    codes = list(getattr(args, 'codes', None) or [])
    if codes == ['-'] or not codes:
        from webtool.core import stdin as _stdin
        parsed = _stdin.parse_lines(_stdin.read_input(
            '-' if not codes and _stdin.is_pipe() else (codes[0] if codes else None)))
        if parsed:
            return parsed
        if not codes:
            return []
    return codes
