"""banner: 把文字排成大字符 (本地字库, 不联网)"""
import sys
import unicodedata

import typer

from webtool.cli._ctx import _run, Fmt, Output
from webtool.cli.app import app
from webtool.cli.bannerfont import COL, DEFAULT_FONT, GLYPHS, ROW, _FONTS


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
        out = [' ' * (r // 2) + row for r, row in enumerate(out)]
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


@app.command('banner')
def banner_cmd(text: list[str] = typer.Argument(None, help='要排版的文字 (可给多个词; 留空读 stdin)'),
               font: str = typer.Option(DEFAULT_FONT, '--font', help='字体, 见 --list'),
               spacing: int = typer.Option(1, '--spacing', help='字间距 (空列数)'),
               width: int = typer.Option(0, '--width', help='折行宽度 (终端列数; 0=不折)'),
               list_fonts: bool = typer.Option(False, '--list', help='列出字体并各打一个样例'),
               fmt: str = Fmt, output: str = Output):
    """字符大字: 把文字排成 banner (本地字库, 不联网)"""
    words = ' '.join(text) if text else None

    def fn(args, cfg):
        if list_fonts:
            for name, spec in _FONTS.items():
                print(f'{name:8} {spec["desc"]}')
                print(render('Ab', name))
                print()
            return 0
        if font not in _FONTS:
            print(f'error: 不认识的字体 {font!r}; 可用: {", ".join(_FONTS)}', file=sys.stderr)
            return 2
        from webtool.core import stdin as _stdin
        s = _stdin.read_input(words, what='要排版的文字')
        if not s or not s.strip():
            print('error: 没给要排版的文字', file=sys.stderr)
            return 2
        print(render(s, font, max(0, spacing), max(0, width)))
        return 0

    return _run(None, fn, fmt, output, False, False)
