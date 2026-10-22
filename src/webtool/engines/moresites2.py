"""webtool site 第二批: 关键词搜索型适配器, 全走指纹通道。

csdn_so (CSDN 问答) / juejin2 (掘金) / bili2 (B站, 需 buvid cookie) /
douban (HTML 版免登录) / gh_search (GitHub 仓库) / ithome_so (IT之家)。
"""

import json
import re
import urllib.parse

import sys as _sys

_sites = _sys.modules.get('webtool.engines.sites')
if _sites is None:
    from webtool import sites as _sites
from webtool.core import text
from webtool.engines.sites import _headers, _mk, _fetch, _post


_clean = text.clean_markup


# ============================================================ CSDN 问答

def csdn_so(q, limit=10, proxy=None, timeout=15):
    """CSDN 问答 · 服务端搜索页 (so.csdn.net/api/v3/search, t=ask)"""
    if not (q or '').strip():
        return []
    kw = urllib.parse.quote(q)
    url = (f'https://so.csdn.net/api/v3/search?q={kw}&t=ask&p=1&size={min(limit, 20)}')
    headers = _headers(url, 'api', {'Referer': f'https://so.csdn.net/so/search?q={kw}'})
    txt, st, _ = _fetch(url, proxy, timeout, headers)
    o = json.loads(txt)
    out = []
    for x in (o.get('result_vos') or []):
        title = _clean(str(x.get('title') or ''))
        if not title:
            continue
        out.append(_mk(title, x.get('url_location') or x.get('url') or '',
                       _clean(str(x.get('description') or ''))[:140] or None,
                       extra={'answers': x.get('answer_count') or x.get('comment_count')}))
    return out[:limit]


# ============================================================ 掘金综合

def juejin2(q, limit=10, proxy=None, timeout=15):
    """掘金 · 搜索页接口 (备用; 结果可能与 juejin 不同; search_api/v1/search; id_type=0 时 result_model 为字符串容器,
    需按 result_type 分支解析)"""
    if not (q or '').strip():
        return []
    kw = urllib.parse.quote(q)
    url = (f'https://api.juejin.cn/search_api/v1/search?query={kw}'
           f'&id_type=0&cursor=0&limit={min(limit, 20)}&search_type=0')
    headers = _headers(url, 'api', {'Referer': f'https://juejin.cn/search?query={kw}'})
    txt, st, _ = _fetch(url, proxy, timeout, headers)
    o = json.loads(txt)
    out = []
    for r_ in (o.get('data') or []):
        item = r_.get('result_model') or {}
        if isinstance(item, str):          # 容器型: 再解一层
            try:
                item = json.loads(item)
            except Exception:
                continue
        # 文章型: article_info 在 model 本层
        info = item.get('article_info') or {}
        title = _clean(str(info.get('title') or item.get('title') or ''))
        if not title:
            continue
        out.append(_mk(title, f"https://juejin.cn/post/{info.get('article_id') or ''}",
                       _clean(str(info.get('brief') or item.get('summary') or ''))[:140] or None,
                       extra={'views': info.get('view_count'),
                              'author': (item.get('author_user_info') or {}).get('user_name')}))
    return out[:limit]


# ============================================================ B站视频

def bili2(q, limit=10, proxy=None, timeout=15):
    """B站综合搜索 · 页面接口 (备用, 含专栏/用户; x/web-interface/search/all/v2; 需 buvid cookie)"""
    if not (q or '').strip():
        return []
    kw = urllib.parse.quote(q)
    url = f'https://api.bilibili.com/x/web-interface/search/all/v2?keyword={kw}'
    headers = _headers(url, 'api', {'Referer': f'https://www.bilibili.com/search?keyword={kw}',
                                    'Origin': 'https://www.bilibili.com',
                                    'Sec-Fetch-Site': 'same-site',
                                    'Cookie': 'buvid3=webtool-inject; b_nut=1700000000'})
    txt, st, _ = _fetch(url, proxy, timeout, headers)
    o = json.loads(txt)
    out = []
    for blk in ((o.get('data') or {}).get('result') or []):
        if blk.get('result_type') != 'video':
            continue
        for x in (blk.get('data') or []):
            title = _clean(str(x.get('title') or ''))
            if not title:
                continue
            u = str(x.get('arcurl') or x.get('url') or '')
            if u.startswith('//'):
                u = 'https:' + u
            elif u.startswith('/'):
                u = 'https://www.bilibili.com' + u
            out.append(_mk(title, u,
                           _clean(str(x.get('description') or ''))[:120] or None,
                           extra={'author': x.get('author'), 'play': x.get('play'),
                                  'danmaku': x.get('video_review'), 'duration': x.get('duration')}))
    return out[:limit]


# ============================================================ IT之家搜索

def ithome_so(q, limit=10, proxy=None, timeout=15):
    """IT之家关键词搜索 (www.ithome.com/category/listpage 分页拉新闻流后本地筛)

    IT之家已无公开搜索接口: 站内搜索页 (www.ithome.com/search/<词>.html) 要
    软媒通行证登录, 老搜索域 so.ithome.com 整域 NXDOMAIN, api 域的
    /json/newslist/search 不认 keyword 参数 (恒返回同一批首页旧闻)。
    剩下能用的就是列表页的分页接口 /category/listpage?page=N —— 首页
    "更多" 按钮就是它。按时间倒序翻若干页, 再本地按关键词筛标题。
    """
    if not (q or '').strip():
        return []
    url = 'https://www.ithome.com/category/listpage'
    headers = _headers(url, 'api', {
        'Referer': 'https://www.ithome.com/list/',
        'X-Requested-With': 'XMLHttpRequest',
    })
    kw = q.strip().lower()
    out, seen = [], set()
    # 每页约 50 条, 翻 8 页 ≈ 最近两天多; 命中够数就早停
    for page in range(1, 9):
        try:
            txt, _st, _ = _post(f'{url}?page={page}', proxy, timeout,
                                headers, data='')
        except Exception:
            break
        try:
            o = json.loads(txt)
        except Exception:
            break
        html = ((o.get('content') or {}).get('html') or '')
        if not html:
            break
        got = False
        for m in re.finditer(
                r'<a class="t" href="(https?://www\.ithome\.com/\d+/\d+/\d+\.htm)"[^>]*>([^<]{2,120})</a>'
                r'(?:.*?<i>([^<]*)</i>)?', html, re.S):
            u, title, ts = m.group(1), _clean(m.group(2)), (m.group(3) or '').strip()
            if not title or u in seen:
                continue
            seen.add(u)
            got = True
            if kw and kw not in title.lower():
                continue
            out.append(_mk(title, u, ts or None, extra={'time': ts} if ts else None))
            if len(out) >= limit:
                return out
        if not got:
            break
    return out[:limit]


# ============================================================ 豆瓣

def douban(q, limit=10, proxy=None, timeout=15):
    """豆瓣内容搜索 (www.douban.com/search HTML; /j/search 需登录, HTML 版免登录;
    a.nbg 条目: title 属性 + link2 url= 真实链接)"""
    if not (q or '').strip():
        return []
    kw = urllib.parse.quote(q)
    url = f'https://www.douban.com/search?cat=1001&q={kw}'
    headers = _headers(url, 'nav', {'Referer': 'https://www.douban.com/'})
    txt, st, _ = _fetch(url, proxy, timeout, headers)
    out = []
    for m in re.finditer(
            r'<a class="nbg" href="[^"]*url=([^&"]+)[^"]*"[^>]*title="([^"]+)"',
            txt):
        real = urllib.parse.unquote(m.group(1))
        title = _clean(m.group(2))
        if not title:
            continue
        out.append(_mk(title, real))
        if len(out) >= limit:
            break
    return out[:limit]


def gh_search(q, limit=10, proxy=None, timeout=15):
    """GitHub 仓库 (q 语法透传; 接口比 github 弱, 一般用 github 即可; api.github.com; stars:>1000 language:python)"""
    if not (q or '').strip():
        return []
    url = (f'https://api.github.com/search/repositories?q={urllib.parse.quote(q)}'
           f'&sort=best-match&per_page={min(limit, 30)}')
    from webtool.engines.sites import _headers as _sh
    headers = _sh(url, 'rest', {'Accept': 'application/vnd.github+json'})
    txt, st, _ = _fetch(url, proxy, timeout, headers)
    o = json.loads(txt)
    out = []
    for x in o.get('items') or []:
        name = x.get('full_name') or ''
        if not name:
            continue
        out.append(_mk(name, x.get('html_url') or f'https://github.com/{name}',
                       _clean(str(x.get('description') or ''))[:140] or None,
                       extra={'stars': x.get('stargazers_count'),
                              'lang': x.get('language'),
                              'updated': str(x.get('pushed_at') or '')[:10]}))
    return out[:limit]


# ============================================================ 注册表

