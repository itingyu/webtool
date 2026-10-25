"""pic: 图片转字符画 (本地图或 URL; 依赖可选, 见下方提示)"""
import base64
import io
import os
import re
import sys

import typer

from webtool.cli._ctx import _run, Fmt, Output
from webtool.cli import _size

DEFAULT_CHARS = ' .:-=+*#%@'


_MAGIC = (b'\x89PNG', b'\xff\xd8\xff', b'GIF8', b'BM', b'RIFF')


def _maybe_bytes(raw):
    """裸图片字节原样返回; 看着像 base64 就解码; 都不像返回 None"""
    if any(raw.startswith(m) for m in _MAGIC):
        return raw
    txt = b''.join(raw.split())
    if len(txt) < 32 or not re.fullmatch(rb'[A-Za-z0-9+/]+={0,2}', txt):
        return None
    try:
        return base64.b64decode(txt, validate=True)
    except Exception:
        return None


def _load_bytes(src):
    """本地路径 / http(s) URL / data: URI / 裸 base64 / `-`(stdin) → 图片原始字节"""
    if src.startswith(('http://', 'https://')):
        from webtool.net import transport
        data, _status, _via, _hdrs = transport.get(src, kind='nav', raw=True)
        if not isinstance(data, (bytes, bytearray)):
            raise ValueError(f'取回的不是二进制 ({type(data).__name__}), 确认 URL 指向图片')
        return bytes(data)
    if src.startswith('data:'):                      # data:image/png;base64,xxxx
        head, _, body = src.partition(',')
        if ';base64' in head:
            return base64.b64decode(body)
        from urllib.parse import unquote_to_bytes
        return unquote_to_bytes(body)
    if src == '-':                                   # 从 stdin 读 base64 或裸二进制
        return _maybe_bytes(sys.stdin.buffer.read())
    path = os.path.expanduser(src)
    if os.path.exists(path):
        with open(path, 'rb') as f:
            return f.read()
    data = _maybe_bytes(src.encode())                # 命令行里直接塞 base64
    if data is None:
        raise OSError('既不是文件 / URL, 也不是 base64 (要喂 stdin 用 -)')
    return data


def _to_ascii(data, width, height, chars, invert):
    try:
        from PIL import Image
    except ImportError:
        raise RuntimeError('需要 Pillow 解码图片 (pyproject 已声明依赖; 缺了就是装包不全, 重装 webtool 即可)') from None
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


def pic_cmd(src: str = typer.Argument(None, help='图片源: 路径 / http(s) URL / data: URI / 裸 base64 / - 读 stdin'),
            width: int = typer.Option(80, '-w', '--width', help='输出列数'),
            height: int = typer.Option(0, '--height', help='输出行数 (默认按比例, 字高≈宽 2 倍)'),
            size: str = typer.Option('', '--size', help='尺寸, 如 120x40 (= -w 120 --height 40)'),
            chars: str = typer.Option(DEFAULT_CHARS, '--chars', help='灰度字符梯 (从暗到亮)'),
            invert: bool = typer.Option(False, '--invert', help='反转明暗 (浅色终端/负片)'),
            fmt: str = Fmt, output: str = Output):
    """图片转字符画 (jpg/png/webp/gif/bmp; 本地或 URL)"""
    if src is None:
        print('用法: webtool render image <图片> [-w 80] [--height N] [--size 120x40] [-c] [--sixel]\n'
              '  图片源: 本地路径 / http(s) URL / data: URI / 裸 base64 / - 读 stdin',
              file=sys.stderr)
        return 2

    def fn(args, cfg):
        if len(chars) < 2:
            print('error: --chars 至少要 2 个字符', file=sys.stderr)
            return 2
        try:
            data = _load_bytes(src)
        except OSError as e:
            print(f'error: 读不到 {src[:48]}: {e}', file=sys.stderr)
            return 2
        except Exception as e:
            print(f'error: 下载失败: {e}', file=sys.stderr)
            return 2
        try:
            try:
                sw, sh = _size.parse_size(size)
            except ValueError as e:
                print(f'error: {e}', file=sys.stderr)
                return 2
            art = _to_ascii(data, sw or width, sh or height, chars, invert)
        except Exception as e:
            print(f'error: 转字符画失败: {e}', file=sys.stderr)
            return 2
        print(art)
        return 0

    return _run(None, fn, fmt, output, False, False)
