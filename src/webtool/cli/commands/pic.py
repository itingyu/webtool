"""pic: 图片转字符画 (本地图或 URL; 依赖可选, 见下方提示)"""
import io
import os
import sys

import typer

from webtool.cli._ctx import _run, Fmt, Output
from webtool.cli.app import app

DEFAULT_CHARS = ' .:-=+*#%@'


def _load_bytes(src):
    """本地路径或 http(s) URL → 图片原始字节"""
    if src.startswith(('http://', 'https://')):
        from webtool.net import transport
        data, _status, _via, _hdrs = transport.get(src, kind='nav', raw=True)
        if not isinstance(data, (bytes, bytearray)):
            raise ValueError(f'取回的不是二进制 ({type(data).__name__}), 确认 URL 指向图片')
        return bytes(data)
    with open(os.path.expanduser(src), 'rb') as f:
        return f.read()


def _to_ascii(data, width, height, chars, invert):
    try:
        from PIL import Image
    except ImportError:
        raise RuntimeError('需要 Pillow 解码图片, 装一个: pip install pillow') from None
    resample = getattr(Image, 'Resampling', Image).LANCZOS
    im = Image.open(io.BytesIO(data)).convert('L')
    w, h = im.size
    if width <= 0:
        width = min(w, 120)
    rows = height if height > 0 else max(1, round(h / w * width * 0.5))  # 字符高≈宽 2 倍
    im = im.resize((width, rows), resample)
    px = im.load()
    top = len(chars) - 1
    out = []
    for y in range(rows):
        line = []
        for x in range(width):
            v = px[x, y] / 255
            if invert:
                v = 1 - v
            line.append(chars[min(top, max(0, round(v * top)))])
        out.append(''.join(line).rstrip())
    return '\n'.join(out)


@app.command('pic')
def pic_cmd(src: str = typer.Argument(..., help='图片路径或 URL (http/https 走代理规则)'),
            width: int = typer.Option(80, '-w', '--width', help='输出列数'),
            height: int = typer.Option(0, '--height', help='输出行数 (默认按比例, 字高≈宽 2 倍)'),
            chars: str = typer.Option(DEFAULT_CHARS, '--chars', help='灰度字符梯 (从暗到亮)'),
            invert: bool = typer.Option(False, '--invert', help='反转明暗 (浅色终端/负片)'),
            fmt: str = Fmt, output: str = Output):
    """图片转字符画 (jpg/png/webp/gif/bmp; 本地或 URL)"""

    def fn(args, cfg):
        if len(chars) < 2:
            print('error: --chars 至少要 2 个字符', file=sys.stderr)
            return 2
        try:
            data = _load_bytes(src)
        except OSError as e:
            print(f'error: 读不到 {src}: {e}', file=sys.stderr)
            return 2
        except Exception as e:
            print(f'error: 下载失败: {e}', file=sys.stderr)
            return 2
        try:
            art = _to_ascii(data, width, height, chars, invert)
        except Exception as e:
            print(f'error: 转字符画失败: {e}', file=sys.stderr)
            return 2
        print(art)
        return 0

    return _run(None, fn, fmt, output, False, False)
