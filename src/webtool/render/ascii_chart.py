"""终端字符画: K 线与分时

不依赖任何图形库, 只把坐标画到一个字符网格上, 直接往 stdout 打。
颜色走 ANSI (红涨绿跌), `color=False` 时退化成纯文本, 方便重定向到文件。

网格约定: 一行 = 一个字符单元, 价格越高行号越小 (与屏幕方向一致)。
左侧留 9 列写价格轴, 其余宽度按 1 根 K 线 = 1 列排布。
"""
import shutil

_ANSI = {
    'up': '\033[31m',      # 红
    'down': '\033[32m',    # 绿
    'dim': '\033[90m',     # 灰: 影线/坐标
    'avg': '\033[33m',     # 黄: 均价
    'ma': '\033[35m',      # 紫: 均线
    'vol': '\033[36m',     # 青: 量
}
_RST = '\033[0m'
_BLOCKS = ' ▁▂▃▄▅▆▇█'   # 量能: 0..8 档
_BLOCKS_ASCII = ' .:-=+*#@'  # 纯 ASCII 兜底 (字体缺块元素时)
_GLYPH = {
    'wide':    dict(wick='│', body_up='█', body_dn='▓', doji='─', dot='·'),
    # 默认即区分形态: 影线细竖 `│` (灰), 实体 `█`/`▓` (红/绿) —— 有色无色
    # 都能一眼分开; 旧 "细柱┃" 字形与影线只差半格, 无色环境看不出来, 弃用。
    'thin':    dict(wick='│', body_up='█', body_dn='▓', doji='─', dot='·'),
    'plain':   dict(wick='|', body_up='#', body_dn='#', doji='-', dot='.'),
}


class _Grid:
    """字符网格 + 每格颜色, 渲染时按连续同色段拼 ANSI。"""

    def __init__(self, w, h):
        self.w, self.h = w, h
        self.ch = [[' '] * w for _ in range(h)]
        self.fg = [[None] * w for _ in range(h)]

    def put(self, x, y, c, color=None):
        if 0 <= x < self.w and 0 <= y < self.h:
            self.ch[y][x] = c
            self.fg[y][x] = color

    def get(self, x, y):
        if 0 <= x < self.w and 0 <= y < self.h:
            return self.ch[y][x]
        return ' '

    def vline(self, x, y0, y1, c, color=None):
        for y in range(min(y0, y1), max(y0, y1) + 1):
            self.put(x, y, c, color)

    def line(self, x0, y0, x1, y1, c, color=None):
        """Bresenham: 把两个点连起来 (分时折线用)"""
        dx, dy = abs(x1 - x0), abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx - dy
        while True:
            self.put(x0, y0, c, color)
            if x0 == x1 and y0 == y1:
                return
            e2 = 2 * err
            if e2 > -dy:
                err -= dy
                x0 += sx
            if e2 < dx:
                err += dx
                y0 += sy

    def render(self, color=True):
        out = []
        for y in range(self.h):
            buf, cur = [], None
            for x in range(self.w):
                c = self.fg[y][x]
                if color:
                    if c != cur:
                        buf.append(_ANSI[c] if c else (_RST if cur else ''))
                        cur = c
                buf.append(self.ch[y][x])
            line = ''.join(buf)
            if color:
                line += _RST
            out.append(line.rstrip())
        return '\n'.join(out)


def _term_width(default=78):
    try:
        return max(40, min(160, shutil.get_terminal_size((default, 24)).columns))
    except Exception:                                  # noqa: BLE001
        return default


def _fnum(v, nd=2):
    return f'{v:,.{nd}f}'


# ── K 线 ────────────────────────────────────────────────────────────
def _silent_gap(a, b):
    """09:25 撮合完到 09:30 连续竞价之间没有成交, 连线会画出假走势"""
    return (str(a.get('t') or '')[:5] <= '09:25'
            and str(b.get('t') or '')[:5] >= '09:30')


def kline_ascii(rows, width=None, height=20, ma=(5, 10, 20, 60),
                title='', color=True, vol_h=3, plain=False, wide=False,
                gap=False):
    """日/周/月 K 的字符画。rows 用 render.kline_svg.normalize_rows 的形状。"""
    rows = [r for r in (rows or []) if r.get('close') is not None]
    if not rows:
        return '（无 K 线数据）'
    width = width or _term_width()
    g = _GLYPH['plain' if plain else ('wide' if wide else 'thin')]
    bw = 2 if gap else 1          # 每根占几列 (gap=True 时右侧空一列做间隔)
    blocks = _BLOCKS_ASCII if plain else _BLOCKS
    lab_w = 9
    plot_w = max(10, width - lab_w - 1)
    n = min(len(rows), plot_w // bw)
    show = rows[-n:]
    # 均线在完整序列上算, 只看窗口尾部会缺前段
    ma_series = {}
    for m in (ma or ()):
        try:
            m = int(str(m).strip())
        except (TypeError, ValueError):
            continue
        if m <= 0:
            continue
        vals, s = [], 0.0
        for i, r in enumerate(rows):
            s += r['close']
            if i >= m:
                s -= rows[i - m]['close']
            vals.append(s / m if i >= m - 1 else None)
        ma_series[m] = vals[len(rows) - n:]

    hi = max(r['high'] for r in show)
    lo = min(r['low'] for r in show)
    pad = (hi - lo) * 0.04 or max(hi * 0.01, 1)
    hi, lo = hi + pad, lo - pad
    span = hi - lo or 1

    grid = _Grid(width, height + 3)

    def ypos(v):
        return int(round((hi - v) / span * (height - 1)))

    # 价格轴
    for k in range(5):
        yy = min(height - 1, round(k * (height - 1) / 4))
        v = hi - (yy / (height - 1)) * span
        txt = _fnum(v).rjust(lab_w - 2)
        for i, ch in enumerate(txt):
            grid.put(i, yy, ch, 'dim')
        grid.put(lab_w - 1, yy, '┤', 'dim')

    # 蜡烛: 每根 1 列, 影线 + 实体
    for i, r in enumerate(show):
        x = lab_w + i * bw
        up = r['close'] >= r['open']
        col = 'up' if up else 'down'
        yh, yl = ypos(r['high']), ypos(r['low'])
        yo, yc = ypos(r['open']), ypos(r['close'])
        grid.vline(x, yh, yl, g['wick'], 'dim')
        body = g['body_up'] if up else g['body_dn']
        if abs(yo - yc) < 1:                  # 十字星: 仍画竖的, 横杠会把列截断
            grid.put(x, yo, body, col)
        else:
            grid.vline(x, yo, yc, body, col)

    # 均线: 只填空格, 不盖住蜡烛; 每条用不同字符, 否则四条糊成一片点
    _ma_chars = ['·', ':', '+', '×']
    for k, (m, vals) in enumerate(ma_series.items()):
        ch = _ma_chars[k % len(_ma_chars)]
        for i, v in enumerate(vals):
            if v is None:
                continue
            x = lab_w + i * bw
            yy = ypos(v)
            if grid.get(x, yy) == ' ':
                grid.put(x, yy, ch, 'ma')

    # 量能: 单行八分块, 比多行柱省地方也更看得出高低
    vmax = max((r.get('volume') or 0) for r in show) or 1
    for i, r in enumerate(show):
        v = r.get('volume') or 0
        k = min(8, int(round(v / vmax * 8))) if v else 0
        grid.put(lab_w + i * bw, height + 1, blocks[k],
                 'up' if r['close'] >= r['open'] else 'down')

    # 底部日期
    _last_end = [-1]
    step = max(1, n // 6)
    for i in range(0, n, step):
        d = str(show[i]['date'])[5:10]
        if i * bw < _last_end[0]:            # 会压到上一个标签就跳过
            continue
        for j, ch in enumerate(d):
            grid.put(lab_w + i * bw + j, height + 2, ch, 'dim')
        _last_end[0] = i * bw + len(d) + 2

    head = title or ''
    if head:
        head += f'   高 {_fnum(hi - pad)}  低 {_fnum(lo + pad)}'
    body = grid.render(color)
    return f'{head}\n{body}' if head else body


# ── 分时 ────────────────────────────────────────────────────────────
class _Braille:
    """盲文点阵画布: 一个字符 = 2 列 × 4 行子像素

    同一格里的 8 个点合并成一个 U+2800 区字符, 于是 78×16 的终端区域
    实际有 156×64 个可寻址点 —— 折线不会再被压成台阶。
    """

    # 子像素 (dx, dy) → 点位
    _BIT = ((0x01, 0x02, 0x04, 0x40), (0x08, 0x10, 0x20, 0x80))

    def __init__(self, cols, rows):
        self.cw, self.rh = cols, rows
        self.bits = [[0] * cols for _ in range(rows)]
        self.fg = [[None] * cols for _ in range(rows)]

    def dot(self, x, y, color=None):
        if x < 0 or y < 0:
            return
        cx, cy = x >> 1, y >> 2
        if cx >= self.cw or cy >= self.rh:
            return
        self.bits[cy][cx] |= self._BIT[x & 1][y & 3]
        if color and self.fg[cy][cx] is None:
            self.fg[cy][cx] = color

    def line(self, x0, y0, x1, y1, color=None):
        dx, dy = abs(x1 - x0), abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx - dy
        while True:
            self.dot(x0, y0, color)
            if x0 == x1 and y0 == y1:
                return
            e2 = 2 * err
            if e2 > -dy:
                err -= dy
                x0 += sx
            if e2 < dx:
                err += dx
                y0 += sy

    def char(self, cy, cx):
        b = self.bits[cy][cx]
        return chr(0x2800 + b) if b else None


def intraday_ascii(days, width=None, height=16, title='', color=True,
                   vol_h=3, preclose=None, show_avg=True, show_ma=True,
                   plain=False):
    """分时字符画: 走势用盲文点阵 (2×4 子像素), 坐标与量能用普通字符"""
    days = [d for d in (days or []) if d.get('points')]
    if not days:
        return '（无分时数据）'
    width = width or _term_width()
    blocks = _BLOCKS_ASCII if plain else _BLOCKS
    lab_w = 10
    plot_w = max(10, width - lab_w - 1)

    pts = [p for d in days for p in d['points']]
    n = len(pts)
    cols = min(plot_w, n)
    picked = [pts[round(i * (n - 1) / max(cols - 1, 1))] for i in range(cols)]

    prices = [p['price'] for p in picked if p.get('price') is not None]
    avgs = [p['avg'] for p in picked if show_avg and p.get('avg') is not None]
    base = preclose or days[0].get('preclose') or prices[0]
    lo = min(prices + (avgs or []))
    hi = max(prices + (avgs or []))
    lo, hi = min(lo, base), max(hi, base)
    pad = (hi - lo) * 0.06 or max(base * 0.002, 0.01)
    hi, lo = hi + pad, lo - pad
    span = hi - lo or 1

    grid = _Grid(width, height + 3)
    pts_grid = _Braille(cols, height)          # 子像素网格
    sub_h = height * 4 - 1

    def doty(v):
        return int(round((hi - v) / span * sub_h))

    # 坐标轴
    for k in range(5):
        yy = min(height - 1, round(k * (height - 1) / 4))
        v = hi - (yy / (height - 1)) * span
        pct = (v / base - 1) * 100 if base else 0
        txt = f'{pct:+.2f}%'.rjust(lab_w - 2)
        for i, ch in enumerate(txt):
            grid.put(i, yy, ch, 'dim')
        grid.put(lab_w - 1, yy, '┤', 'dim')

    # 0% 基准线: 点阵虚线
    y0 = doty(base)
    if not plain:
        for x in range(cols * 2):
            if x % 6 == 0:
                pts_grid.dot(x, y0)

    # 价格线
    if plain:
        for i, p in enumerate(picked):
            yy = max(0, min(height - 1,
                            int(round((hi - p['price']) / span * (height - 1)))))
            grid.put(lab_w + i, yy, '*',
                     'up' if p['price'] >= base else 'down')
        if show_avg:
            for i, p in enumerate(picked):
                if p.get('avg') is None:
                    continue
                yy = max(0, min(height - 1,
                                int(round((hi - p['avg']) / span * (height - 1)))))
                if grid.get(lab_w + i, yy) == ' ':
                    grid.put(lab_w + i, yy, '.', 'avg')
    else:
        prev = None
        for i, p in enumerate(picked):
            yy = doty(p['price'])
            col = 'up' if p['price'] >= base else 'down'
            x = i * 2 + 1
            if prev is None or _silent_gap(picked[i - 1], p):
                pts_grid.dot(x, yy, col)
                pts_grid.dot(x, yy + 1, col)
            else:
                pts_grid.line(x - 2, prev, x, yy, col)
            prev = yy

    # 均价: 补在价格线没占的点上, 不抢主线的颜色
    if show_avg and avgs and not plain:
        prev = None
        for i, p in enumerate(picked):
            if p.get('avg') is None:
                continue
            yy = doty(p['avg'])
            x = i * 2 + 1
            if prev is not None and not _silent_gap(picked[i - 1], p):
                for xx in range(x - 2, x + 1):
                    cy, cx = yy >> 2, xx >> 1
                    if 0 <= cy < height and 0 <= cx < cols and not pts_grid.bits[cy][cx]:
                        pts_grid.dot(xx, yy, 'avg')
            prev = yy

    # 日分界
    if len(days) > 1:
        acc, bounds = 0, []
        for d in days[:-1]:
            acc += len(d['points'])
            bounds.append(min(cols - 1, round(acc / max(n - 1, 1) * (cols - 1))))
        for bx in bounds:
            for yy in range(height):
                if grid.get(lab_w + bx, yy) == ' ':
                    grid.put(lab_w + bx, yy, '│', 'dim')

    # 量能: 单行八分块
    colv, colmap, vmax = [], [], 0
    for i in range(cols):
        a = round(i * (n - 1) / max(cols - 1, 1))
        b = round((i + 1) * (n - 1) / max(cols - 1, 1)) + 1
        v = sum((p.get('vol') or 0) for p in pts[a:b])
        colv.append(v)
        colmap.append('up' if picked[i]['price'] >= base else 'down')
        vmax = max(vmax, v)
    vmax = vmax or 1
    for i, v in enumerate(colv):
        k = min(8, int(round(v / vmax * 8))) if v else 0
        grid.put(lab_w + i, height + 1, blocks[k], colmap[i])

    # 时间轴
    ylab = height + 2
    if len(days) > 1:
        acc = 0
        for d in days:
            idx = round(acc / max(n - 1, 1) * (cols - 1))
            idx = min(idx, width - 6)
            for j, ch in enumerate(str(d.get('date') or '')[-5:]):
                grid.put(lab_w + idx + j, ylab, ch, 'dim')
            acc += len(d['points'])
    else:
        marks = ['09:30', '10:30', '11:30/13:00', '14:00', '15:00']
        for k, m in enumerate(marks):
            idx = round(k * (cols - 1) / (len(marks) - 1))
            idx = min(idx, lab_w + cols - len(m) - 1)
            for j, ch in enumerate(m):
                grid.put(lab_w + idx + j, ylab, ch, 'dim')

    # 合并: 点阵优先, 其余用文字网格
    lines = []
    for y in range(height):
        buf, cur = [], None
        for x in range(width):
            if x >= lab_w:
                cx = x - lab_w
                bc = pts_grid.char(y, cx) if cx < cols else None
                if bc:
                    c = pts_grid.fg[y][cx]
                    if color and c != cur:
                        buf.append(_ANSI[c] if c else (_RST if cur else ''))
                        cur = c
                    buf.append(bc)
                    continue
            c = grid.fg[y][x]
            if color and c != cur:
                buf.append(_ANSI[c] if c else (_RST if cur else ''))
                cur = c
            buf.append(grid.ch[y][x])
        line = ''.join(buf)
        lines.append(line + (_RST if color else ''))
    # 底部三行 (空行/量能/时间) 用纯文字网格
    for y in range(height, height + 3):
        buf, cur = [], None
        for x in range(width):
            c = grid.fg[y][x]
            if color and c != cur:
                buf.append(_ANSI[c] if c else (_RST if cur else ''))
                cur = c
            buf.append(grid.ch[y][x])
        lines.append(''.join(buf).rstrip() + (_RST if color else ''))
    body = '\n'.join(ln.rstrip() for ln in lines)
    return f'{title}\n{body}' if title else body
