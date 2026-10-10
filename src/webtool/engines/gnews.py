# -*- coding: utf-8 -*-
"""google news 跳转链解码: batchexecute 接口还原真实文章 URL

原理 (2025+ 有效): article 页 c-wiz 节点带 data-n-a-id/ts/sg 三参数,
POST 到 news.google.com/_/DotsSplashUi/data/batchexecute (f.req 携带
Fbv4je+"garturlreq") 即返回真实 URL — 无需浏览器, 无需 JS 引擎,
纯 HTTP; id 去重缓存 7 天。

article 页本身 600KB, 此模块负责整条解析链:
article link → 抓页面提参数 → batchexecute → 原文 URL
"""
import json
import re
import time
import urllib.parse

from .. import state
from ..http import build_opener

_TTL = 7 * 86400

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
    # 上限保护: 只留最近 500 条
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
    ua = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'
    try:
        # 1) article 页 → 三参数 (c-wiz data-n-a-*)
        req = urllib.request.Request(link, headers={'User-Agent': ua})
        with op.open(req, timeout=timeout) as r:
            page = r.read(2 * 1024 * 1024).decode('utf-8', 'ignore')
        gid_p = re.search(r'data-n-a-id="([^"]*)"', page)
        ts_p = re.search(r'data-n-a-ts="([^"]*)"', page)
        sg_p = re.search(r'data-n-a-sg="([^"]*)"', page)
        if not (gid_p and ts_p and sg_p):
            _fail()
            return None
        real = _batchexecute(gid_p.group(1), int(ts_p.group(1)),
                             sg_p.group(1), op, ua, timeout)
        if real:
            state.set_breaker('gnews', fails=0)
            _cache_put(gid, real)
            return real
        _fail()
        return None
    except Exception:
        _fail()
        return None


def _batchexecute(gid, ts, sg, op, ua, timeout):
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
                 'User-Agent': ua, 'Referer': 'https://news.google.com/'})
    with op.open(req, timeout=timeout) as r:
        body = r.read().decode('utf-8', 'ignore')
    m = re.search(r'https?://[^\s"\\]+', body)
    if m and 'news.google.com' not in m.group(0):
        return m.group(0)
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
