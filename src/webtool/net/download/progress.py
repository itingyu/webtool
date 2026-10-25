"""下载进度显示: 字节数说人话 + TTY 原地刷新

从 net/download 拆出 (P4); 经 net/download/__init__ 再导出。
"""
import sys
import threading
import time


def human(n):
    """字节数说成人话"""
    v = float(n)
    for unit in ('B', 'KB', 'MB', 'GB'):
        if v < 1024 or unit == 'GB':
            return f'{v:.0f} {unit}' if unit == 'B' else f'{v:.1f} {unit}'
        v /= 1024
    return f'{v:.1f} GB'


def _eta(sec):
    m, s = divmod(int(sec), 60)
    return f'{m}:{s:02d}' if m else f'{s}s'


class Progress:
    """下载进度。TTY 原地刷新, 非 TTY 只报结果

    progress: None = 自动 (是终端才刷), True/False = 强制开/关。
    """

    def __init__(self, total=0, done=0, t0=None, progress=None, label='下载中'):
        self.total, self.done = total, done
        self.t0 = t0 or time.time()
        self.label = label
        self.tty = sys.stderr.isatty() if progress is None else bool(progress)
        self._tick = 0.0
        self.lock = threading.Lock()      # 多连接时几个线程共用一个进度

    def update(self, n):
        with self.lock:
            self.done += n
        now = time.time()
        # 每 0.2s 刷一次就够人看: 每个 chunk 都刷等于把终端写爆
        if not self.tty or now - self._tick < 0.2:
            return
        self._tick = now
        el = max(now - self.t0, 1e-6)
        bps = self.done / el
        line = f'  {self.label} {human(self.done)}'
        if self.total:
            line += f' / {human(self.total)} {self.done * 100 // self.total}%'
        line += f'  {human(bps)}/s'
        if self.total and bps > 1:
            line += f'  ETA {_eta((self.total - self.done) / bps)}'
        sys.stderr.write('\r' + line + '    ')
        sys.stderr.flush()

    def finish(self, resumed_from=0):
        """报一句结果。**不报落点** —— 落点由调用方说 (fetch 会打"已存: ..."),
        这里再说一遍就是同一件事打印两遍。"""
        el = max(time.time() - self.t0, 1e-6)
        if self.tty:
            sys.stderr.write('\r' + ' ' * 78 + '\r')
        extra = f' · 续传 {human(resumed_from)}' if resumed_from else ''
        print(f'下载完成: {human(self.done)} · {el:.1f}s · '
              f'{human(self.done / el)}/s{extra}', file=sys.stderr)
        sys.stderr.flush()


# 续传状态: 上次留下的 .part 与它的同伴
# 只认"有 .meta 同伴的 .part": 孤零零一个 .part 无从知道它是谁下的、下到哪、
# 服务端那份还是不是同一份, 接着写就是赌。

