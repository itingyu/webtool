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
MA_COLORS = ('#e8a33d', '#3d7de8', '#9a5cf0', '#d94f8a',
             '#12a3a3', '#b0743a')

FIELDS = ('date', 'open', 'close', 'high', 'low', 'volume')
# 文字白描边: 压在 K 线/网格上也读得清
HALO = (' paint-order="stroke" stroke="#ffffff" stroke-width="3" '
        'stroke-linejoin="round"')


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
                     width=980, price_h=420, vol_h=110, bars=None,
                     ma_rows=None, macd=False, time_lines=True,
                     extreme_labels='both'):
    """rows: normalize_rows() 的输出; 返回 SVG 文本

    `ma_rows` 是均线的计算区间 (通常比 rows 多带一段区间前的历史):
    用 --start 截取时, 若只拿可见的 N 根算 MA20, 前 19 根会没有均线值,
    图上看就是"均线从第 20 根才开始" —— 不是数据缺失, 是窗口不够。
    """
    rows = normalize_rows(rows)
    # --ma 传来的是字符串 ('5,10,20' 拆出来的), 这里统一成整数; 非法值直接丢,
    # 免得一个手滑的 'ma5' 让整张图报错
    ma = [int(str(x).strip()) for x in (ma or []) if str(x).strip().isdigit()
          and int(str(x).strip()) > 0]

    if bars and bars > 0:
        rows = rows[-bars:]
    if not rows:
        return ('<svg xmlns="http://www.w3.org/2000/svg" width="480" height="80">'
                '<text x="16" y="46" font-family="sans-serif" font-size="14" '
                f'fill="{AXIS}">{html.escape(title or "K线")}: 无数据</text></svg>')

    ma = [int(m) for m in (ma or ()) if int(m) > 0]
    top, left, right = 54, 62, 74
    bottom = 62 if time_lines else 46
    vol_top = top + price_h + 12      # 价量之间收紧, 别留一大片空白
    macd_h = 92 if macd else 0
    macd_top = vol_top + vol_h + (14 if macd else 0)
    h = (macd_top + macd_h if macd else vol_top + vol_h) + bottom
    plot_w = width - left - right

    hi = max(r['high'] for r in rows)
    lo = min(r['low'] for r in rows)
    pad = (hi - lo) * 0.06 or max(abs(hi) * 0.02, 1.0)
    hi, lo = hi + pad, lo - pad
    span = hi - lo or 1.0

    full = normalize_rows(ma_rows) if ma_rows else rows
    if len(full) < len(rows):
        full = rows
    mas = {n: _ma(full, n) for n in ma}
    pos = {r['date']: i for i, r in enumerate(full)}

    def ma_at(n, date):
        i = pos.get(date)
        vals = mas[n]
        return vals[i] if i is not None and i < len(vals) else None
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

    # 时间边界: 月初重(虚线+月份标签), 每周一轻 —— 先画, 压在蜡烛下面
    slot = plot_w / len(rows)
    if time_lines and len(rows) > 1:
        vbot = (macd_top + macd_h) if macd else (vol_top + vol_h)
        for i, kind in _time_guides(rows):
            gx = left + plot_w * i / len(rows)
            if kind == 'M':
                s.append(f'<line x1="{gx:.1f}" y1="{top}" x2="{gx:.1f}" y2="{vbot:.1f}" '
                         f'stroke="#b9bfd0" stroke-width="1" stroke-dasharray="4 3"/>')
            else:
                s.append(f'<line x1="{gx:.1f}" y1="{top}" x2="{gx:.1f}" y2="{vbot:.1f}" '
                         f'stroke="#dcdfe8" stroke-width="1"/>')

    # 蜡烛
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
    gap = min(64.0, max(36.0, plot_w / max(len(ma), 1)))
    for k, n in enumerate(ma):
        pts = []
        for i, r in enumerate(rows):
            v = ma_at(n, r['date'])
            if v is not None:
                pts.append(f'{px(i):.1f},{py(v):.1f}')
        if pts:
            c = MA_COLORS[k % len(MA_COLORS)]
            s.append(f'<polyline points="{" ".join(pts)}" fill="none" '
                     f'stroke="{c}" stroke-width="1.4"/>')
            s.append(f'<text x="{left + 6 + k * gap:.1f}" y="{top + 14}" '
                     f'font-size="11" fill="{c}">MA{n}</text>')

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

    # ── MACD 副图 (12,26,9) ─────────────────────────────────────
    if macd:
        dif_all, dea_all, hist_all = _macd(full)
        mmax = max((abs(v) for v in hist_all if v is not None), default=0) or 1e-9

        def mvy(v):
            return macd_top + macd_h / 2 - (v / mmax) * (macd_h / 2 - 4)

        s.append(f'<line x1="{left}" y1="{macd_top + macd_h / 2:.1f}" '
                 f'x2="{left + plot_w}" y2="{macd_top + macd_h / 2:.1f}" '
                 f'stroke="{GRID}"/>')
        for k, r in enumerate(rows):
            i = pos.get(r['date'])
            if i is None or hist_all[i] is None:
                continue
            v = hist_all[i]
            c = UP if v >= 0 else DOWN
            y0, y1 = mvy(0), mvy(v)
            s.append(f'<rect x="{px(k) - bw / 2:.1f}" y="{min(y0, y1):.1f}" '
                     f'width="{bw:.1f}" height="{max(abs(y1 - y0), 1):.1f}" '
                     f'fill="{c}" opacity="0.7"/>')
        for vals, c in ((dif_all, '#3d7de8'), (dea_all, '#e8a33d')):
            pts = []
            for k, r in enumerate(rows):
                i = pos.get(r['date'])
                if i is not None and vals[i] is not None:
                    pts.append(f'{px(k):.1f},{mvy(vals[i]):.1f}')
            if pts:
                s.append(f'<polyline points="{" ".join(pts)}" fill="none" '
                         f'stroke="{c}" stroke-width="1.2"/>')
        li = len(full) - 1
        di_v = dif_all[li] if li < len(dif_all) else None
        de_v = dea_all[li] if li < len(dea_all) else None
        lab = (f'MACD(12,26,9)  DIF {di_v:+.3f}  DEA {de_v:+.3f}'
               if di_v is not None and de_v is not None else 'MACD(12,26,9)')
        s.append(f'<line x1="{left}" y1="{macd_top:.1f}" x2="{left + plot_w}" '
                 f'y2="{macd_top:.1f}" stroke="{GRID}"/>')
        s.append(f'<rect x="{left}" y="{macd_top + 2:.1f}" '
                 f'width="{len(lab) * 5.6 + 8:.1f}" height="13" '
                 f'fill="#ffffff" fill-opacity="0.85"/>')
        s.append(f'<text x="{left + 2}" y="{macd_top + 12:.1f}" font-size="10" '
                 f'fill="{AXIS}">{lab}</text>')

    # 月/周分段的最高最低点 (带数值); 放不下就换个位置, 再不行才跳过
    if extreme_labels and len(rows) > 2:
        kinds = ('M', 'W') if extreme_labels == 'both' else (str(extreme_labels)[:1],)
        placed = []                       # 已占位 (x0, y0, x1, y1)
        legend_zone = (left - 6, top - 6, left + 250, top + 26)
        for kind in ('W', 'M'):           # 周先画, 月的压在上面
            if kind not in kinds:
                continue
            for s0, s1, hi_i, lo_i in _segment_extremes(rows, kind):
                if kind == 'W' and (s1 - s0 + 1) * slot < 30:
                    continue              # 一周还不到 26px, 标了也糊成一团
                for idx, is_hi in ((hi_i, True), (lo_i, False)):
                    val = rows[idx]['high'] if is_hi else rows[idx]['low']
                    # 周线只给整数: 一周两根数字挤在几像素里, 两位小数必糊
                    txt = f'{val:.2f}' if kind == 'M' else f'{val:.0f}'
                    half = len(txt) * 3.1 + 3
                    tx, y = px(idx), py(val)
                    # 首选贴着该点外侧, 撞了就翻到另一侧
                    for ty in ((y - 8, y + 16) if is_hi else (y + 16, y - 8)):
                        box = (tx - half, ty - 9, tx + half, ty + 2)
                        if (box[2] > legend_zone[0] and box[0] < legend_zone[2]
                                and box[3] > legend_zone[1]
                                and box[1] < legend_zone[3]):
                            continue      # 别压住 MA 图例
                        if any(not (box[2] < b[0] or box[0] > b[2]
                                    or box[3] < b[1] or box[1] > b[3])
                               for b in placed):
                            continue
                        placed.append(box)
                        s.append(f'<line x1="{tx - 2.2:.1f}" y1="{y:.1f}" '
                                 f'x2="{tx + 2.2:.1f}" y2="{y:.1f}" '
                                 f'stroke="{UP if is_hi else DOWN}" stroke-width="1.8"/>')
                        s.append(f'<text x="{tx:.1f}" y="{ty:.1f}" font-size="9.5" '
                                 f'text-anchor="middle"'
                                 f' paint-order="stroke" stroke="#ffffff" '
                                 f'stroke-width="2.2" stroke-linejoin="round" '
                                 f'fill="{UP if is_hi else DOWN}">{txt}</text>')
                        break

    # 日期轴: 两端必含, 中间均匀取样 —— 按固定步长会漏掉最新的那根
    want = min(6, len(rows))
    idxs = sorted({round(i * (len(rows) - 1) / (want - 1)) for i in range(want)}) \
        if want > 1 else [0]
    for i in idxs:
        s.append(f'<text x="{px(i):.1f}" y="{h - 26}" font-size="11" '
                 f'text-anchor="middle" fill="{AXIS}">{rows[i]["date"][5:]}</text>')
    if time_lines:                      # 月初标签单独一行, 不跟日期挤
        s.append(f'<text x="{left + 2}" y="{h - 10}" font-size="10" '
                 f'fill="{AXIS}">{int(rows[0]["date"][5:7])}月</text>')
        for i, kind in _time_guides(rows):
            if kind != 'M':
                continue
            gx = left + plot_w * i / len(rows)
            if gx > left + plot_w - 24:
                continue
            s.append(f'<text x="{gx + 3:.1f}" y="{h - 10}" font-size="10" '
                     f'fill="{AXIS}">{int(rows[i]["date"][5:7])}月</text>')
    s.append(f'<text x="{width - 8}" y="{h - 8}" font-size="10" '
             f'text-anchor="end" fill="{AXIS}">webtool · {datetime.now():%Y-%m-%d}</text>')
    s.append('</svg>')
    return '\n'.join(s)


def write_kline_svg(path, rows, **kw):
    svg = render_kline_svg(rows, **kw)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(svg)
    return path


def _macd(rows, fast=12, slow=26, sig=9):
    """MACD(12,26,9) → (DIF, DEA, 柱). 柱 = (DIF-DEA)*2, 与通达信一致"""
    closes = [r['close'] for r in rows]
    if not closes:
        return [], [], []

    def ema(vals, n):
        out, a = [], 2.0 / (n + 1)
        prev = vals[0]
        for v in vals:
            prev = v if prev is None else a * v + (1 - a) * prev
            out.append(prev)
        return out

    e1, e2 = ema(closes, fast), ema(closes, slow)
    dif = [a - b for a, b in zip(e1, e2)]
    dea = ema(dif, sig)
    hist = [(a - b) * 2 for a, b in zip(dif, dea)]
    return dif, dea, hist


def _time_guides(rows):
    """按月/周切分: [(bar_index, 'M'|'W')] —— 月初与 ISO 周切换处"""
    out = []
    for i in range(1, len(rows)):
        a, b = rows[i - 1]['date'], rows[i]['date']
        if a[:7] != b[:7]:
            out.append((i, 'M'))
            continue
        try:
            wa = datetime.strptime(a, '%Y-%m-%d').isocalendar()[:2]
            wb = datetime.strptime(b, '%Y-%m-%d').isocalendar()[:2]
        except ValueError:
            continue
        if wa != wb:
            out.append((i, 'W'))
    return out


def _segment_extremes(rows, kind):
    """按月/周切段, 返回 [(start_i, end_i, 最高价_i, 最低价_i)]"""
    def key(d):
        if kind == 'M':
            return d[:7]
        try:
            return datetime.strptime(d, '%Y-%m-%d').isocalendar()[:2]
        except ValueError:
            return d

    out, start = [], 0
    for i in range(1, len(rows) + 1):
        if i == len(rows) or key(rows[i]['date']) != key(rows[start]['date']):
            seg = range(start, i)
            hi = max(seg, key=lambda j: rows[j]['high'])
            lo = min(seg, key=lambda j: rows[j]['low'])
            out.append((start, i - 1, hi, lo))
            start = i
    return out
