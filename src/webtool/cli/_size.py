"""字符画尺寸: 默认跟着终端走, 也能一次给死 (--size 120x40)"""
import shutil
import sys

MIN_W, MAX_W = 20, 240


def term_size():
    """终端 (列, 行); 输出被重定向/管道时给 (80, 24)"""
    try:
        return shutil.get_terminal_size((80, 24))
    except Exception:
        return (80, 24)          # 拿不到就当典型终端


def is_tty():
    try:
        return bool(sys.stdout.isatty())
    except Exception:
        return False


def auto_cols(hi=MAX_W):
    """终端列数 (不是 tty 就给 80), 夹在 20..hi"""
    return max(MIN_W, min(hi, term_size().columns)) if is_tty() else 80


def auto_rows(hi=40):
    """终端行数留两行余量 (不是 tty 就给 24)"""
    return max(8, min(hi, term_size().lines - 2)) if is_tty() else 24


def parse_size(text):
    """'120x40' / '120*40' / '120,40' → (120, 40); 只给一个数就是宽"""
    if not text:
        return 0, 0
    s = text.lower().replace('*', 'x').replace(',', 'x').replace('×', 'x')
    parts = [p.strip() for p in s.split('x') if p.strip()]
    try:
        w = int(parts[0]) if parts else 0
        h = int(parts[1]) if len(parts) > 1 else 0
    except ValueError:
        raise ValueError(f'--size 要写成 120x40 这样, 收到 {text!r}') from None
    return max(0, w), max(0, h)


def fit_box(vw, vh, cols, rows):
    """按原始宽高比装进 cols×rows 的框 (字高≈宽 2 倍), 行数不够就收窄"""
    w = max(1, cols)
    h = max(1, round(vh / vw * w * 0.5))
    if rows and h > rows:
        h = max(1, rows)
        w = max(1, round(2 * h * vw / vh))
    return w, h
