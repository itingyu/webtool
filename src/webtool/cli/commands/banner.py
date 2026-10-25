"""banner: 把文字排成大字符 (本地字库, 不联网)"""
import sys
import unicodedata

import typer

from webtool.cli._ctx import _run, Fmt, Output
from webtool.cli.bannerfont import COL, DEFAULT_FONT, GLYPHS, ROW, _FONTS
from webtool.core.config_data import DATA_DIR


def _cells(ch, spec):
    """单个字符 → 若干行等宽字符串 (按字体上色 / 描边 / 投影 / 斜切)"""
    rows = GLYPHS.get(ch) or GLYPHS.get(ch.upper())   # 字库只有大写, 小写归一
    if rows is None:                       # 非字库字符 (含中文) 原样排在中间行
        w = 2 if unicodedata.east_asian_width(ch) in ('W', 'F') else 1
        blank = ' ' * w
        out = [blank] * ROW
        out[ROW // 2] = ch.ljust(w)
        return out
    bit = [[c == '1' for c in r] for r in rows]

    def on(r, c):
        return 0 <= r < ROW and 0 <= c < COL and bit[r][c]

    grid = [[' '] * COL for _ in range(ROW)]
    for r in range(ROW):
        for c in range(COL):
            if not bit[r][c]:
                continue
            if spec.get('outline') and on(r - 1, c) and on(r + 1, c) and on(r, c - 1) and on(r, c + 1):
                continue                   # 四邻皆实 → 内部点, 挖空成轮廓
            grid[r][c] = spec['fill']
    if spec.get('shadow'):
        for r in range(ROW):
            for c in range(COL):
                if not bit[r][c] and (on(r - 1, c - 1) or on(r - 1, c) or on(r, c - 1)):
                    grid[r][c] = spec['shadow']
    out = [''.join(row) for row in grid]
    if spec.get('slant'):
        out = [' ' * ((ROW - 1 - r) // 2) + row for r, row in enumerate(out)]
    return out


def _render_line(text, spec, spacing):
    cells = [_cells(ch, spec) for ch in text]
    if not cells:
        return []
    pad = ' ' * spacing
    return [pad.join(c[r] for c in cells).rstrip() for r in range(ROW)]


def _wrap(text, width, spacing):
    """按终端列数折行; width<=0 不折"""
    if width <= 0:
        return [text]
    per = max(1, (width + spacing) // (COL + spacing))
    lines, cur = [], ''
    for word in text.split(' '):
        while len(word) > per:             # 超长单词硬切
            if cur:
                lines.append(cur)
                cur = ''
            lines.append(word[:per])
            word = word[per:]
        if not cur:
            cur = word
        elif len(cur) + 1 + len(word) <= per:
            cur += ' ' + word
        else:
            lines.append(cur)
            cur = word
    if cur or not lines:
        lines.append(cur)
    return lines


def render(text, font=DEFAULT_FONT, spacing=1, width=0):
    spec = _FONTS[font]
    out = []
    for ln in _wrap(text, width, spacing):
        out.extend(_render_line(ln, spec, spacing))
        out.append('')
    while out and not out[-1]:
        out.pop()
    return '\n'.join(out)


_BIG_RAMP = ' .:-=+*#%@'


def _find_font():
    """能画汉字的字体: WEBTOOL_BANNER_FONT → 随包字体 → 系统字体 (Linux/macOS/Windows)"""
    import glob
    import os
    env = os.environ.get('WEBTOOL_BANNER_FONT')
    if env and os.path.exists(env):
        return env
    bundled = DATA_DIR / 'banner-cjk-sc.otf'      # 随包的 Noto Sans CJK SC 子集 (4736 字)
    if bundled.exists():
        return str(bundled)
    pats = ('/usr/share/fonts/**/*CJK*.tt[cf]', '/system/fonts/*CJK*.tt[cf]',
            '/System/Library/Fonts/PingFang.ttc', '/System/Library/Fonts/*.tt[cf]',
            '/Library/Fonts/*.tt[cf]', 'C:/Windows/Fonts/msyh.ttc',
            'C:/Windows/Fonts/simhei.ttf', 'C:/Windows/Fonts/*.tt[cf]',
            '/usr/share/fonts/**/*.tt[cf]')
    for pat in pats:
        for p in sorted(glob.glob(pat, recursive=True)):
            return p
    raise RuntimeError('找不到字体文件; 用 WEBTOOL_BANNER_FONT=<字体路径> 指定')


def _render_big(text, cols=0, chars=_BIG_RAMP):
    """用真实字体把整串文字栅格化再映射成字符 (中英混排都能画)"""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        raise RuntimeError("需要 Pillow 渲染大字 (pyproject 已声明依赖; 重装 webtool 即可)") from None
    font = ImageFont.truetype(_find_font(), 96)
    asc, desc = font.getmetrics()
    w = int(sum(font.getlength(c) for c in text)) + 8
    im = Image.new('L', (max(1, w), asc + desc), 0)
    ImageDraw.Draw(im).text((4, 0), text, fill=255, font=font)
    box = im.getbbox()
    if box:
        im = im.crop(box)
    iw, ih = im.size
    if cols > 0:                                   # 给了宽度 → 高度按比例
        rows = max(1, round(cols * ih / iw * 0.5))
    else:                                          # 默认 12 行 (汉字够看清)
        rows = 12
        cols = max(1, round(2 * rows * iw / ih))
    im = im.resize((cols, rows), Image.LANCZOS)
    px = im.load()
    top = len(chars) - 1
    out = []
    for y in range(rows):
        out.append(''.join(chars[min(top, max(0, round(px[x, y] / 255 * top)))]
                           for x in range(cols)).rstrip())
    return '\n'.join(out)


def banner_cmd(text: list[str] = typer.Argument(None, help='要排版的文字 (可给多个词; 留空读 stdin)'),
               font: str = typer.Option(DEFAULT_FONT, '--font', help='字体 (见 --list; big = 字体栅格化, 支持汉字)'),
               spacing: int = typer.Option(1, '--spacing', help='字间距 (空列数)'),
               width: int = typer.Option(0, '--width', help='折行宽度 (终端列数; 0=不折)'),
               list_fonts: bool = typer.Option(False, '--list', help='列出字体并各打一个样例'),
               fmt: str = Fmt, output: str = Output):
    """字符大字: 字母走点阵, 汉字/emoji 走字体栅格化 (本地, 不联网)"""
    words = ' '.join(text) if text else None

    def fn(args, cfg):
        if list_fonts:
            for name, spec in _FONTS.items():
                print(f'{name:8} {spec["desc"]}')
                print(render('Ab', name))
                print()
            return 0
        if font not in _FONTS and font != 'big':
            print(f'error: 不认识的字体 {font!r}; 可用: {", ".join(list(_FONTS) + ["big"])}',
                  file=sys.stderr)
            return 2
        from webtool.core import stdin as _stdin
        s = _stdin.read_input(words, what='要排版的文字')
        if not s or not s.strip():
            print('用法: webtool render text <文字> [--font big] [--spacing 1] [--width N]\n'
                  '  文字也可从管道喂: echo HI | webtool render text', file=sys.stderr)
            return 2
        if font == 'big' or any(ord(c) > 127 for c in s):     # 汉字/emoji → 字体栅格化
            if font in _FONTS:
                print('提示: 文字含非 ASCII, 自动改用字体栅格化 (big); '
                      f'想强行点阵可加 --font {font}', file=sys.stderr)
            print(_render_big(s, max(0, width)))
        else:
            print(render(s, font, max(0, spacing), max(0, width)))
        return 0

    return _run(None, fn, fmt, output, False, False)
