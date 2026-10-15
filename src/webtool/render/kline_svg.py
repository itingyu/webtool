"""K 线 SVG 渲染: 零依赖手写 SVG (蜡烛 + 均线 + 量能 + 十字轴)

为什么不用 matplotlib: 沙盒和用户机器上都没有图形栈, 而 SVG 是纯文本 ——
不用装包、不用字体文件, 生成即可在 app 里预览, 也能直接贴进 HTML 报告。

标的约定: 红涨绿跌 (A 股习惯), 上影/下影用细线, 实体用矩形。
"""
import html
from datetime import datetime

UP = '#e2453c'      # 涨
DOWN = '#17a673'    # 跌
GRID = '#e8e8ea'
AXIS = '#8a8f99'
INK = '#22242a'
MA_COLORS = ('#e8a33d', '#3d7de8', '#9a5cf0', '#d94f8a')

FIELDS = ('date', 'open', 'close', 'high', 'low', 'volume')


def normalize_rows(rows):
    """各源 K 线形状不一 → 统一成 dict 列表

    tencent: [date, open, close, high, low, volume] (字符串)
    em/xueqiu: [date, open, close, high, low, volume, ...] 或已是 dict
    """
    out = []
    for r in rows or []:
        if isinstance(r, dict):
            try:
                d = {'date': str(r.get('date') or r.get('time') or '')[:10]}
                for f in ('open', 'close', 'high', 'low'):
                    d[f] = float(r[f])
                d['volume'] = float(r.get('volume') or 0)
            except (KeyError, TypeError, ValueError):
                continue
        elif isinstance(r, (list, tuple)) and len(r) >= 6:
            try:
                d = {'date': str(r[0])[:10], 'open': float(r[1]),
                     'close': float(r[2]), 'high': float(r[3]),
                     'low': float(r[4]), 'volume': float(r[5] or 0)}
            except (TypeError, ValueError):
                continue
        else:
            continue
        if d['high'] < d['low']:           # 个别源字段顺序不一致时兜底
            d['high'], d['low'] = d['low'], d['high']
        out.append(d)
    return out


def _ma(rows, n):
    """前 n-1 个点没有均线值 → None (不画, 也不补 0 误导人)"""
    closes = [r['close'] for r in rows]
    out, acc = [], 0.0
    for i, c in enumerate(closes):
        acc += c
        if i >= n:
            acc -= closes[i - n]
        out.append(acc / n if i >= n - 1 else None)
    return out


def _fmt_vol(v):
    for unit, div in (('亿', 1e8), ('万', 1e4)):
        if abs(v) >= div:
            return f'{v / div:.2f}{unit}'
    return f'{v:.0f}'


def render_kline_svg(rows, title='', subtitle='', ma=(5, 10, 20),
                     width=980, price_h=420, vol_h=110, bars=None):
    """rows: normalize_rows() 的输出; 返回 SVG 文本"""
    rows = normalize_rows(rows)
    if bars and bars > 0:
        rows = rows[-bars:]
    if not rows:
        return ('<svg xmlns="http://www.w3.org/2000/svg" width="480" height="80">'
                '<text x="16" y="46" font-family="sans-serif" font-size="14" '
                f'fill="{AXIS}">{html.escape(title or "K线")}: 无数据</text></svg>')

    ma = [int(m) for m in (ma or ()) if int(m) > 0]
    top, left, right, bottom = 54, 62, 74, 46
    vol_top = top + price_h + 26
    h = vol_top + vol_h + bottom
    plot_w = width - left - right

    hi = max(r['high'] for r in rows)
    lo = min(r['low'] for r in rows)
    pad = (hi - lo) * 0.06 or max(abs(hi) * 0.02, 1.0)
    hi, lo = hi + pad, lo - pad
    span = hi - lo or 1.0

    mas = {n: _ma(rows, n) for n in ma}
    vmax = max(r['volume'] for r in rows) or 1.0

    def px(i):
        return left + plot_w * (i + 0.5) / len(rows)

    def py(p):
        return top + price_h * (hi - p) / span

    def vy(v):
        return vol_top + vol_h * (1 - v / vmax)

    s = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{h}" '
         f'viewBox="0 0 {width} {h}" font-family="-apple-system,Helvetica,Arial,sans-serif">',
         f'<rect width="{width}" height="{h}" fill="#fff"/>']

    # 标题
    last = rows[-1]
    prev = rows[-2] if len(rows) > 1 else last
    chg = (last['close'] - prev['close']) / prev['close'] * 100 if prev['close'] else 0.0
    color = UP if chg >= 0 else DOWN
    s.append(f'<text x="{left}" y="24" font-size="16" font-weight="600" fill="{INK}">'
             f'{html.escape(title)}</text>')
    s.append(f'<text x="{left}" y="44" font-size="12" fill="{color}">'
             f'{html.escape(subtitle)}</text>')
    s.append(f'<text x="{left + plot_w}" y="24" font-size="14" text-anchor="end" '
             f'fill="{color}">{last["close"]:.2f}  {chg:+.2f}%</text>')

    # 价格网格 + 左轴
    for k in range(5):
        p = hi - span * k / 4
        y = py(p)
        s.append(f'<line x1="{left}" y1="{y:.1f}" x2="{left + plot_w}" y2="{y:.1f}" '
                 f'stroke="{GRID}"/>')
        s.append(f'<text x="{left - 8}" y="{y + 4:.1f}" font-size="11" text-anchor="end" '
                 f'fill="{AXIS}">{p:.2f}</text>')

    # 蜡烛
    slot = plot_w / len(rows)
    bw = max(slot * 0.62, 1.0)
    for i, r in enumerate(rows):
        up = r['close'] >= r['open']
        c = UP if up else DOWN
        x = px(i)
        tip = (f'{r["date"]}  开{r["open"]:.2f} 高{r["high"]:.2f} '
               f'低{r["low"]:.2f} 收{r["close"]:.2f} 量{_fmt_vol(r["volume"])}')
        s.append(f'<g><title>{html.escape(tip)}</title>')
        s.append(f'<line x1="{x:.1f}" y1="{py(r["high"]):.1f}" x2="{x:.1f}" '
                 f'y2="{py(r["low"]):.1f}" stroke="{c}" stroke-width="1"/>')
        y1, y2 = py(max(r['open'], r['close'])), py(min(r['open'], r['close']))
        if y2 - y1 < 1.0:
            y2 = y1 + 1.0
        s.append(f'<rect x="{x - bw / 2:.1f}" y="{y1:.1f}" width="{bw:.1f}" '
                 f'height="{y2 - y1:.1f}" fill="{c if not up else "#fff"}" '
                 f'stroke="{c}" stroke-width="1"/></g>')

    # 均线
    for k, n in enumerate(ma):
        pts = ' '.join(f'{px(i):.1f},{py(v):.1f}'
                       for i, v in enumerate(mas[n]) if v is not None)
        if pts:
            s.append(f'<polyline points="{pts}" fill="none" '
                     f'stroke="{MA_COLORS[k % len(MA_COLORS)]}" stroke-width="1.4"/>')
            lx = left + 6 + k * 62
            s.append(f'<text x="{lx}" y="{top + 14}" font-size="11" '
                     f'fill="{MA_COLORS[k % len(MA_COLORS)]}">MA{n}</text>')

    # 最新价虚线
    ly = py(last['close'])
    s.append(f'<line x1="{left}" y1="{ly:.1f}" x2="{left + plot_w}" y2="{ly:.1f}" '
             f'stroke="{color}" stroke-width="1" stroke-dasharray="4 3" opacity="0.8"/>')
    s.append(f'<text x="{left + plot_w + 6}" y="{ly + 4:.1f}" font-size="11" '
             f'fill="{color}">{last["close"]:.2f}</text>')

    # 量能
    s.append(f'<line x1="{left}" y1="{vol_top + vol_h:.1f}" x2="{left + plot_w}" '
             f'y2="{vol_top + vol_h:.1f}" stroke="{AXIS}"/>')
    s.append(f'<text x="{left - 8}" y="{vol_top + 12}" font-size="11" '
             f'text-anchor="end" fill="{AXIS}">{_fmt_vol(vmax)}</text>')
    for i, r in enumerate(rows):
        c = UP if r['close'] >= r['open'] else DOWN
        y = vy(r['volume'])
        s.append(f'<rect x="{px(i) - bw / 2:.1f}" y="{y:.1f}" width="{bw:.1f}" '
                 f'height="{vol_top + vol_h - y:.1f}" fill="{c}" opacity="0.72"/>')

    # 日期轴: 两端必含, 中间均匀取样 —— 按固定步长会漏掉最新的那根
    want = min(6, len(rows))
    idxs = sorted({round(i * (len(rows) - 1) / (want - 1)) for i in range(want)}) \
        if want > 1 else [0]
    for i in idxs:
        s.append(f'<text x="{px(i):.1f}" y="{h - 26}" font-size="11" '
                 f'text-anchor="middle" fill="{AXIS}">{rows[i]["date"][5:]}</text>')
    s.append(f'<text x="{width - 8}" y="{h - 8}" font-size="10" '
             f'text-anchor="end" fill="{AXIS}">webtool · {datetime.now():%Y-%m-%d}</text>')
    s.append('</svg>')
    return '\n'.join(s)


def write_kline_svg(path, rows, **kw):
    svg = render_kline_svg(rows, **kw)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(svg)
    return path
