# -*- coding: utf-8 -*-
"""google news 跳转链解码: batchexecute 接口还原真实文章 URL

article 页 c-wiz 节点带 data-n-a-id/ts/sg, POST batchexecute (f.req 携带
Fbv4je+"garturlreq") 返回真实 URL; id 去重缓存 7 天。
"""
import gzip
import io
import json
import logging
import re
import time
import urllib.parse
import urllib.request

from .. import state, transport as _t
from ..http import build_opener

log = logging.getLogger(__name__)

_TTL = 7 * 86400


def _read_body(r, max_bytes=2 * 1024 * 1024):
    """读响应体并按 Content-Encoding 解压。

    本模块走 urllib 通道, urllib 不会自动解 gzip, 裸 r.read() 得到的压缩
    字节会让 data-n-a-* 三参数全部匹配不上。
    """
    raw = r.read(max_bytes)
    if r.headers.get('Content-Encoding') == 'gzip':
        try:
            raw = gzip.GzipFile(fileobj=io.BytesIO(raw)).read()
        except Exception:
            pass
    elif r.headers.get('Content-Encoding') == 'deflate':
        try:
            import zlib
            raw = zlib.decompress(raw, -zlib.MAX_WBITS)
        except Exception:
            pass
    return raw.decode('utf-8', 'ignore')

_BATCH_URL = 'https://news.google.com/_/DotsSplashUi/data/batchexecute'


def _cache_get(gid):
    hit = state.get_breaker('gnews_cache').get(gid)
    if hit:
        url, ts = hit
        if time.time() - ts < _TTL:
            return url
    return None


def _cache_put(gid, url):
    b = dict(state.get_breaker('gnews_cache'))
    b[gid] = [url, time.time()]
    if len(b) > 500:
        for k in sorted(b, key=lambda k: b[k][1])[:len(b) - 500]:
            b.pop(k, None)
    state.set_breaker('gnews_cache', **b)


def decode(link, proxy=None, timeout=15):
    """news.google.com/articles/... → 真实 URL; 非跳转链原样返回

    返回 None 表示解码失败 (页面改版/接口下线/熔断中)。
    """
    if 'news.google.com/rss/articles/' not in link \
            and 'news.google.com/articles/' not in link:
        return link
    gid = link.rstrip('/').rsplit('/', 1)[-1]
    hit = _cache_get(gid)
    if hit:
        return hit
    br = state.get_breaker('gnews')
    if time.time() < float(br.get('skip_until', 0)):
        return None

    op = build_opener(proxy)
    _prof = _t.PROFILES[_t._pick_profile('gnews')]
    ua = _prof['ua']
    try:
        req = urllib.request.Request(link, headers=_t.headers_for(
            'nav', link, full=True, profile=_prof))
        with op.open(req, timeout=timeout) as r:
            page = _read_body(r)
        gid_p = re.search(r'data-n-a-id="([^"]*)"', page)
        ts_p = re.search(r'data-n-a-ts="([^"]*)"', page)
        sg_p = re.search(r'data-n-a-sg="([^"]*)"', page)
        if not (gid_p and ts_p and sg_p):
            log.debug('gnews: article 页无 c-wiz 三参数 (len=%d), 判为改版',
                      len(page))
            _fail()
            return None
        real = _batchexecute(gid_p.group(1), int(ts_p.group(1)),
                             sg_p.group(1), op, _prof, timeout)
        if real:
            state.set_breaker('gnews', fails=0)
            _cache_put(gid, real)
            return real
        log.debug('gnews: batchexecute 未返回非 google 域名')
        _fail()
        return None
    except Exception as e:
        log.debug('gnews: 解码异常 %s: %s', type(e).__name__, e)
        _fail()
        return None


def _batchexecute(gid, ts, sg, op, prof, timeout):
    payload = json.dumps(["garturlreq",
        [["X", "X", ["X", "X"], None, None, 1, 1, "US:en", None, 1,
          None, None, None, None, 0, 1],
         "X", "X", 1, [1, 1, 1], 1, 1, None, 0, 0, None, 0],
        gid, ts, sg])
    freq = json.dumps([[["Fbv4je", payload, "wrt.org"]]])
    req = urllib.request.Request(
        _BATCH_URL,
        data=f'f.req={urllib.parse.quote(freq)}'.encode(),
        headers={'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8',
                 'User-Agent': prof['ua'],
                 'Accept-Language': _t.LANG_EN,
                 'Referer': 'https://news.google.com/'})
    with op.open(req, timeout=timeout) as r:
        body = _read_body(r)
    m = re.search(r'https?://[^\s"\\]+', body)
    if m and 'news.google.com' not in m.group(0):
        return m.group(0)
    log.debug('gnews: batchexecute 响应里没有非 google 域名 (len=%d)', len(body))
    return None


def _fail():
    br = state.get_breaker('gnews')
    fails = int(br.get('fails', 0)) + 1
    if fails >= 3:
        state.set_breaker('gnews', fails=fails,
                          skip_until=time.time() + 600)   # 熔断 10 分钟
    else:
        state.set_breaker('gnews', fails=fails)


def cache_info():
    b = state.get_breaker('gnews_cache')
    br = state.get_breaker('gnews')
    return {'entries': len(b),
            'fails': br.get('fails', 0),
            'skip': max(0, int(float(br.get('skip_until', 0)) - time.time()))}
