# -*- coding: utf-8 -*-
"""webtool site 搜索站点: thepaper/eastmoney

设计 (对齐用户要求: 站内搜索务必带反探测指纹):
- 全部走 transport.get(真浏览器 TLS 指纹 + XHR 头同源构造), 不用 urllib
- 知乎/头条/微博/百度/IT之家热榜及 reddit/hn/lobsters/github_trend
  已迁至 engines/hotsites.py, 由 rank 命令使用 (webtool rank ...)
- 36kr: 移动/桌面全线被火山引擎 JS 挑战拦截 (纯 HTTP 拿不到数据), 不进内置表
"""
import json
import re
import urllib.parse

import sys as _sys
# 循环导入规避: sites 在尾部 _lazy_extend() 里导入本模块,
# 此时sites模块已部分初始化 (SITES/工具函数已就绪), 从 sys.modules 直接取
_sites = _sys.modules.get('webtool.engines.sites')
if _sites is None:                      # 独立导入本模块时 (非经 sites), 正常导入
    from . import sites as _sites
from .. import transport
from .sites import _headers, _mk, _fetch


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


NEW_SITES = {
    'thepaper':  {'fn': thepaper,  'desc': '澎湃新闻搜索', 'proxy': 'direct'},
    'eastmoney': {'fn': eastmoney, 'desc': '东方财富资讯搜索', 'proxy': 'direct'},
}
