"""video/music: 终端里的字符动画播放 (Bad Apple 那种)。

不走 _run: 动画要边算边刷 stdout, 被捕获住就成幻灯片了。
解码一律交给 ffmpeg (缺了就直接报错, 不偷偷降级成"只出第一帧")。
"""
import math
import os
import struct
import subprocess
import sys
import tempfile
import time

import typer

from webtool.cli.app import app

RAMP = ' .:-=+*#%@'
HIDE, SHOW, HOME = '\033[?25l', '\033[?25h', '\033[H'


def _mk_render(chars, invert, w):
    """灰度帧 (bytes) → 字符画文本; ASCII 字符梯走 translate 快路径, 否则慢路径"""
    top = len(chars) - 1

    def pick(i):
        return top - round(i * top / 255) if invert else round(i * top / 255)

    if all(ord(c) < 128 for c in chars):
        table = bytes(ord(chars[pick(i)]) for i in range(256))

        def render(buf):
            fb = buf.translate(table)
            return b'\n'.join(fb[i:i + w] for i in range(0, len(fb), w)).decode()
        return render
    lut = [chars[pick(i)].encode() for i in range(256)]

    def render(buf):
        rows = [b''.join(lut[b] for b in buf[i:i + w]) for i in range(0, len(buf), w)]
        return b'\n'.join(rows).decode()
    return render


def _local(src):
    """URL → 临时文件 (走 webtool 代理规则); 本地路径原样用"""
    if src.startswith(('http://', 'https://')):
        from webtool.net import transport
        data, _st, _via, _h = transport.get(src, kind='nav', raw=True)
        fd, path = tempfile.mkstemp(suffix=os.path.splitext(src.split('?')[0])[1] or '.bin')
        with os.fdopen(fd, 'wb') as f:
            f.write(data)
        return path, True
    if not os.path.exists(src):
        raise OSError(f'找不到 {src}')
    return src, False


def _need(*tools):
    miss = [t for t in tools if not _which(t)]
    if miss:
        raise RuntimeError(f'需要 {", ".join(miss)} (装一个: apk add ffmpeg / apt install ffmpeg)')


def _which(tool):
    from shutil import which
    return which(tool)


def _probe_size(src):
    """视频尺寸 (字符画要按比例算行数)"""
    out = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0',
                          '-show_entries', 'stream=width,height', '-of', 'csv=p=0', src],
                         capture_output=True, text=True).stdout.strip().split('\n')[0]
    w, h = (int(x) for x in out.split(',')[:2])
    return w, h


def _frames(src, w, h, fps, start, dur):
    """ffmpeg 吐 rawvideo 灰度帧; 帧高固定 → 每次读满 w*h 字节"""
    cmd = ['ffmpeg', '-v', 'error']
    if start:
        cmd += ['-ss', str(start)]
    cmd += ['-i', src]
    if dur:
        cmd += ['-t', str(dur)]
    cmd += ['-vf', f'fps={fps},scale={w}:{h}', '-f', 'rawvideo', '-pix_fmt', 'gray', '-']
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    n = w * h
    try:
        while True:
            buf = p.stdout.read(n)
            if len(buf) < n:
                break
            yield buf
    finally:
        p.stdout.close()
        p.wait()


def _play(make_frames, fps, loop):
    """把帧画到终端; make_frames() 每次调用给一个可重放的迭代器"""
    out = sys.stdout
    out.write(HIDE)
    try:
        while True:
            t0 = time.monotonic()
            for i, txt in enumerate(make_frames()):
                out.write(HOME + txt)
                out.flush()
                d = t0 + (i + 1) / fps - time.monotonic()
                if d > 0:
                    time.sleep(d)
            if not loop:
                break
    finally:
        out.write(SHOW + '\n')


@app.command('video')
def video_cmd(src: str = typer.Argument(..., help='视频路径或 URL (http/https 走代理规则)'),
              width: int = typer.Option(80, '-w', '--width', help='输出列数'),
              height: int = typer.Option(0, '--height', help='输出行数 (默认按比例, 字高≈宽 2 倍)'),
              fps: float = typer.Option(12.0, '--fps', help='播放帧率 (终端刷不过来就调小)'),
              chars: str = typer.Option(RAMP, '--chars', help='灰度字符梯 (从暗到亮)'),
              invert: bool = typer.Option(False, '--invert', help='反转明暗'),
              start: float = typer.Option(0.0, '--start', help='从第几秒开始'),
              dur: float = typer.Option(0.0, '--dur', help='只放多少秒 (0=全部)'),
              loop: bool = typer.Option(False, '--loop', help='放完再来一遍'),
              mute: bool = typer.Option(False, '--mute', help='不放音轨 (默认有播放器时同步放)'),
              player: str = typer.Option(None, '--player', help='指定播放器 (默认自动找)')):
    """视频转字符画播放 (Bad Apple 效果; URL 先整段下载再播; 需要 ffmpeg)"""
    if len(chars) < 2:
        print('error: --chars 至少要 2 个字符', file=sys.stderr)
        return 2
    tmp = None
    try:
        _need('ffmpeg', 'ffprobe')
        path, is_tmp = _local(src)
        tmp = path if is_tmp else None
        vw, vh = _probe_size(path)
        w = max(1, width)
        h = height if height > 0 else max(1, round(vh / vw * w * 0.5))
    except Exception as e:
        print(f'error: {e}', file=sys.stderr)
        return 2
    render = _mk_render(chars, invert, w)
    proc = None
    if not mute:
        if start or dur:
            print('提示: 带 --start/--dur 时不同步音轨, 只放画面', file=sys.stderr)
        else:
            cmd = _find_player(player)
            if cmd:
                try:
                    proc = subprocess.Popen(cmd + [path])
                except OSError:
                    proc = None
            else:
                print('提示: 没找到播放器, 只有画面没有声音 (可用 --player 指定)', file=sys.stderr)

    def frames_txt():
        for buf in _frames(path, w, h, fps, start, dur):
            yield render(buf)
    try:
        _play(frames_txt, fps, loop)
    except KeyboardInterrupt:
        return 130
    finally:
        if proc:
            proc.terminate()
        if tmp:
            os.unlink(tmp)
    return 0


PLAYERS = {
    'ffplay': ['-nodisp', '-autoexit', '-loglevel', 'quiet'],
    'mpv': ['--no-video', '--really-quiet'],
    'mplayer': ['-really-quiet'],
    'afplay': [],
    'aplay': ['-q'],
    'paplay': [],
}


def _find_player(explicit):
    """外部播放器: 显式 --player 优先, 否则按常见名字找; 没有就返回 None (只放画面)"""
    if explicit:
        if not _which(explicit):
            return None
        return [explicit] + PLAYERS.get(os.path.basename(explicit), [])
    for name, args in PLAYERS.items():
        if _which(name):
            return [name] + args
    return None


def _band_costs(freqs, rate):
    """每个频点的 Goertzel 系数, 预先算好 (窗口内只做乘加)"""
    return [2 * math.cos(2 * math.pi * f / rate) for f in freqs]


def _goertzel(samples, c):
    """单频点能量; 只为"看着像频谱", 不做幅值校准"""
    s1 = s2 = 0.0
    for x in samples:
        s1, s2 = x + c * s1 - s2, s1
    return math.sqrt(max(0.0, s1 * s1 + s2 * s2 - c * s1 * s2))


def _music_frames(path, freqs, costs, rate, fps, bands, rows, start, dur, title):
    win = max(64, int(rate / fps))
    cmd = ['ffmpeg', '-v', 'error']
    if start:
        cmd += ['-ss', str(start)]
    cmd += ['-i', path]
    if dur:
        cmd += ['-t', str(dur)]
    cmd += ['-f', 's16le', '-ac', '1', '-ar', str(rate), '-']
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    peak = 1e-9
    try:
        while True:
            buf = p.stdout.read(2 * win)
            if len(buf) < 2 * win:
                break
            samples = struct.unpack(f'<{win}h', buf)
            mags = [_goertzel(samples, costs[i]) for i in range(bands)]
            peak = max(max(mags) if mags else 0.0, peak * 0.92)   # 全局峰值缓降 → 柱子不抖
            lvl = [min(1.0, m / peak) for m in mags]
            grid = [[' '] * bands for _ in range(rows)]
            for i, v in enumerate(lvl):
                k = int(round(v * rows))
                for r in range(k):
                    grid[rows - 1 - r][i] = '█' if r == k - 1 else '▓'
            yield title + '\n' + '\n'.join(''.join(r) for r in grid)
    finally:
        p.stdout.close()
        p.wait()


@app.command('music')
def music_cmd(src: str = typer.Argument(..., help='音频路径或 URL (http/https 走代理规则)'),
              bands: int = typer.Option(16, '--bands', help='频谱柱数 (列数)'),
              rows: int = typer.Option(12, '--rows', help='柱子最高多少行'),
              fps: float = typer.Option(20.0, '--fps', help='刷新率 (每帧按它算采样窗口)'),
              rate: int = typer.Option(8000, '--rate', help='分析采样率 (越大越吃 CPU)'),
              start: float = typer.Option(0.0, '--start', help='从第几秒开始'),
              dur: float = typer.Option(0.0, '--dur', help='只放多少秒 (0=全部)'),
              loop: bool = typer.Option(False, '--loop', help='放完再来一遍'),
              player: str = typer.Option(None, '--player', help='指定播放器 (默认自动找; 找不到只放画面)')):
    """音乐转字符律动: 频谱柱动画 (URL 先整段下载再播; 需要 ffmpeg 解码)"""
    if bands < 1 or rows < 1:
        print('error: --bands/--rows 要 >= 1', file=sys.stderr)
        return 2
    tmp = None
    try:
        _need('ffmpeg')
        path, is_tmp = _local(src)
        tmp = path if is_tmp else None
    except Exception as e:
        print(f'error: {e}', file=sys.stderr)
        return 2
    lo = 60.0
    hi = min(3500.0, rate / 2 * 0.9)
    freqs = [lo * (hi / lo) ** (i / (bands - 1)) for i in range(bands)] if bands > 1 else [lo]
    costs = _band_costs(freqs, rate)
    title = f'♪ {os.path.basename(src)[:60]}  ({bands} 柱)'
    proc = _find_player(player)
    if proc:
        try:
            proc = subprocess.Popen(proc + [path])
        except OSError:
            proc = None
    if not proc:
        print('提示: 没找到 ffplay/aplay/mpv/afplay 这类播放器, 只有画面没有声音 '
              '(可用 --player 指定)', file=sys.stderr)

    def frames_txt():
        return _music_frames(path, freqs, costs, rate, fps, bands, rows, start, dur, title)
    try:
        _play(frames_txt, fps, loop)
    except KeyboardInterrupt:
        return 130
    finally:
        if proc:
            proc.terminate()
        if tmp:
            os.unlink(tmp)
    return 0
