# -*- coding: utf-8 -*-
"""webtool site 站点: thepaper/eastmoney, 全走 transport 指纹通道。

热榜类源在 engines/hotsites.py (rank 命令用); 36kr 被火山引擎 JS 挑战
拦截 (纯 HTTP 拿不到数据), 不进内置表。
"""
import json
import re
import urllib.parse

import sys as _sys
# sites 在尾部 _lazy_extend() 里导入本模块 (半初始化), 从 sys.modules 直接取
_sites = _sys.modules.get('webtool.engines.sites')
if _sites is None:
    from webtool import sites as _sites
from webtool import transport
from webtool.engines.sites import _headers, _mk, _fetch


def _clean(s):
    """去 HTML 标签/高亮 em 标记"""
    s = re.sub(r'</?em[^>]*>', '', s or '')
    s = re.sub(r'<[^>]+>', '', s)
    return re.sub(r'\s+', ' ', s).strip()


def thepaper(q, limit=10, proxy=None, timeout=15):
    """澎湃新闻搜索 (api.thepaper.cn POST 免登录; 同档案指纹 session)"""
    url = 'https://api.thepaper.cn/search/web/news'
    headers = _headers(url, 'api', {'Referer': 'https://www.thepaper.cn/',
                                    'Origin': 'https://www.thepaper.cn'})
    kw = (q or '').strip() or '热点'
    s, prof = transport._new_session(
        transport._pick_profile('thepaper'), proxy or None, None)
    r = s.post(url, json={'word': kw, 'orderType': 3, 'pageNum': 1,
                          'pageSize': min(limit, 20)},
               headers=headers, timeout=timeout)
    if r.status_code != 200:
        raise RuntimeError(f'HTTP {r.status_code}')
    out = []
    for x in (r.json().get('data') or {}).get('list') or []:
        title = _clean(str(x.get('name') or ''))
        if not title:
            continue
        cid = x.get('contId') or ''
        link = x.get('link') or (f'https://www.thepaper.cn/newsDetail_forward_{cid}' if cid else '')
        out.append(_mk(title, link, _clean(str(x.get('summary') or ''))[:140],
                       extra={'time': x.get('pubTime'), 'praise': x.get('praiseTimes')}))
    return out[:limit]


def eastmoney(q, limit=10, proxy=None, timeout=15):
    """东方财富资讯搜索 (search-api-web jsonp 免登录)"""
    kw = (q or '').strip()
    if not kw:
        return []
    param = {'uid': '', 'keyword': kw, 'type': ['cmsArticleWebOld'],
             'client': 'web', 'clientType': 'web', 'clientVersion': 'curr',
             'param': {'cmsArticleWebOld': {'searchScope': 'default', 'sort': 'default',
                                            'pageIndex': 1, 'pageSize': min(limit, 20),
                                            'preTag': '<em>', 'postTag': '</em>'}}}
    url = ('https://search-api-web.eastmoney.com/search/jsonp?cb=cb&param='
           + urllib.parse.quote(json.dumps(param, separators=(',', ':'))))
    headers = _headers(url, 'api', {'Referer': 'https://so.eastmoney.com/'})
    txt, st, _ = _fetch(url, proxy, timeout, headers)
    if txt.startswith('cb('):
        txt = txt[txt.find('(') + 1:txt.rfind(')')]
    o = json.loads(txt)
    out = []
    for x in (o.get('result') or {}).get('cmsArticleWebOld') or []:
        title = _clean(str(x.get('title') or ''))
        if not title:
            continue
        out.append(_mk(title, x.get('url') or '',
                       _clean(str(x.get('content') or ''))[:140],
                       extra={'media': x.get('mediaName'), 'time': x.get('date')}))
    return out[:limit]


