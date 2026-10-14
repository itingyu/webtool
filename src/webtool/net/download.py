"""下载: 流式写盘 + 断点续传 + 进度

二进制目标落盘本质就是个下载动作, 就得按下载的规矩办:

1. **边收边写** —— 不把整个文件读进内存。手机内存经不起一个 200MB 的视频,
   而且"先整段读、再写盘"在超大文件上必然失败, 那时你已经白下了九成。
2. **断了能续** —— `.part` 临时文件 + `Range` 续传, 并带 `If-Range` 验证器:
   没有验证器的续传是赌博, 服务端资源换了照样接着写, 拼出一个"前半旧后半新"的
   坏文件, 打开才知道。
3. **进度看得见** —— 长任务不吭声最难受。TTY 下原地刷一行 (带速率与 ETA),
   非 TTY (管道/日志/agent 抓取) 只报一句结果 —— 几百行 `\r` 进度塞进日志是污染。

这个模块不碰浏览器指纹/代理/TLS: 请求由调用方通过 `opener` 注入, 这里只负责
续传判断、写盘、进度。下载逻辑跟反爬纠缠在一起, 两边都没法单独测。
"""

import json
import os
import re
import shutil
import sys
import time

CHUNK = 64 * 1024
# .part 的同伴: 记着"这是谁的、下到哪、服务端那份的验证器"。给 .part 再挂后缀
# (big.bin.part.meta), 而不是另起一个 big.bin.meta —— 后者会跟正式文件抢名字
_META_SUFFIX = '.meta'


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

    def update(self, n):
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


# --- 续传状态: 上次留下的 .part 与它的同伴 --------------------------------
# 只认"有 .meta 同伴的 .part": 孤零零一个 .part 无从知道它是谁下的、下到哪、
# 服务端那份还是不是同一份, 接着写就是赌。

def part_path(path):
    return path + '.part'


def _meta_path(part):
    return part + _META_SUFFIX


def resume_state(path, url):
    """看看能不能续: 返回 (已下字节数, 验证器); 不能续就是 (0, '')"""
    part = part_path(path)
    if not os.path.exists(part) or os.path.getsize(part) == 0:
        return 0, ''
    try:
        with open(_meta_path(part), encoding='utf-8') as f:
            meta = json.load(f)
    except Exception:
        os.remove(part)                  # 没有同伴/读不出来: 残渣, 清掉重下
        return 0, ''
    if meta.get('url') != url:
        os.remove(part)                  # 同一个落点换了 URL: 上一份不是这东西
        return 0, ''
    return os.path.getsize(part), meta.get('validator', '')


def _save_meta(part, url, validator, total):
    try:
        with open(_meta_path(part), 'w', encoding='utf-8') as f:
            json.dump({'url': url, 'validator': validator, 'total': total}, f)
    except OSError:
        pass


def _drop_meta(part):
    for p in (part, _meta_path(part)):
        try:
            os.remove(p)
        except OSError:
            pass


def validator_of(headers):
    """续传校验用哪个头: ETag 优先, 退到 Last-Modified"""
    return headers.get('etag') or headers.get('last-modified') or ''


def total_of(headers, status, resumed):
    """这一份总共多大: Content-Range 的 /z 最准, 退到 Content-Length"""
    m = re.search(r'/(\d+)\s*$', headers.get('content-range') or '')
    if m:
        return int(m.group(1))
    cl = headers.get('content-length')
    if cl and cl.isdigit():
        return int(cl) + (resumed if status == 206 else 0)
    return 0


def request_headers(resumed, validator):
    """续传请求头。identity 编码是必须的: 续传按字节算偏移, 中间被压过一遍就错位"""
    req = {'Accept-Encoding': 'identity'}
    if resumed:
        req['Range'] = f'bytes={resumed}-'
        if validator:
            req['If-Range'] = validator
    return req


def download(url, path, opener, *, progress=None, t0=None, chunk=CHUNK,
             opened=None):
    """下载 url 到 path。返回结果 dict (成功带 file/size, 失败带 error)

    opener(headers) -> (resp, status, via, headers): 流式请求由调用方注入,
    这里不碰浏览器指纹与代理。

    opened: 调用方已经打开的 (resp, status, via, headers), 给它就省掉一次请求
    —— 判类型时反正要开一个, 别开完发现是二进制又重开一个。只在"不需要发 Range"
    时才该给 (发了 Range 的请求必须带 Range 头重开)。

    落盘策略: 先写 `path + '.part'`, 下完再改名。半成品不许顶着正式文件名 ——
    进程被杀/断网时留下一个看起来正常的文件, 比留着 .part 危险得多。
    """
    t0 = t0 or time.time()
    part = part_path(path)
    os.makedirs(os.path.dirname(os.path.abspath(path)) or '.', exist_ok=True)
    started = resume_state(path, url)
    signal = '断点续传' if started[0] else '开始下载'
    if opened is not None and not started[0]:
        resp, status, via, headers = opened
    else:
        resp, status, via, headers = opener(request_headers(*started))
    if started[0]:
        print(f'  {signal}: 已有 {human(started[0])}, 从断点接着收', file=sys.stderr)
    resumed = started[0]

    if resumed and status == 416:
        # "你要的范围不存在" = 本地那份已经够了 (上次下完就差改名)
        os.replace(part, path)
        _drop_meta(part)
        return {'file': os.path.abspath(path), 'size': resumed, 'status': status,
                'via': via, 'resumed_from': resumed, 'took_ms': int((time.time() - t0) * 1000)}
    if status >= 400:
        body = b''
        try:
            body = next(iter(resp.iter_content(200)), b'')
        except Exception:
            pass
        _close(resp)
        note = body.decode('utf-8', 'replace').strip()[:120] if body else ''
        return {'url': url, 'status': status, 'error': f'HTTP {status} {note}'.strip()}

    if resumed:
        enc = (headers.get('content-encoding') or 'identity').lower()
        if status != 206 and enc not in ('identity', 'none'):
            # 200 = 服务端没搭理 Range (或被 If-Range 判为资源变了); 有压缩过更没法接
            # 着写。本地那份作废, 从头下 —— 拼错比慢更糟。
            os.remove(part)
            resumed = 0

    total = total_of(headers, status, resumed)
    free = shutil.disk_usage(os.path.dirname(os.path.abspath(path)) or '.').free
    if total and total - resumed > free * 0.98:
        _close(resp)
        return {'url': url, 'error': f'磁盘空间不够: 还需 {human(total - resumed)},'
                                     f' 可用 {human(free)}'}
    _save_meta(part, url, validator_of(headers) or started[1], total)
    pr = Progress(total=total, done=resumed, t0=t0, progress=progress,
                  label=f'{signal}中')
    got = resumed
    try:
        with open(part, 'ab' if resumed else 'wb') as f:
            for buf in resp.iter_content(chunk):
                if not buf:
                    continue
                f.write(buf)
                got += len(buf)
                pr.update(len(buf))
    except Exception as e:
        # 网络断了: .part 和同伴都留着, 再跑一次就从这里接上
        pr.done = got
        _finish_progress(pr, path, got, total, resumed, aborted=True)
        return {'url': url, 'error': f'下载中断 ({type(e).__name__}: {str(e)[:100]}), '
                                     f'已下 {human(got)}'
                                     + (f'/{human(total)}' if total else ''),
                'partial': os.path.abspath(part), 'resumed_from': resumed}
    finally:
        _close(resp)

    if not total:
        total = got
    if got < total:
        # 连接正常结束但没读完: 别改名, 留着 .part 续
        pr.done = got
        _finish_progress(pr, path, got, total, resumed, aborted=True)
        return {'url': url, 'error': f'只收到 {human(got)}/{human(total)}, 未下完, '
                                     f'再跑一次从断点续',
                'partial': os.path.abspath(part), 'resumed_from': resumed}
    os.replace(part, path)               # 同目录改名: 要么完整文件, 要么 .part
    _drop_meta(part)
    pr.done = got
    pr.finish(resumed_from=resumed)
    return {'file': os.path.abspath(path), 'size': got, 'status': status, 'via': via,
            'resumed_from': resumed, 'took_ms': int((time.time() - t0) * 1000)}


def _finish_progress(pr, path, got, total, resumed, aborted=False):
    el = max(time.time() - pr.t0, 1e-6)
    if pr.tty:
        sys.stderr.write('\r' + ' ' * 78 + '\r')
    print(f'已下 {human(got)}/{human(total)} · {el:.1f}s · {human(got / el)}/s'
          + (f' · 续传 {human(resumed)}' if resumed else ''),
          file=sys.stderr)
    sys.stderr.flush()


def _close(resp):
    try:
        resp.close()
    except Exception:
        pass
