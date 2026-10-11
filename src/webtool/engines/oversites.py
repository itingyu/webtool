# -*- coding: utf-8 -*-
"""webtool site 国际站点组 (oversites.py): 与 moresites 同约定, 全走反探测指纹通道

- so_v2ex:sov2ex 搜索 (V2EX 全文检索)
- 热榜类 (reddit/hn_official/lobsters/github_trend) 已迁至 engines/hotsites.py,
  由 rank 命令使用 (webtool rank hn_official github_trend ...)

- 代理: 这些站直连可达 (本环境); 若环境受限, site 分发器会按 proxy hint 走代理
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
if _sites is None:                      # 独立导入: 补一次完整 sites 加载 (半初始化时由 _lazy_extend 容错)
    from . import sites as _sites
    _sites = _sys.modules['webtool.engines.sites']

from .sites import _headers, _mk, _fetch


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


OVER_SITES = {
    'sov2ex':       {'fn': sov2ex,       'desc': 'V2EX 全文搜索 (sov2ex)', 'proxy': 'direct'},
}
