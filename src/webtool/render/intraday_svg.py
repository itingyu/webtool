"""分时图 SVG 渲染: 当日 / 五日, 零依赖手写 SVG

与 kline_svg 一样不用 matplotlib —— 沙盒和用户机器上都没有图形栈, SVG 是纯文本,
生成即可预览 (要 PNG 走 render.png 转一道)。

版式 (对齐行情软件的习惯):
    ┌ 标题行: 名称 代码 · 现价 涨跌额 涨跌幅
    ├ 价格区: 左轴价格, 右轴涨幅 (同一组网格线, 两条轴同一个 y)
    ├ 量能区: 每分钟成交量, 按该分钟涨跌着色
    └ 时间轴: 单日给关键时点 (开盘/午休/收盘), 五日给日期

纵轴为什么对称: 分时图的"0%"必须落在正中 —— 否则同一只票的 ±1% 看起来不
一样长, 看图的人会误判强弱。所以以昨收为轴心, 取上下最大偏离的较大者。
五日图的价格跨度跨了好几天, 涨幅轴统一以**最后一天**的昨收为基准
(轴上只有一个 %, 混用每天各自的昨收会自相矛盾), 每日自己的昨收用灰虚线画。
"""
import html


UP = '#e2453c'          # 涨
DOWN = '#17a673'        # 跌
FLAT = '#8a8f99'        # 平
GRID = '#ececef'
AXIS = '#8a8f99'
INK = '#22242a'
AVG = '#e8a33d'         # 均价线
DMA_COLORS = ('#5b6b8c', '#8a6d3b', '#7d5a8f', '#4d7a6a')  # 日线均线(暗色, 别跟分时均线撞色)
LINE = '#2f6fd0'        # 价格线 (白底上比红绿更清楚, 颜色交给涨跌标签)
FILL_TOP = '0.28'      # 渐变透明度 (stop-opacity: rsvg 对 rgba() 支持不稳)
FILL_BOT = '0.02'
HALO = (' paint-order="stroke" stroke="#ffffff" stroke-width="3" '
        'stroke-linejoin="round"')
FONT = ("-apple-system,'Noto Sans CJK SC','Source Han Sans SC',"
        "'PingFang SC','Microsoft YaHei',Helvetica,Arial,sans-serif")


def _hf(v):
    """成交量: 手 → 万手/亿手 (A 股口径; 港美股是股, 量级差 100 倍但可读)"""
    v = float(v or 0)
    for unit, div in (('亿', 1e8), ('万', 1e4)):
        if abs(v) >= div:
            return f'{v / div:.2f}{unit}'
    return f'{v:.0f}'


def _pct(p, base):
    return (p / base - 1) * 100 if base else 0.0


def prepare_days(days):
    """清洗: 按时间排序、丢坏点、补均价

    days: [{'date','preclose','points':[{'t','price','avg','vol'}]}]
    """
    out = []
    for d in days or []:
        pts = []
        for p in (d.get('points') or []):
            try:
                price = float(p.get('price'))
            except (TypeError, ValueError):
                continue
            if not price:
                continue
            avg = p.get('avg')
            try:
                avg = float(avg) if avg not in (None, '') else None
            except (TypeError, ValueError):
                avg = None
            try:
                vol = float(p.get('vol') or 0)
            except (TypeError, ValueError):
                vol = 0.0
            pts.append({'t': str(p.get('t') or '')[:5],
                        'price': price, 'avg': avg or price, 'vol': vol})
        if not pts:
            continue
        pts.sort(key=lambda x: x['t'])
        pre = d.get('preclose')
        try:
            pre = float(pre) if pre not in (None, '') else 0.0
        except (TypeError, ValueError):
            pre = 0.0
        if not pre:
            pre = pts[0]['price']
        out.append({'date': str(d.get('date') or '')[:10], 'preclose': pre,
                    'points': pts})
    return out


def render_intraday_svg(days, title='', subtitle='', width=980,
                        price_h=420, vol_h=104, anchor=None,
                        limits=None, closing_auction=False, mavg=(),
                        macd=False, dma=(), limit_y=False):
    """days: prepare 过的 list (1 条=当日, 5 条=五日); 返回 SVG 文本"""
    days = prepare_days(days)
    if not days:
        return ('<svg xmlns="http://www.w3.org/2000/svg" width="480" height="80" '
                f'font-family="{FONT}"><text x="16" y="46" font-size="14" '
                f'fill="{AXIS}">{html.escape(title or "分时")}: 无数据</text></svg>')

    multi = len(days) > 1
    anchor = float(anchor or days[-1]['preclose'])      # 涨幅基准
    allpts = [p for d in days for p in d['points']]
    # 秒级粒度 (gran=30 有 480 根) 时按点数把画布撑宽, 保证每根还有 1px 以上
    maxn = max((len(d.get('points') or []) for d in days), default=0)
    if maxn > 420:
        width = min(2600, max(width, int(maxn * 1.9) + 170))
    last = allpts[-1]
    last_chg = last['price'] - anchor
    last_pct = _pct(last['price'], anchor)
    color = UP if last_chg > 0 else (DOWN if last_chg < 0 else FLAT)

    # ── 价格区间: 以基准对称, 0% 恒在中线 ──────────────────────────
    hi = max(max(p['price'], p['avg']) for p in allpts)
    lo = min(min(p['price'], p['avg']) for p in allpts)
    # 波动小的时候把价格区拉高, 不然再好的取景也是压扁的一条线
    if not multi and anchor and hi > lo:
        amp = (hi - lo) / anchor
        if amp < 0.015:
            price_h = int(price_h * (1.0 + min(0.30, (0.015 - amp) / 0.015 * 0.45)))

    if limits and limits.get('up') and limits.get('down') and not multi:
        up, down = float(limits['up']), float(limits['down'])
        need = max(abs(hi - anchor), abs(anchor - lo)) or anchor * 0.004
        if hi > up or lo < down:                   # 越过涨跌停 (新股/除权) 兜底
            dev = need * 1.08
            ph, pl = anchor + dev, anchor - dev
        elif limit_y or need > (up - anchor) * 0.35:
            # 波动够大才撑满涨跌停: 0% 恒在中线, 幅度一眼可比
            ph, pl = up, down
        else:
            # 只用了一小截 (茅台这种 ±0.4%) 就别硬撑, 否则整屏都是空白
            dev = max(need * 1.10, anchor * 0.004)
            ph, pl = min(anchor + dev, up), max(anchor - dev, down)
    else:
        dev = max(hi - anchor, anchor - lo)
        dev = dev * 1.06 or max(anchor * 0.01, 0.01)
        ph, pl = anchor + dev, anchor - dev
    span = ph - pl

    top, left, right, bottom = 62, 66, 68, 44
    vol_top = top + price_h + 10      # 价量之间只留一线, 少一片空白
    macd_h = 82 if macd else 0
    macd_top = vol_top + vol_h + (12 if macd else 0)
    chart_bot = (macd_top + macd_h) if macd else (vol_top + vol_h)
    h = chart_bot + bottom
    plot_w = width - left - right

    def py(p):
        return top + price_h * (ph - p) / span

    def vy(v, vmax):
        return vol_top + vol_h * (1 - (v / vmax if vmax else 0))

    # x: 每日等宽; 日内按点序 (午休天然被压缩, 不做等时距)
    def xpos(di, frac):
        return left + plot_w * ((di + frac) / len(days))

    s = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{h}" '
         f'viewBox="0 0 {width} {h}" font-family="{FONT}">',
         '<defs><linearGradient id="ig" x1="0" y1="0" x2="0" y2="1">'
         f'<stop offset="0%" stop-color="{LINE}" stop-opacity="{FILL_TOP}"/>'
         f'<stop offset="100%" stop-color="{LINE}" stop-opacity="{FILL_BOT}"/>'
         '</linearGradient></defs>',
         f'<rect width="{width}" height="{h}" fill="#fff"/>']

    # ── 标题 ────────────────────────────────────────────────────
    s.append(f'<text x="{left}" y="26" font-size="17" font-weight="600" '
             f'fill="{INK}">{html.escape(title)}</text>')
    s.append(f'<text x="{left}" y="47" font-size="12" fill="{AXIS}">'
             f'{html.escape(subtitle)}</text>')
    s.append(f'<text x="{left + plot_w}" y="26" font-size="15" text-anchor="end" '
             f'fill="{color}">{last["price"]:.2f}  {last_chg:+.2f}  {last_pct:+.2f}%</text>')
    # 图例 (左上角, 价格区顶)
    # 分时均线是"按分钟价格"的简单均线, 与 K 线的 MA(按日收盘) 不是一回事 ——
    # 所以标签写"均5", 不写 MA5, 免得看的人以为是日线均线。
    mas = [int(str(x)) for x in (mavg or []) if str(x).strip().isdigit()
           and int(str(x)) > 0]
    # 均价线占了橙色, 分时均线从色表第二个开始取, 避免两条线同色
    macols = [c for c in ('#9a5cf0', '#d94f8a', '#12a3a3', '#b0743a')
              if c.lower() not in (AVG.lower(), LINE.lower())]
    lastp = days[-1]['points'][-1]

    def _last_ma(pts, nh):
        mv = [v for v in _price_ma(pts, nh) if v is not None]
        return mv[-1] if mv else None

    lg = ([('价格', LINE),
           (f"均价 {lastp['avg']:.2f}" if lastp.get('avg') else '均价', AVG)]
          + [(f"均{n} {_last_ma(days[-1]['points'], n):.2f}"
              if _last_ma(days[-1]['points'], n) else f'均{n}', macols[k % len(macols)])
             for k, n in enumerate(mas)]
          + [(f'{lab} {float(val):.2f}', DMA_COLORS[k % len(DMA_COLORS)])
             for k, (lab, val) in enumerate(dma or ())
             if pl <= float(val) <= ph])
    legend = []                       # 最后再画, 压在所有底纹之上
    # 图例按内容宽度排, 挤不下就整体压缩间距 (6 条均线时不至于只剩 4 条)
    widths = [21 + len(lab) * 7.0 for lab, _ in lg]
    total = sum(widths) + 12 * (len(lg) - 1)
    avail = plot_w - 16
    fit = 1.0 if total <= avail else max(0.62, avail / total)
    lx = left + 8
    for i, (lab, c) in enumerate(lg):
        legend.append(f'<line x1="{lx}" y1="{top + 12}" x2="{lx + 16 * fit}" '
                      f'y2="{top + 12}" stroke="{c}" stroke-width="2"/>')
        legend.append(f'<text x="{lx + 21 * fit}" y="{top + 16}" '
                      f'font-size="{11 * max(0.85, fit):.1f}"'
                      f'{HALO} fill="{INK}">{lab}</text>')
        lx += (widths[i] + 12) * fit

    # ── 网格 + 双轴 (价格 / 涨幅) ────────────────────────────────
    ticks = 4
    for k in range(ticks + 1):
        p = ph - span * k / ticks
        y = py(p)
        s.append(f'<line x1="{left}" y1="{y:.1f}" x2="{left + plot_w}" y2="{y:.1f}" '
                 f'stroke="{GRID}"/>')
        s.append(f'<text x="{left - 8}" y="{y + 4:.1f}" font-size="11" '
                 f'text-anchor="end" fill="{AXIS}">{p:.2f}</text>')
        pc = _pct(p, anchor)
        if abs(pc) > 0.005:                # 0% 见下方轴心标签, 不重复
            s.append(f'<text x="{left + plot_w + 8}" y="{y + 4:.1f}" font-size="11" '
                     f'fill="{UP if pc > 0 else DOWN}">{pc:+.2f}%</text>')

    # 昨收 (基准) 线
    y0 = py(anchor)
    s.append(f'<line x1="{left}" y1="{y0:.1f}" x2="{left + plot_w}" y2="{y0:.1f}" '
             f'stroke="{AXIS}" stroke-width="1" stroke-dasharray="5 4" opacity="0.75"/>')
    s.append(f'<text x="{left + plot_w + 8}" y="{y0 + 4:.1f}" font-size="11" '
             f'font-weight="600" fill="{AXIS}">0%</text>')
    # 昨收价格直接标在左轴线上, 抄自行情软件的做法
    s.append(f'<text x="{left - 8}" y="{y0 + 4:.1f}" font-size="10.5" '
             f'text-anchor="end"{HALO} fill="{AXIS}">{anchor:.2f}</text>')

    # ── 日线均线 (MA5/10/20/60 等, 横向价格参考) ─────────────────
    # 只画虚线, 数值统一放顶部图例 —— 贴在右侧会正好压在"最后一笔"价格上
    if dma:
        for k, (_lab, val) in enumerate(dma):
            if not (pl <= float(val) <= ph):
                continue
            col = DMA_COLORS[k % len(DMA_COLORS)]
            dy = py(float(val))
            s.append(f'<line x1="{left}" y1="{dy:.1f}" x2="{left + plot_w}" '
                     f'y2="{dy:.1f}" stroke="{col}" stroke-width="1" '
                     f'stroke-dasharray="7 5" opacity="0.6"/>')

    # ── 价格 / 均价 / 量能 ──────────────────────────────────────
    vmax = max((max((p['vol'] for p in d['points']), default=0) for d in days),
               default=0) or 1.0
    day_guides = []          # [(di, [(frac, label, emphasis)])], 时间分界线用
    for di, d in enumerate(days):
        pts = d['points']
        n = len(pts)
        step = (n - 1) or 1

        def xi(j):
            return xpos(di, j / step if n > 1 else 0.5)

        # 每日自己的昨收 (只在五日图里与基准不同时画, 免得刷屏)
        if multi and abs(d['preclose'] - anchor) > 1e-9:
            yp = py(d['preclose'])
            x_end = xpos(di, 1.0)
            s.append(f'<line x1="{xpos(di, 0):.1f}" y1="{yp:.1f}" x2="{x_end:.1f}" '
                     f'y2="{yp:.1f}" stroke="{FLAT}" stroke-width="1" '
                     f'stroke-dasharray="3 4" opacity="0.5"/>')

        # 集合竞价段 (09:15-09:25): 淡底 + 分隔线, 与连续竞价区分开。
        # 数据里只有竞价点时才有; --no-auction 由上游直接剔掉这些点。
        n_auc = 0
        for p in pts:
            if p['t'] < '09:30':
                n_auc += 1
            else:
                break
        if n_auc:
            xa = xpos(di, 0)
            xb = xpos(di, (n_auc - 0.5) / step if n > 1 else 0.5)
            s.append(f'<rect x="{xa:.1f}" y="{top}" width="{max(xb - xa, 1):.1f}" '
                     f'height="{chart_bot - top:.1f}" fill="#eef1f9" '
                     f'fill-opacity="0.55"/>')
            s.append(f'<line x1="{xb:.1f}" y1="{top}" x2="{xb:.1f}" '
                     f'y2="{chart_bot:.1f}" stroke="{GRID}" '
                     f'stroke-dasharray="3 3"/>')
            if not multi:
                s.append(f'<text x="{(xa + xb) / 2:.1f}" y="{top + 44}" font-size="10" '
                         f'text-anchor="middle" fill="{AXIS}">集合竞价</text>')

        bands = _sessions(pts, closing_auction and not multi)
        if not multi:
            for b0, b1, label in bands:
                if label in ('集合竞价', '尾盘竞价'):
                    xa, xb = xpos(di, b0 / step), xpos(di, b1 / step)
                    s.append(f'<rect x="{xa:.1f}" y="{top}" width="{xb - xa:.1f}" '
                             f'height="{chart_bot - top:.1f}" fill="#eef1f9" '
                             f'fill-opacity="0.55"/>')
        # 涨跌停线 + 封板区
        if not multi and limits:
            for side, col in (('up', UP), ('down', DOWN)):
                p_lim = limits.get(side)
                if not p_lim or p_lim > ph or p_lim < pl:
                    continue
                yl = py(p_lim)
                s.append(f'<line x1="{left}" y1="{yl:.1f}" x2="{left + plot_w}" '
                         f'y2="{yl:.1f}" stroke="{col}" stroke-width="1" '
                         f'stroke-dasharray="6 4" opacity="0.6"/>')
                s.append(f'<text x="{left + plot_w - 4}" y="{yl - 4:.1f}" '
                         f'font-size="10" text-anchor="end"{HALO} fill="{col}">'
                         f'{"涨停" if side == "up" else "跌停"} {p_lim:.2f}</text>')
            last_lab = -1e9
            for i0, i1, side in _seal_runs(pts, limits):
                col = UP if side == 'up' else DOWN
                xa, xb = xpos(di, i0 / step), xpos(di, i1 / step)
                yl = py(limits.get(side) or pts[i0]['price'])
                # 贴着封板价的窄条 —— 整块染色会把整个价格区糊成一片
                s.append(f'<rect x="{xa:.1f}" y="{yl - 7:.1f}" '
                         f'width="{max(xb - xa, 1.5):.1f}" height="14" '
                         f'fill="{col}" fill-opacity="0.35"/>')
                cx = (xa + xb) / 2
                if xb - xa > 40 and cx - last_lab > 64:
                    s.append(f'<text x="{cx:.1f}" y="{vol_top - 8}" '
                             f'font-size="10" text-anchor="middle"{HALO} fill="{col}">'
                             f'封板 {pts[i0]["t"]}</text>')
                    last_lab = cx

        guides = _day_guides(pts, multi)
        day_guides.append((di, guides))
        for frac, _lab, emph in guides:
            gx = xpos(di, frac)
            # 分界线要"看得见": 午休最重 (虚线), 开收盘次之, 整点最轻
            if emph == 2:
                col, w, dash, op = '#b9bfd0', 1.3, '4 3', '1'
            elif emph == 3:
                col, w, dash, op = '#d5d9e4', 1, '3 3', '1'
            elif emph == 1:
                col, w, dash, op = '#c8cdd9', 1.1, 'none', '1'
            else:
                col, w, dash, op = '#dfe2ea', 1, 'none', '1'
            s.append(f'<line x1="{gx:.1f}" y1="{top}" x2="{gx:.1f}" '
                     f'y2="{chart_bot:.1f}" stroke="{col}" stroke-width="{w}" '
                     f'stroke-dasharray="{dash}" opacity="{op}"/>')

        base_y = py(max(min(d['preclose'], ph), pl))

        def _runs(seq):
            """按静默期切段: 09:25 撮合完到 09:30 之间没有成交, 折线不能跨过去"""
            run = []
            for j, p in enumerate(seq):
                if run and _is_silent_gap(run[-1][1], p):
                    yield run
                    run = []
                run.append((j, p))
            if run:
                yield run

        for run in _runs(pts):
            x0, x1 = xi(run[0][0]), xi(run[-1][0])
            lp = ' '.join(f'{xi(j):.1f},{py(p["price"]):.1f}' for j, p in run)
            if len(run) > 1:
                s.append(f'<polygon points="{x0:.1f},{base_y:.1f} {lp} '
                         f'{x1:.1f},{base_y:.1f}" fill="url(#ig)" stroke="none"/>')
                s.append(f'<polyline points="{lp}" fill="none" stroke="{LINE}" '
                         f'stroke-width="1.5" stroke-linejoin="round"/>')
            else:
                s.append(f'<circle cx="{x0:.1f}" cy="{py(run[0][1]["price"]):.1f}" '
                         f'r="2.2" fill="{LINE}"/>')
        for run in _runs(pts):
            if len(run) > 1:
                ap = ' '.join(f'{xi(j):.1f},{py(p["avg"]):.1f}' for j, p in run)
                s.append(f'<polyline points="{ap}" fill="none" stroke="{AVG}" '
                         f'stroke-width="1.2"/>')
        # 分时均线 (按分钟价格, 与 K 线 MA 不同口径); 跨日不连
        for k, nh in enumerate(mas):
            mv = _price_ma(pts, nh)
            seg = ' '.join(f'{xi(j):.1f},{py(v):.1f}'
                           for j, v in enumerate(mv) if v is not None)
            if seg:
                s.append(f'<polyline points="{seg}" fill="none" '
                         f'stroke="{macols[k % len(macols)]}" '
                         f'stroke-width="1.1" opacity="0.95"/>')

        # 每分钟量柱: 按该分钟相对上一分钟的涨跌着色
        # 宽度跟着槽位走, 太密就退化成 1px 竖线 —— 宁可细, 绝不让柱子互相压住
        slot = plot_w / len(days) / n
        bw = slot * 0.66
        thin = bw < 1.2
        prev = d['preclose']          # 首根跟昨收比, 别跟自己比 (恒红)
        for j, p in enumerate(pts):
            c = UP if p['price'] >= prev else DOWN
            prev = p['price']
            y = vy(p['vol'], vmax)
            if p['vol'] <= 0:
                continue
            if thin:
                x = xi(j)
                s.append(f'<line x1="{x:.1f}" y1="{y:.1f}" x2="{x:.1f}" '
                         f'y2="{vol_top + vol_h:.1f}" stroke="{c}" '
                         f'stroke-width="1" opacity="0.75"/>')
            else:
                s.append(f'<rect x="{xi(j) - bw / 2:.1f}" y="{y:.1f}" width="{bw:.1f}" '
                         f'height="{vol_top + vol_h - y:.1f}" fill="{c}" '
                         f'opacity="0.65"/>')

        # 悬停提示: 每个点挂 <title> 太吵, 只给整日一条
        s.append(f'<title>{html.escape(d["date"])} 昨收 {d["preclose"]:.2f} '
                 f'开 {pts[0]["price"]:.2f} 高 {max(p["price"] for p in pts):.2f} '
                 f'低 {min(p["price"] for p in pts):.2f} '
                 f'收 {pts[-1]["price"]:.2f}</title>')

    # 日分隔线 (五日)
    if multi:
        for di in range(1, len(days)):
            x = xpos(di, 0)
            s.append(f'<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" '
                     f'y2="{chart_bot:.1f}" stroke="#b9bfd0" stroke-width="1.3"/>')

    # ── MACD 副图 (12,26,9): 价格 → 量能 → MACD, 自上而下 ──────────
    if macd and macd_h:
        s.append(f'<line x1="{left}" y1="{macd_top + 0.5:.1f}" '
                 f'x2="{left + plot_w}" y2="{macd_top + 0.5:.1f}" stroke="{GRID}"/>')
        zero = macd_top + macd_h / 2
        if not multi:
            s.append(f'<line x1="{left}" y1="{zero:.1f}" x2="{left + plot_w}" '
                     f'y2="{zero:.1f}" stroke="{AXIS}" stroke-dasharray="4 3" '
                     f'opacity="0.6"/>')
        # 多日按整段连续算: 一天一重置会在日界处蹦出锯齿
        closes, offs = [], []
        for d in days:
            offs.append(len(closes))
            closes += [p['price'] for p in d['points']]
        dif, dea, hist = _macd_series(closes)
        mmax = max((abs(v) for v in hist if v is not None), default=0) or 1e-9

        def my(v):
            return zero - (v / mmax) * (macd_h / 2 - 7)

        for di, d in enumerate(days):
            pts = d['points']
            n = len(pts)
            step = (n - 1) or 1
            off = offs[di]
            bw2 = max(plot_w / len(days) / n * 0.6, 1.0)
            for j in range(n):
                v = hist[off + j]
                if v is None:
                    continue
                x = xpos(di, j / step)
                y1 = my(v)
                if abs(y1 - zero) < 0.6:
                    continue
                s.append(f'<rect x="{x - bw2 / 2:.1f}" y="{min(y1, zero):.1f}" '
                         f'width="{bw2:.1f}" height="{abs(y1 - zero):.1f}" '
                         f'fill="{UP if v >= 0 else DOWN}" opacity="0.55"/>')
            for series, col in ((dif, '#e8a33d'), (dea, '#3d7de8')):
                seg = ' '.join(f'{xpos(di, j / step):.1f},{my(series[off + j]):.1f}'
                               for j in range(n) if series[off + j] is not None)
                if seg:
                    s.append(f'<polyline points="{seg}" fill="none" '
                             f'stroke="{col}" stroke-width="1"/>')
        # 标题最后画, 垫白底, 免得被 DIF/DEA 穿过
        s.append(f'<rect x="{left}" y="{macd_top + 2:.1f}" width="76" height="13" '
                 f'fill="#ffffff" fill-opacity="0.85"/>')
        s.append(f'<text x="{left + 2}" y="{macd_top + 12:.1f}" font-size="9.5" '
                 f'fill="#9aa0aa">MACD(12,26,9)</text>')

    # ── 时间轴: 单日标时刻 (取分界线的位置), 多日只标日期 ──────────
    if not multi:
        di, guides = day_guides[0]
        labels = []                      # (gx, lab, anchor)
        for frac, lab, emph in guides:
            gx = xpos(di, frac)
            if lab == '09:15' and days[0]['points'][0]['t'] == '09:15':
                lab = '9:15-25'          # 竞价段就 10 分钟, 直接标区间更省地方
            # 离得太近就跳过, 免得 "11:30/13:00" 压在 "10:30" 上;
            # 但收盘那个 (emph=2) 不能丢, 改成让前一个退位
            if labels and gx - labels[-1][0] < 72:
                if emph != 2:
                    continue
                labels.pop()
            anchor = 'start' if frac <= 0 else ('end' if frac >= 1 else 'middle')
            labels.append((gx, lab, anchor))
        for gx, lab, anchor in labels:
            s.append(f'<text x="{gx:.1f}" y="{h - 26}" font-size="11" '
                     f'text-anchor="{anchor}" fill="{AXIS}">{lab}</text>')
        # 时段名 (集合竞价 / 早盘 / 午盘 / 尾盘竞价) 标在时刻行下方
        pts0 = days[0]['points']
        step0 = (len(pts0) - 1) or 1
        for b0, b1, label in _sessions(pts0, closing_auction):
            if not label:
                continue
            xa = xpos(0, b0 / step0)
            xb = xpos(0, b1 / step0)
            narrow = xb - xa < 46
            at_end = b1 >= len(pts0) - 1
            if narrow and not at_end and label not in ('集合竞价', '不可撤单'):
                continue                      # 半个时段的"午盘"不值得标
            cx = xb - 2 if (narrow and at_end) else \
                (xa + 2 if narrow else (xa + xb) / 2)
            anchor = 'end' if (narrow and at_end) else \
                ('start' if narrow else 'middle')
            fs = 9 if label == '不可撤单' else 10
            s.append(f'<text x="{cx:.1f}" y="{h - 10}" font-size="{fs}" '
                     f'text-anchor="{anchor}" fill="#9aa0aa">{label}</text>')
    else:
        for di, d in enumerate(days):
            cx = xpos(di, 0.5)
            d_last = d['points'][-1]
            pc = _pct(d_last['price'], d['preclose'])
            c = UP if pc > 0 else (DOWN if pc < 0 else FLAT)
            s.append(f'<text x="{cx:.1f}" y="{h - 26}" font-size="11" '
                     f'text-anchor="middle" fill="{AXIS}">{d["date"][5:]} '
                     f'<tspan fill="{c}">{pc:+.2f}%</tspan></text>')

    # 量能轴刻度 (只在左上标一个峰值, 与 K 线图同一套做法)
    s.append(f'<text x="{left - 8}" y="{vol_top + 12}" font-size="11" '
             f'text-anchor="end" fill="{AXIS}">{_hf(vmax)}</text>')
    s.append(f'<line x1="{left}" y1="{vol_top + vol_h}" x2="{left + plot_w}" '
             f'y2="{vol_top + vol_h}" stroke="{AXIS}"/>')

    # 最新价标记
    lx = xpos(len(days) - 1, 1.0)
    ly = py(last['price'])
    s.append(f'<circle cx="{lx:.1f}" cy="{ly:.1f}" r="3" fill="{LINE}"/>')

    s.extend(legend)
    s.append('</svg>')
    return '\n'.join(s)


def _minutes(t):
    try:
        hh, mm = str(t).split(':')[:2]
        return int(hh) * 60 + int(mm)
    except (ValueError, AttributeError):
        return 0


def write_intraday_svg(path, days, **kw):
    svg = render_intraday_svg(days, **kw)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(svg)
    return path

def _day_guides(pts, multi=False):
    """一日内的时间分界线: 开盘 / 10:30 / 午休 / 14:00 / 14:57 / 收盘

    多日图只留午休线: 每格的 14:57 与日界只差 2px, 全画出来就是一团双线;
    日界本身由调用方单独画。
    """
    n = len(pts)
    step = (n - 1) or 1
    gap_j, gap_min = None, 10
    for j in range(1, n):
        d = _minutes(pts[j]['t']) - _minutes(pts[j - 1]['t'])
        if d > gap_min:
            gap_j, gap_min = j, d
    mid = ((gap_j - 0.5) / step,
           f"{pts[gap_j - 1]['t']}/{pts[gap_j]['t']}") if gap_j else None
    if multi:
        return [(mid[0], mid[1], 2)] if mid else []
    guides = [(0.0, pts[0]['t'], 1)]
    for t in ('09:20', '10:30', '14:00', '14:57'):
        j = next((i for i, p in enumerate(pts) if p['t'] == t), None)
        if j:
            guides.append((j / step, t, 3 if t in ('09:20', '14:57') else 0))
    if mid:
        guides.append((mid[0], mid[1], 2))
    guides.append((1.0, pts[-1]['t'], 1))
    return guides

def _sessions(pts, closing_auction=False):
    """按数据里的真实时刻切时段: 集合竞价 / 早盘 / 午盘 / 尾盘竞价

    边界全部取自数据 (首个 >=09:30 的点、午休空档、首个 >=14:57 的点),
    所以半日市/停牌/港股时段不会错位。返回 [(i0, i1, label)] 含端点。
    """
    n = len(pts)
    if not n:
        return []
    tt = [p['t'] for p in pts]
    gap_j, gap_min = None, 10
    for j in range(1, n):
        d = _minutes(tt[j]) - _minutes(tt[j - 1])
        if d > gap_min:
            gap_j, gap_min = j, d
    bands, i0 = [], 0
    if tt[0] < '09:30':
        j = next((i for i, t in enumerate(tt) if t >= '09:30'), n)
        if j > 0:
            # 09:15-09:20 可撤单, 09:20-09:25 不可撤单 (两段的撮合规则不同,
            # 行情软件也是分两段画的)
            bands.append((0, j - 1, '集合竞价'))
            i0 = j
    end = n - 1
    # 盘后固定价格交易 (15:05 起) 单独成段
    k_after = next((i for i, t in enumerate(tt) if t > '15:00' and i > i0), None)
    after = None
    if k_after is not None:
        after = (k_after, n - 1, '盘后')
        end = k_after - 1
    if closing_auction:
        k = next((i for i, t in enumerate(tt) if t >= '14:57' and i > i0 and i <= end),
                 None)
        if k is not None:
            bands.append((k, end, '尾盘竞价'))
            end = k - 1
    if after:
        bands.append(after)
    if i0 <= end:
        if gap_j and i0 < gap_j <= end:
            bands.append((i0, gap_j - 1, '早盘'))
            bands.append((gap_j, end, '午盘'))
        else:
            bands.append((i0, end, '早盘' if tt[i0] < '12:00' else '午盘'))
    return bands


def _seal_runs(pts, limits):
    """封板区间: 连续贴着涨停 (或跌停) 价的分钟段 → [(i0, i1, 'up'/'down')]"""
    up, down = limits.get('up'), limits.get('down')
    eps = 0.0051
    runs, cur = [], None
    for i, p in enumerate(pts):
        pr = p['price']
        side = 'up' if (up and pr >= up - eps) else (
            'down' if (down and pr <= down + eps) else None)
        if cur and cur[2] == side:
            cur = (cur[0], i, side)
        else:
            if cur:
                runs.append(cur)
            cur = (i, i, side) if side else None
    if cur:
        runs.append(cur)
    return runs


def _is_silent_gap(a: dict, b: dict) -> bool:
    """09:25 撮合完到 09:30 连续竞价之间没有成交, 折线不能连过去。

    这 5 分钟交易所只收申报、不撮合 (也不处理撤单), 行情静止。
    连成直线会让人以为价格在这段时间里走过, 实际全部波动都发生在 09:30 之后。
    """
    ta = str(a.get('t') or '')[:5]
    tb = str(b.get('t') or '')[:5]
    return ta <= '09:25' and tb >= '09:30'


def _price_ma(pts, n):
    """分时价格 n 分钟均线; 前 n-1 个点没有值 (None), 不补 0"""
    out, acc = [], 0.0
    prices = [p['price'] for p in pts]
    for i, c in enumerate(prices):
        acc += c
        if i >= n:
            acc -= prices[i - n]
        out.append(acc / n if i >= n - 1 else None)
    return out


def _ema(vals, n):
    """指数移动平均; 首值用首个样本初始化"""
    k = 2.0 / (n + 1)
    out, prev = [], None
    for v in vals:
        prev = v if prev is None else prev + k * (v - prev)
        out.append(prev)
    return out


def _macd_series(closes, fast=12, slow=26, sig=9):
    """分时 MACD: 与 K 线同口径 (柱 = (DIF-DEA)*2)"""
    if not closes:
        return [], [], []
    dif = [a - b for a, b in zip(_ema(closes, fast), _ema(closes, slow))]
    dea = _ema(dif, sig)
    hist = [(a - b) * 2 for a, b in zip(dif, dea)]
    return dif, dea, hist
