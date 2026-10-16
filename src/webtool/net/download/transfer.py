"""下载主体: 单连接流式写盘 + 多连接分片 + 熔断记账

从 net/download 拆出 (P4); 经 net/download/__init__ 再导出。
"""
import json
import os
import shutil
import sys
import threading
import time

from webtool.core.logging import get_logger
from webtool.core.resilient import MAX_WORKERS as JOBS_MAX
from webtool.net.download.progress import Progress, human
from webtool.net.download.resume import (
    _drop_meta, _meta_path, _save_meta, part_path, request_headers,
    resume_state, total_of, validator_of,
)

logger = get_logger(__name__)

CHUNK = 64 * 1024


def download(url, path, opener, *, progress=None, t0=None, chunk=CHUNK,
             opened=None, jobs=1):
    """下载 url 到 path (统一入口)。返回结果 dict (成功带 file/size, 失败带 error)

    jobs>1 或"上次就是分片下到一半" → 多连接分片; 否则单连接。分片现场记在同一个
    .part.meta 里, 所以续传时不必再指定 --jobs, 会接着上次的段数继续。

    熔断: 入口查一次 (打开就短路, 连试探都省), 结果记账 —— 下载是重通道, 站点
    挂了还一遍遍拉几百 MB 最浪费; 证书错不计入 (配置问题, 见 resilient.count_failure)。
    """
    from webtool.core.resilient import count_failure, guard
    from webtool.net.tls import TlsError
    br = guard(url)
    try:
        if jobs > 1 or _seg_meta(path, url) is not None:
            r = download_parallel(url, path, opener, jobs=jobs, progress=progress,
                                  t0=t0, chunk=chunk)
        else:
            r = _download_single(url, path, opener, progress=progress, t0=t0,
                                 chunk=chunk, opened=opened)
    except Exception as e:
        count_failure(br, e, exempt=(TlsError,))
        raise
    if r.get('error'):
        # 失败以 dict 形式返回 (不抛): 这类"站点不给数据"同样要算进熔断
        br.record(False)
    else:
        br.record(True)
    return r


def _download_single(url, path, opener, *, progress=None, t0=None, chunk=CHUNK,
                     opened=None):
    """单连接下载。返回结果 dict (成功带 file/size, 失败带 error)

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


# 多连接分片下载
# aria2/IDM 那一套: 先探一发 Range 确认服务端认账, 再把文件切成 N 段并发收。
# 段不是各自一个文件再拼接 —— 那样完事还要读一遍写一遍 (等于把文件抄一次盘),
# 而磁盘偏移写入本来就支持并发写不相交区间: 直接把 .part 预分配成总大小,
# 每段 seek 到自己的偏移写。失败时各段进度记在 meta 里, 续传只补没下完的部分。

# 连接数封顶 = 全仓并发上限 (core.resilient.MAX_WORKERS): 再多收益被站点限速
# 吃掉, 且并发越高越像扫描; 数字只在一个地方定义
MIN_SPLIT = 1024 * 1024        # 小于 1MB 不值得切, 切了也是连接开销占大头


def _seg_meta(path, url):
    """读分片现场 (没有/不是分片/url 不符就返回 None)"""
    part = part_path(path)
    if not os.path.exists(part):
        return None
    try:
        with open(_meta_path(part), encoding='utf-8') as f:
            meta = json.load(f)
    except Exception:
        return None
    if meta.get('url') != url or 'segs' not in meta:
        return None
    return meta


def _segments(total, jobs):
    """把 [0, total) 切成 jobs 段, 段尾含"""
    step = total // jobs
    segs = []
    for i in range(jobs):
        start = i * step
        end = total - 1 if i == jobs - 1 else (i + 1) * step - 1
        segs.append([start, end])
    return segs


def download_parallel(url, path, opener, *, jobs=4, progress=None, t0=None,
                      chunk=CHUNK):
    """多连接分片下载 (服务端不认 Range 就自动退回单连接)"""
    import concurrent.futures as cf
    t0 = t0 or time.time()
    part = part_path(path)
    os.makedirs(os.path.dirname(os.path.abspath(path)) or '.', exist_ok=True)
    meta = _seg_meta(path, url)
    if meta is None:
        resp, status, via, headers = opener({'Accept-Encoding': 'identity',
                                             'Range': 'bytes=0-0'})
        total = total_of(headers, status, 0)
        _close(resp)
        if status != 206 or total <= 0:
            # 200 就是"我不认 Range": 多连接无从下手, 单连接拿全量
            return _download_single(url, path, opener, progress=progress, t0=t0,
                                    chunk=chunk)
        jobs = max(1, min(jobs, JOBS_MAX, max(1, total // MIN_SPLIT)))
        meta = {'url': url, 'total': total, 'validator': validator_of(headers),
                'segs': _segments(total, jobs), 'done': [0] * jobs}
    total = meta['total']
    segs = meta['segs']
    jobs = len(segs)
    stopped = threading.Event()
    pr = Progress(total=total, done=sum(meta['done']), t0=t0, progress=progress,
                  label=f'下载中 ({jobs} 连接)')
    if jobs > 1:
        print(f'  {jobs} 连接分片下载: 共 {human(total)}', file=sys.stderr)

    def worker(i):
        start, end = segs[i]
        if stopped.is_set():
            return None
        off = start + meta['done'][i]
        if off > end:
            return None
        req = {'Accept-Encoding': 'identity', 'Range': f'bytes={off}-{end}'}
        if meta.get('validator'):
            req['If-Range'] = meta['validator']
        try:
            resp, status, _v, _h = opener(req)
        except Exception as e:
            stopped.set()
            return f'{type(e).__name__}: {str(e)[:80]}'
        if status == 416:
            _close(resp)
            meta['done'][i] = end - start + 1
            return None
        if status != 206:
            # If-Range 判定资源变了 (或服务端反悔): 整份作废重下, 不许拼
            _close(resp)
            stopped.set()
            return f'服务端返回 {status} 而非 206 (资源可能已变)'
        try:
            with open(part, 'r+b') as f:
                f.seek(off)
                for buf in resp.iter_content(chunk):
                    if not buf:
                        continue
                    if stopped.is_set():
                        return 'aborted'
                    f.write(buf)
                    meta['done'][i] += len(buf)
                    pr.update(len(buf))
        except Exception as e:
            stopped.set()
            return f'{type(e).__name__}: {str(e)[:80]}'
        finally:
            _close(resp)
        if start + meta['done'][i] - 1 < end:
            stopped.set()
            return '连接提前结束'
        return None

    # 按总大小把 .part 撑开, 各段才好在自己的偏移上直接写。注意**不能**用 'wb':
    # 续传时这个文件里已经有下好的段, 'wb' 一开就把它们清零了 (truncate 不改大小,
    # 但内容没了, 于是"续传"把已下的部分重新变成零字节)
    if os.path.exists(part) and os.path.getsize(part) == total:
        pass
    else:
        with open(part, 'r+b' if os.path.exists(part) else 'wb') as f:
            f.truncate(total)
    err = None
    with cf.ThreadPoolExecutor(max_workers=jobs) as ex:
        for r in ex.map(worker, range(jobs)):
            if r and not err:
                err = r
    got = sum(meta['done'])
    if err or got < total:
        _write_seg_meta(part, meta)
        pr.done = got
        _finish_progress(pr, path, got, total, 0)
        return {'url': url,
                'error': (f'{err}; ' if err else '')
                         + f'分片未下完 ({human(got)}/{human(total)}), 再跑一次接着续',
                'partial': os.path.abspath(part), 'resumed_from': got}
    os.replace(part, path)
    _drop_meta(part)
    pr.done = got
    pr.finish()
    return {'file': os.path.abspath(path), 'size': got, 'status': 206,
            'via': 'cffi', 'jobs': jobs, 'took_ms': int((time.time() - t0) * 1000)}


def _write_seg_meta(part, meta):
    try:
        with open(_meta_path(part), 'w', encoding='utf-8') as f:
            json.dump(meta, f)
    except OSError:
        pass


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
        logger.debug('忽略异常 (容忍路径)', exc_info=True)
