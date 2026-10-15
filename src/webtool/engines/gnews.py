"""google news 跳转链解码: batchexecute 接口还原真实文章 URL

article 页 c-wiz 节点带 data-n-a-id/ts/sg, POST batchexecute (f.req 携带
Fbv4je+"garturlreq") 返回真实 URL; id 去重缓存 7 天。
"""
import json
import logging
import re
import time
import urllib.parse
from http import cookiejar

from webtool.core import state
from webtool.net import transport

log = logging.getLogger(__name__)

_TTL = 7 * 86400


# gzip/deflate 解压已收进 transport.Resp (urllib 底层不自动解压), 这里不再自己读体

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

    # 走 urllib 底层 (via='urllib') 而非 cffi: 这条通道的立身之本就是"换一套
    # HTTP/TLS 栈再试一次", 但线路/证书/头仍归 transport 那一层管。
    # cookiejar 两次请求共用, 与原实现同一个 opener 的行为一致。
    cj = cookiejar.CookieJar()
    try:
        page = transport.request('GET', link, kind='nav', proxy=proxy,
                                 timeout=timeout, via='urllib',
                                 cookiejar=cj).text
        gid_p = re.search(r'data-n-a-id="([^"]*)"', page)
        ts_p = re.search(r'data-n-a-ts="([^"]*)"', page)
        sg_p = re.search(r'data-n-a-sg="([^"]*)"', page)
        if not (gid_p and ts_p and sg_p):
            log.debug('gnews: article 页无 c-wiz 三参数 (len=%d), 判为改版',
                      len(page))
            _fail()
            return None
        real = _batchexecute(gid_p.group(1), int(ts_p.group(1)),
                             sg_p.group(1), cj, proxy, timeout)
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


def _batchexecute(gid, ts, sg, cookiejar, proxy, timeout):
    payload = json.dumps(["garturlreq",
        [["X", "X", ["X", "X"], None, None, 1, 1, "US:en", None, 1,
          None, None, None, None, 0, 1],
         "X", "X", 1, [1, 1, 1], 1, 1, None, 0, 0, None, 0],
        gid, ts, sg])
    freq = json.dumps([[["Fbv4je", payload, "wrt.org"]]])
    body = transport.request(
        'POST', _BATCH_URL, kind='xhr', referer='https://news.google.com/',
        lang=transport.LANG_EN, proxy=proxy, timeout=timeout, via='urllib',
        cookiejar=cookiejar,
        headers={'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8'},
        data=f'f.req={urllib.parse.quote(freq)}'.encode()).text
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
