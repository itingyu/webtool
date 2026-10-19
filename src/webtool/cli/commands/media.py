"""video/music: 终端里的字符动画播放 (Bad Apple 那种)。

不走 _run: 动画要边算边刷 stdout, 被捕获住就成幻灯片了。
解码一律交给 ffmpeg (缺了就直接报错, 不偷偷降级成"只出第一帧")。
"""
import io
import math
import os
import struct
import subprocess
import sys
import tempfile
import threading
import time

import typer

from webtool.cli import _size
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
    """URL → 临时文件 (走 webtool 代理规则); 本地路径原样用

    边收边写盘: transport.get 有 max_bytes 上限 (默认 8MB), 大视频会被截成残文件。
    """
    if src.startswith(('http://', 'https://')):
        from webtool.net import transport
        resp, status, _via, _h = transport.open_stream(src, kind='nav')
        if int(status) >= 400:
            raise OSError(f'HTTP {status} 取不到 {src}')
        fd, path = tempfile.mkstemp(suffix=os.path.splitext(src.split('?')[0])[1] or '.bin')
        with os.fdopen(fd, 'wb') as f:
            for chunk in resp.iter_content(1 << 16):
                f.write(chunk)
        return path, True
    if not os.path.exists(src):
        raise OSError(f'找不到 {src}')
    return src, False


class _Live:
    """URL 流式输入: 走 webtool 自己的通道边收边喂 ffmpeg, 不整段下载

    head 是先啃下来的前 1MB, 用来探宽高; 之后连同剩余字节一起写进 ffmpeg 的
    stdin。只有流式真的读不了 (索引在文件尾的容器) 才 spill() 落地整段下载 ——
    那是退路, 不是默认路径。
    """

    PEEK = 1 << 20

    def __init__(self, src, head=True):
        from webtool.net import transport
        resp, status, via, _h = transport.open_stream(src, kind='nav')
        if int(status) >= 400:
            raise OSError(f'HTTP {status} 取不到 {src}')
        self.src = src
        self.resp, self.via = resp, via
        self.it = resp.iter_content(1 << 16)
        self.head = self._read_head() if head else b''
        self.tmp = None

    def _suffix(self):
        return os.path.splitext(self.src.split('?')[0])[1] or '.bin'

    def _read_head(self):
        out = bytearray()
        for chunk in self.it:
            out += chunk
            if len(out) >= self.PEEK:
                break
        return bytes(out)

    def probe_size(self):
        """头字节喂进探针的管道 —— 跟 ffmpeg 一样不可 seek, 读得动才返回尺寸

        别写临时文件让 ffprobe 去 seek: 那样"索引在文件尾"的 mp4 也能探出尺寸,
        可 ffmpeg 从管道读同一个文件必然失败, 等于白探一场。
        """
        if not self.head:
            return None
        if _exe('ffprobe'):
            try:
                r = subprocess.run([_exe('ffprobe'), '-v', 'error', '-select_streams', 'v:0',
                                    '-show_entries', 'stream=width,height', '-of', 'csv=p=0',
                                    '-i', 'pipe:0'],
                                   input=self.head, capture_output=True, timeout=90)
                out = r.stdout.decode().strip().splitlines()[0]
                w, h = (int(x) for x in out.split(',')[:2])
                return w, h
            except Exception:
                return None
        return self._pipe_size()

    def _pipe_size(self):
        """没 ffprobe 时: 头字节喂 ffmpeg 解一帧, 交给 PIL 量 (同样是不可 seek 的处境)"""
        try:
            r = subprocess.run([_exe('ffmpeg'), '-v', 'error', '-i', 'pipe:0', '-frames:v', '1',
                                '-f', 'image2pipe', '-vcodec', 'png', '-'],
                               input=self.head, capture_output=True, timeout=180)
            if r.returncode != 0 or not r.stdout:
                return None
            from PIL import Image
            with Image.open(io.BytesIO(r.stdout)) as im:
                return im.size
        except Exception:
            return None

    def readable(self, sel='v:0'):
        """头字节能不能顺序解出来 (不可 seek, 跟 ffmpeg 同处境) → 不能就别走管道"""
        if not self.head:
            return False
        if _exe('ffprobe'):
            try:
                r = subprocess.run([_exe('ffprobe'), '-v', 'error', '-select_streams', sel,
                                    '-show_entries', 'stream=codec_name', '-of', 'csv=p=0',
                                    '-i', 'pipe:0'],
                                   input=self.head, capture_output=True, timeout=90)
                return r.returncode == 0 and bool(r.stdout.strip())
            except Exception:
                return False
        r = subprocess.run([_exe('ffmpeg'), '-v', 'info', '-i', 'pipe:0'], input=self.head,
                           capture_output=True, timeout=90)
        want = 'Audio:' if sel.startswith('a') else 'Video:'
        return want in r.stderr.decode('utf-8', 'replace')

    def spill(self):
        """流式读不了 → 头 + 剩余字节落盘, 返回临时文件路径 (退路: 整段下载)"""
        fd, p = tempfile.mkstemp(suffix=self._suffix())
        with os.fdopen(fd, 'wb') as f:
            f.write(self.head)
            for chunk in self.it:
                f.write(chunk)
        self.tmp = p
        return p

    def feed(self, pipe):
        """后台把 head + 剩余字节推进 ffmpeg 的 stdin; ffmpeg 提前退出就收工"""
        def pump():
            try:
                if self.head:
                    pipe.write(self.head)
                for chunk in self.it:
                    pipe.write(chunk)
            except (BrokenPipeError, ValueError, OSError):
                pass
            finally:
                try:
                    pipe.close()
                except Exception:
                    pass
        t = threading.Thread(target=pump, daemon=True)
        t.start()
        return t

    def close(self):
        try:
            self.resp.close()
        except Exception:
            pass


_FF_CACHE = {}


def _py_pkg_exe(name):
    """Python 包自带的静态二进制 (省得装系统包): static-ffmpeg / imageio-ffmpeg

    动态导入, 不写 import 语句: 这俩是可选的, 不进 pyproject —— musl 上没有轮子,
    塞进核心依赖会把 Alpine 上的安装搞挂; 也不该被依赖审计当成“声明缺失”。
    """
    import importlib
    try:
        sf = importlib.import_module('static_ffmpeg.run')      # pip install static-ffmpeg
        a, b = sf.get_or_fetch_platform_executables_else_raise()
        return a if name == 'ffmpeg' else b
    except Exception:
        pass
    if name == 'ffmpeg':
        try:
            iio = importlib.import_module('imageio_ffmpeg')    # pip install imageio-ffmpeg
            return iio.get_ffmpeg_exe()
        except Exception:
            pass
    return None


def _exe(name):
    """ffmpeg / ffprobe 的实际路径: 环境变量 → PATH → Python 包 (结果缓存)"""
    if name not in _FF_CACHE:
        env = os.environ.get('WEBTOOL_' + name.upper())
        path = env if env and os.access(env, os.X_OK) else (_which(name) or _py_pkg_exe(name))
        _FF_CACHE[name] = path if path and os.access(path, os.X_OK) else None
    return _FF_CACHE[name]


def _need(*tools):
    miss = [t for t in tools if not _exe(t)]
    if miss:
        raise RuntimeError('需要 ' + ', '.join(miss) + ' (三选一: apk add ffmpeg / apt install ffmpeg; '
                           'pip install imageio-ffmpeg; WEBTOOL_' + miss[0].upper() + '=/path/to/binary)')


def _which(tool):
    from shutil import which
    return which(tool)


def _probe_flags(src):
    """URL 限一下探测深度: 默认 5MB 会把小文件整个读进来, 违背别全下载的初衷"""
    return ['-probesize', '1000000', '-analyzeduration', '1000000'] if str(src).startswith(
        ('http://', 'https://')) else []


def _child_env(src):
    """把 webtool 给这个 URL 定的代理交给 ffmpeg/ffprobe/播放器 (它们认 http_proxy 环境变量)"""
    env = dict(os.environ)
    if not src.startswith(('http://', 'https://')):
        return env
    try:
        from webtool.core import secrets_store
        from webtool.net import netx
        proxy = netx.resolve_proxy(None, src)
        if proxy and proxy != 'direct':
            env['http_proxy'] = env['https_proxy'] = secrets_store.resolve_auth(proxy)
    except Exception:
        pass
    return env


def _probe_size(src, env=None):
    """视频尺寸 (字符画要按比例算行数); 没装 ffprobe 就解一帧交给 PIL 量"""
    if _exe('ffprobe'):
        r = subprocess.run([_exe('ffprobe'), '-v', 'error', *_probe_flags(src),
                            '-select_streams', 'v:0', '-show_entries', 'stream=width,height',
                            '-of', 'csv=p=0', src], capture_output=True, text=True, env=env)
        out = r.stdout.strip().splitlines()[0].strip() if r.stdout.strip() else ''
        if ',' in out:
            w, h = (int(x) for x in out.split(',')[:2])
            return w, h
    return _probe_size_by_frame(src, env)


def _probe_size_by_frame(src, env=None):
    """ffmpeg 解第一帧成 PNG, 交给 PIL 量 (Pillow 是硬依赖); 解不出来就是读不动"""
    from PIL import Image
    fd, png = tempfile.mkstemp(suffix='.png')
    os.close(fd)
    try:
        r = subprocess.run([_exe('ffmpeg'), '-v', 'error', *_probe_flags(src), '-i', src,
                            '-frames:v', '1', '-y', png], capture_output=True, env=env)
        if r.returncode != 0 or not os.path.getsize(png):
            tail = r.stderr.decode('utf-8', 'replace').strip().splitlines()
            raise OSError('读不出视频尺寸 (不是视频? 或文件不完整): '
                          + (tail[-1][:70] if tail else 'ffmpeg 没输出'))
        with Image.open(png) as im:
            return im.size
    finally:
        if os.path.exists(png):
            os.unlink(png)


def _can_read(src, env=None, sel='a:0'):
    """URL 能不能交给 ffmpeg 自己读 (只看能不能解出这条流, 不看尺寸)"""
    if _exe('ffprobe'):
        r = subprocess.run([_exe('ffprobe'), '-v', 'error', *_probe_flags(src),
                            '-select_streams', sel, '-show_entries', 'stream=codec_name',
                            '-of', 'csv=p=0', src], capture_output=True, text=True, env=env)
        return r.returncode == 0 and bool(r.stdout.strip())
    r = subprocess.run([_exe('ffmpeg'), '-v', 'info', *_probe_flags(src), '-i', src],
                       capture_output=True, text=True, env=env)
    return ('Audio:' if sel.startswith('a') else 'Video:') in r.stderr


def _frames(src, w, h, fps, start, dur, live=None, env=None):
    """ffmpeg 吐 rawvideo 灰度帧; 帧高固定 → 每次读满 w*h 字节"""
    cmd = [_exe('ffmpeg'), '-v', 'error'] + _probe_flags(src)
    if start and not live:          # 本地文件能 seek, 输入前定位最省事
        cmd += ['-ss', str(start)]
    cmd += ['-i', src]
    if start and live:              # 管道不可 seek, 只能边读边丢
        cmd += ['-ss', str(start)]
    if dur:
        cmd += ['-t', str(dur)]
    cmd += ['-vf', f'fps={fps},scale={w}:{h}', '-f', 'rawvideo', '-pix_fmt', 'gray', '-']
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                         stdin=subprocess.PIPE if live else None, env=env)
    if live:
        live.feed(p.stdin)
    n = w * h
    try:
        while True:
            buf = p.stdout.read(n)
            if len(buf) < n:
                break
            yield buf
    finally:
        try:
            p.stdout.close()
            if live and p.stdin:
                p.stdin.close()
        except Exception:
            pass
        try:
            p.wait(timeout=5)
        except subprocess.TimeoutExpired:
            p.kill()


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
              width: int = typer.Option(0, '-w', '--width', help='输出列数 (默认跟着终端宽度)'),
              height: int = typer.Option(0, '--height', help='输出行数 (默认按比例, 装不下自动收窄)'),
              size: str = typer.Option('', '--size', help='尺寸, 如 120x40 (= -w 120 --height 40)'),
              fps: float = typer.Option(12.0, '--fps', help='播放帧率 (终端刷不过来就调小)'),
              chars: str = typer.Option(RAMP, '--chars', help='灰度字符梯 (从暗到亮)'),
              invert: bool = typer.Option(False, '--invert', help='反转明暗'),
              start: float = typer.Option(0.0, '--start', help='从第几秒开始'),
              dur: float = typer.Option(0.0, '--dur', help='只放多少秒 (0=全部)'),
              loop: bool = typer.Option(False, '--loop', help='放完再来一遍'),
              mute: bool = typer.Option(False, '--mute', help='不放音轨 (默认有播放器时同步放)'),
              download: bool = typer.Option(False, '--download',
                                            help='URL 整段下到临时文件 (默认边收边放)'),
              player: str = typer.Option(None, '--player', help='指定播放器 (默认自动找)')):
    """视频转字符画播放 (Bad Apple 效果; URL 边收边放, 不全量下载; 需要 ffmpeg)"""
    if len(chars) < 2:
        print('error: --chars 至少要 2 个字符', file=sys.stderr)
        return 2
    tmp = None
    live = None
    env = _child_env(src)
    try:
        _need('ffmpeg')
        if src.startswith(('http://', 'https://')) and not download:
            try:                            # ① 交给 ffmpeg 自己读: 能 range/seek, HLS 也能放
                size = _probe_size(src, env)
            except Exception:
                size = None
            if size is not None:
                path, vw, vh = src, size[0], size[1]
            else:
                print('提示: ffmpeg 直接读不动这个 URL, 改走 webtool 通道流式读', file=sys.stderr)
                live = _Live(src)           # ② webtool 通道边收边喂, 不整段下载
                size = live.probe_size()
                if size is None:            # ③ 索引在文件尾, 只有整段下载
                    print('提示: 这条流不可顺序读 (索引在文件尾), 退回整段下载', file=sys.stderr)
                    path = live.spill()
                    tmp, live = path, None
                    vw, vh = _probe_size(path)
                else:
                    path, vw, vh = 'pipe:0', size[0], size[1]
        else:
            path, is_tmp = _local(src)
            tmp = path if is_tmp else None
            vw, vh = _probe_size(path)
        sw, sh = _size.parse_size(size)
        auto = not (sw or width or sh or height)
        w = max(1, sw or width or _size.auto_cols())
        if sh or height:
            h = max(1, sh or height)
        elif auto:
            w, h = _size.fit_box(vw, vh, w, _size.auto_rows())
        else:
            h = max(1, round(vh / vw * w * 0.5))
    except Exception as e:
        print(f'error: {e}', file=sys.stderr)
        return 2
    render = _mk_render(chars, invert, w)
    proc = None
    if not mute:
        if start or dur:
            print('提示: 带 --start/--dur 时不同步音轨, 只放画面', file=sys.stderr)
        elif live is not None:
            print('提示: 流式播放不同步音轨 (要音轨加 --download)', file=sys.stderr)
        else:
            cmd = _find_player(player)
            if cmd:
                try:
                    proc = subprocess.Popen(cmd + [path], env=env)
                except OSError:
                    proc = None
            else:
                print('提示: 没找到播放器, 只有画面没有声音 (可用 --player 指定)', file=sys.stderr)

    opened = [False]

    def one_pass(stream):
        src_arg = 'pipe:0' if stream else path
        return (render(buf) for buf in _frames(src_arg, w, h, fps, start, dur, stream, env))

    def frames_txt():
        nonlocal live
        if live is None:
            return one_pass(None)
        if opened[0]:                    # 上一轮把这条流读完了 (管道读完就没了)
            live.close()
            live = _Live(src, head=False)
        opened[0] = True
        return one_pass(live)

    try:
        _play(frames_txt, fps, loop)
    except KeyboardInterrupt:
        return 130
    finally:
        if live is not None:
            live.close()
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


def _music_frames(path, freqs, costs, rate, fps, bands, rows, start, dur, title, live=None, env=None):
    win = max(64, int(rate / fps))
    cmd = [_exe('ffmpeg'), '-v', 'error'] + _probe_flags(path)
    if start and not live:            # 本地文件能 seek, 输入前定位最省事
        cmd += ['-ss', str(start)]
    cmd += ['-i', path]
    if start and live:                # 管道不可 seek, 只能边读边丢
        cmd += ['-ss', str(start)]
    if dur:
        cmd += ['-t', str(dur)]
    cmd += ['-f', 's16le', '-ac', '1', '-ar', str(rate), '-']
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                         stdin=subprocess.PIPE if live else None, env=env)
    if live:
        live.feed(p.stdin)
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
        try:
            p.stdout.close()
            if live and p.stdin:
                p.stdin.close()
        except Exception:
            pass
        try:
            p.wait(timeout=5)
        except subprocess.TimeoutExpired:
            p.kill()


@app.command('music')
def music_cmd(src: str = typer.Argument(..., help='音频路径或 URL (http/https 走代理规则)'),
              bands: int = typer.Option(0, '--bands', help='频谱柱数 (列数; 默认跟终端宽度, 上限 64)'),
              rows: int = typer.Option(0, '--rows', help='柱子最高多少行 (默认跟终端高度)'),
              size: str = typer.Option('', '--size', help='尺寸, 如 100x16 (= --bands 100 --rows 16)'),
              fps: float = typer.Option(20.0, '--fps', help='刷新率 (每帧按它算采样窗口)'),
              rate: int = typer.Option(8000, '--rate', help='分析采样率 (越大越吃 CPU)'),
              start: float = typer.Option(0.0, '--start', help='从第几秒开始'),
              dur: float = typer.Option(0.0, '--dur', help='只放多少秒 (0=全部)'),
              loop: bool = typer.Option(False, '--loop', help='放完再来一遍'),
              download: bool = typer.Option(False, '--download',
                                            help='URL 整段下到临时文件 (默认边收边放)'),
              player: str = typer.Option(None, '--player', help='指定播放器 (默认自动找; 找不到只放画面)')):
    """音乐转字符律动: 频谱柱动画 (URL 边收边放, 不全量下载; 需要 ffmpeg 解码)"""
    try:
        sw, sh = _size.parse_size(size)
    except ValueError as e:
        print(f'error: {e}', file=sys.stderr)
        return 2
    bands = max(1, sw or bands or min(_size.auto_cols(), 64))
    rows = max(1, sh or rows or _size.auto_rows(24))
    tmp = None
    live = None
    env = _child_env(src)
    try:
        _need('ffmpeg')
        if src.startswith(('http://', 'https://')) and not download:
            if _can_read(src, env):            # ① ffmpeg 自己读: 能 range/seek, HLS 也能放
                path = src
            else:
                print('提示: ffmpeg 直接读不动这个 URL, 改走 webtool 通道流式读', file=sys.stderr)
                live = _Live(src)              # ② webtool 通道边收边喂
                if live.readable('a:0'):
                    path = 'pipe:0'
                else:                          # ③ 索引在文件尾之类, 只有整段下载
                    print('提示: 这条流不可顺序读, 退回整段下载', file=sys.stderr)
                    path = live.spill()
                    tmp, live = path, None
        else:
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
    proc = None
    if live is not None:
        print('提示: 流式播放不放音轨 (要音轨加 --download)', file=sys.stderr)
    else:
        proc = _find_player(player)
        if proc:
            try:
                proc = subprocess.Popen(proc + [path], env=env)
            except OSError:
                proc = None
        if not proc:
            print('提示: 没找到 ffplay/aplay/mpv/afplay 这类播放器, 只有画面没有声音 '
                  '(可用 --player 指定)', file=sys.stderr)

    opened = [False]

    def frames_txt():
        nonlocal live
        if live is None:
            return _music_frames(path, freqs, costs, rate, fps, bands, rows, start, dur,
                         title, None, env)
        if opened[0]:                      # 上一轮把这条流读完了, 重开一条
            live.close()
            live = _Live(src, head=False)
        opened[0] = True
        return _music_frames('pipe:0', freqs, costs, rate, fps, bands, rows, start, dur,
                             title, live, env)
    try:
        _play(frames_txt, fps, loop)
    except KeyboardInterrupt:
        return 130
    finally:
        if live is not None:
            live.close()
        if proc:
            proc.terminate()
        if tmp:
            os.unlink(tmp)
    return 0
