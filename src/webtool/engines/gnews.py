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
import urllib.request

from ..http import build_opener

_CACHE = {}          # gnews_id -> (real_url, ts)
_TTL = 7 * 86400
_STATE = {'fails': 0, 'skip_until': 0}   # 连续失败熔断, 防止烧时间

_BATCH_URL = 'https://news.google.com/_/DotsSplashUi/data/batchexecute'


def decode(link, proxy=None, timeout=15):
    """news.google.com/articles/... → 真实 URL; 非跳转链原样返回

    返回 None 表示解码失败 (页面改版/接口下线/熔断中)。
    """
    if 'news.google.com/rss/articles/' not in link \
            and 'news.google.com/articles/' not in link:
        return link
    gid = link.rstrip('/').rsplit('/', 1)[-1]
    hit = _CACHE.get(gid)
    if hit and time.time() - hit[1] < _TTL:
        return hit[0]
    if time.time() < _STATE['skip_until']:
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
            _STATE['fails'] = 0
            _CACHE[gid] = (real, time.time())
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
    _STATE['fails'] += 1
    if _STATE['fails'] >= 3:
        _STATE['skip_until'] = time.time() + 600   # 熔断 10 分钟


def cache_info():
    return {'entries': len(_CACHE),
            'fails': _STATE['fails'],
            'skip': max(0, int(_STATE['skip_until'] - time.time()))}
