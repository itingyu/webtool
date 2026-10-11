"""webtool site 第二批: 真·关键词搜索型适配器 (对齐用户要求: 站点搜索不单热榜)

全部走 transport/_fetch 反探测指纹通道 (XHR 头同源构造 + 真 TLS 指纹):
- csdn_so    CSDN 问答搜索 (so.csdn.net API, 免登录)
- juejin2    掘金综合搜索 (recommend 接口, 涵盖文章/沸点/课程)
- bili2      B站视频搜索 (web-interface/search/all/v2, 需简单 buvid cookie)
- ithome_so  IT之家关键词搜索 (api.ithome.com/json/search)
- douban     豆瓣内容搜索 (www.douban.com/j/search, 免登录)
- sohu_so    搜狐资讯搜索 (search.sohu.com API)
- wallhaven  壁纸搜索 (C 指纹可达; q 支持颜色/分类语法透传)
- gh_search  GitHub 代码/仓库关键词搜索 (api.github.com, 与 trend 区分)
- wp_media   Wikipedia 多语言搜索增强 (走 zh/en 自动重试)
"""

import json
import re
import urllib.parse

import sys as _sys

_sites = _sys.modules.get('webtool.engines.sites')
if _sites is None:
    from . import sites as _sites
from .sites import _headers, _mk, _fetch


def _clean(s):
    s = re.sub(r'</?em[^>]*>', '', s or '')
    s = re.sub(r'<[^>]+>', '', s)
    return re.sub(r'\s+', ' ', s).strip()


# ============================================================ CSDN 问答

def csdn_so(q, limit=10, proxy=None, timeout=15):
    """CSDN 问答搜索 (so.csdn.net/api/v3/search, t=ask)"""
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
    """掘金文章搜索 (search_api/v1/search; id_type=0 时 result_model 为字符串容器,
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
    """B站综合搜索 (x/web-interface/search/all/v2; 需 buvid cookie)"""
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
    """IT之家关键词搜索 (so.ithome.com 搜索页 HTML; api 域搜索接口已 404)"""
    if not (q or '').strip():
        return []
    kw = urllib.parse.quote(q)
    url = f'https://so.ithome.com/html/search.html?word={kw}'
    headers = _headers(url, 'nav', {'Referer': 'https://www.ithome.com/'})
    txt, st, _ = _fetch(url, proxy, timeout, headers)
    out = []
    for m in re.finditer(
            r'<a[^>]+href="(?:https?:)?//(www\.ithome\.com/0/\d+/\d+\.htm)"[^>]*>([^<]{6,120})</a>',
            txt):
        u, title = m.group(1), _clean(m.group(2))
        if not title or any(u == x['url'] for x in out):
            continue
        out.append(_mk(title, f'https://{u}'))
        if len(out) >= limit:
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


# sohu_so 已移除: search.sohu.com/meta 返回空数据 (status:-1), odin blockdata 502,
# 无可用公开搜索接口.

# ============================================================ GitHub 仓库搜索


# ============================================================ GitHub 仓库搜索

def gh_search(q, limit=10, proxy=None, timeout=15):
    """GitHub 仓库关键词搜索 (api.github.com; q 语法透传 stars:>1000 language:python)"""
    if not (q or '').strip():
        return []
    url = (f'https://api.github.com/search/repositories?q={urllib.parse.quote(q)}'
           f'&sort=best-match&per_page={min(limit, 30)}')
    from .sites import _headers as _sh
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

# ithome_so 已移除 (api 404 / so 域 DNS 不可达); 热榜通道 moresites.ithome 仍可用.

NEW2_SITES = {
    'csdn_so':    {'fn': csdn_so,    'desc': 'CSDN 问答搜索', 'proxy': 'direct'},
    'juejin2':    {'fn': juejin2,    'desc': '掘金文章搜索', 'proxy': 'direct'},
    'bili2':      {'fn': bili2,      'desc': 'B站视频综合搜索', 'proxy': 'direct'},
    'douban':     {'fn': douban,     'desc': '豆瓣内容搜索 (图书/影剧等)', 'proxy': 'direct'},
    'gh_search':  {'fn': gh_search,  'desc': 'GitHub 仓库搜索 (q 语法透传)', 'proxy': 'direct'},
}
