"""断点续传现场: .part 同伴元数据 + Range/If-Range 请求头

从 net/download 拆出 (P4); 经 net/download/__init__ 再导出。
"""
import json
import os
import re

# .part 的同伴: 记着"这是谁的、下到哪、服务端那份的验证器"。给 .part 再挂后缀
# (big.bin.part.meta), 而不是另起一个 big.bin.meta —— 后者会跟正式文件抢名字
_META_SUFFIX = '.meta'


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
    if 'segs' in meta:
        return 0, ''                     # 分片的现场归 download_parallel 管
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


