"""webtool site 站点: sov2ex (V2EX 全文检索), 与 moresites 同约定, 走指纹通道。

热榜类源 (reddit/hn_official/lobsters/github_trend) 在 engines/hotsites.py。
"""

import json
import re
import urllib.parse

import sys as _sys


def _clean(s):
    """去 HTML 标签/高亮 em 标记"""
    s = re.sub(r'</?em[^>]*>', '', s or '')
    s = re.sub(r'<[^>]+>', '', s)
    return re.sub(r'\s+', ' ', s).strip()

_sites = _sys.modules.get('webtool.engines.sites')
if _sites is None:
    from webtool import sites as _sites
    _sites = _sys.modules['webtool.engines.sites']

from webtool.engines.sites import _headers, _mk, _fetch


def sov2ex(q, limit=10, proxy=None, timeout=15):
    """V2EX 全文搜索 (sov2ex 社区索引 API)"""
    kw = (q or '').strip()
    if not kw:
        kw = 'v2ex'
    url = ('https://www.sov2ex.com/api/search?q=' + urllib.parse.quote(kw)
           + f'&size={min(limit, 30)}')
    txt, st, _ = _fetch(url, proxy, timeout,
                        headers=_headers(url, 'rest', {'Accept': 'application/json'}))
    o = json.loads(txt)
    out = []
    for x in (o.get('hits') or []):
        s = x.get('_source') or {}
        title = s.get('title') or ''
        if not title:
            continue
        tid = s.get('id')
        out.append(_mk(title, f'https://www.v2ex.com/t/{tid}' if tid else '',
                       re.sub(r'<[^>]+>', '', str(s.get('content') or ''))[:140],
                       extra={'node': s.get('node_name'),
                              'replies': s.get('replies')}))
    return out[:limit]


