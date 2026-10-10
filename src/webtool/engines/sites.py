# -*- coding: utf-8 -*-
"""站点内搜索 (site search): 知名站点的官方/公开接口, 与传统搜索引擎区分

设计原则:
1. 每个站点一个适配器, 统一输出 {title,url,snippet,score,site} 结构
2. 只收录有稳定公开 JSON/XML 接口的站点; 纯 HTML 爬站的不进
3. 与 search 子命令分开: webtool site <site> <query>
4. 失败信息带 hint, 代理策略继承全局配置
5. 请求头走 transport 统一指纹: 浏览器站点用 XHR 指纹 (sec-fetch-mode: cors
   + accept: application/json + origin/referer 推导), 开放 API 用 API 惯例头,
   避免 header 与人行为不一致触发反爬

UA 策略 (A/B 实测 2026-10-09):
- 裸 UA 打 bilibili 直接 412, 浏览器 UA 全部 200; 开放 API 对浏览器 UA 同样接受
- 全部经 transport: UA/TLS/sec-ch-ua 同源一致, 不手工拼装
"""
import json
import re
import urllib.parse

from .. import transport

# 浏览器站点 (XHR 指纹) 与开放 API (API 惯例头) 共用的 UA 常量 (文档/兼容用)
_UA = transport.PROFILES['chrome131_win']['ua']
_TOOL_UA = _UA


def _headers(site_url, kind='api', extra=None):
    """构造与真人浏览器一致的请求头 (transport.headers_for 的站点适配包装)

    kind: 'api'  = 页面 JS 发起的 XHR/fetch 请求 (cors 模式)
          'nav'  = 直接导航打开 (document 模式)
          'rest' = 开放 REST API (github/arxiv...): 惯例头, 不带浏览器指纹
    site_url: 请求目标 URL, 用于推导 Origin/Referer/sec-fetch-site
    """
    p = urllib.parse.urlparse(site_url)
    origin = f'{p.scheme}://{p.netloc}'
    if kind == 'rest':
        return {'Accept': 'application/json', 'User-Agent': _TOOL_UA,
                **(extra or {})}
    h = transport.headers_for('xhr' if kind == 'api' else 'nav', site_url,
                              referer=origin + '/')
    if kind == 'api':
        h.setdefault('Origin', origin)
    if extra:
        for k, v in extra.items():
            if v is None:
                h.pop(k, None)
            else:
                h[k] = v
    return h


# ---------------------------------------------------------------- 注册表
# site_key -> {desc, fn, proxy_hint: 'direct'|'proxy'|None(auto)}

def _clean_html(s):
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', s or '')).strip()


def _html_unescape(s):
    from html import unescape
    return unescape(s or '')


def _mk(title, url, snippet='', score=None, extra=None):
    r = {'title': _html_unescape(_clean_html(title)), 'url': url,
         'snippet': _html_unescape(_clean_html(snippet))[:300]}
    if score is not None:
        r['score'] = score
    if extra:
        r.update(extra)
    return r


# ---------------------------------------------------------------- adapters

def github(q, limit=10, proxy=None, timeout=15):
    """GitHub 仓库搜索 (api.github.com, 匿名 10 req/min)"""
    url = (f'https://api.github.com/search/repositories?q={urllib.parse.quote(q)}'
           f'&per_page={min(limit, 50)}&sort=best-match')
    txt, st, _ = _fetch(url, proxy, timeout, _headers(url, 'rest', {
        'Accept': 'application/vnd.github+json'}))
    d = json.loads(txt)
    out = []
    for it in d.get('items', []):
        out.append(_mk(f"{it['full_name']} ⭐{it['stargazers_count']}", it['html_url'],
                       it.get('description') or '', score=it['stargazers_count'],
                       extra={'lang': it.get('language'), 'stars': it['stargazers_count'],
                              'updated': (it.get('pushed_at') or '')[:10]}))
    return out


def stackoverflow(q, limit=10, proxy=None, timeout=15):
    """Stack Overflow (api.stackexchange, 免key 300 req/day; gzip 强制)"""
    url = (f'https://api.stackexchange.com/2.3/search/advanced?order=desc&sort=relevance'
           f'&q={urllib.parse.quote(q)}&site=stackoverflow&pagesize={min(limit, 100)}')
    txt, st, _ = _fetch(url, proxy, timeout, _headers(url, 'rest'))
    d = json.loads(txt)
    out = []
    for it in d.get('items', []):
        out.append(_mk(it['title'], it['link'],
                       f"answers:{it.get('answer_count')} score:{it.get('score')}",
                       score=it.get('score'),
                       extra={'answers': it.get('answer_count'),
                              'is_answered': it.get('is_answered'),
                              'tags': it.get('tags', [])[:5]}))
    return out


def hackernews(q, limit=10, proxy=None, timeout=15):
    """Hacker News (Algolia 官方 API, 免key无限制)"""
    url = (f'https://hn.algolia.com/api/v1/search?query={urllib.parse.quote(q)}'
           f'&tags=story&hitsPerPage={min(limit, 50)}')
    txt, st, _ = _fetch(url, proxy, timeout, _headers(url, 'rest'))
    d = json.loads(txt)
    out = []
    for it in d.get('hits', []):
        title = it.get('title') or it.get('story_title') or ''
        url = it.get('url') or f"https://news.ycombinator.com/item?id={it['objectID']}"
        out.append(_mk(title, url,
                       f"{it.get('points', 0)} points, {it.get('num_comments', 0)} comments",
                       score=it.get('points'),
                       extra={'points': it.get('points'),
                              'comments': it.get('num_comments'),
                              'hn_discuss': f"https://news.ycombinator.com/item?id={it['objectID']}",
                              'date': (it.get('created_at') or '')[:10]}))
    return out


def wikipedia(q, limit=10, proxy=None, timeout=15, lang='zh'):
    """维基百科 (官方 API; 国内直连不稳定, 建议走代理)"""
    url = (f'https://{lang}.wikipedia.org/w/api.php?action=query&list=search'
           f'&srsearch={urllib.parse.quote(q)}&srlimit={min(limit, 50)}&format=json')
    txt, st, _ = _fetch(url, proxy, timeout, _headers(url, 'rest'))
    d = json.loads(txt)
    out = []
    for it in d.get('query', {}).get('search', []):
        out.append(_mk(it['title'],
                       f'https://{lang}.wikipedia.org/wiki/{urllib.parse.quote(it["title"])}',
                       it.get('snippet', ''), score=None, extra={'wordcount': it.get('wordcount')}))
    return out


def arxiv(q, limit=10, proxy=None, timeout=15):
    """arXiv 论文 (官方 API, Atom XML)"""
    url = (f'https://export.arxiv.org/api/query?search_query=all:{urllib.parse.quote(q)}'
           f'&max_results={min(limit, 50)}&sortBy=relevance')
    txt, st, _ = _fetch(url, proxy, timeout, _headers(url, 'rest'))
    entries = re.findall(r'<entry>(.*?)</entry>', txt, re.S)
    out = []
    for e in entries:
        t = re.search(r'<title>(.*?)</title>', e, re.S)
        link = re.search(r'<id>(.*?)</id>', e, re.S)
        summ = re.search(r'<summary>(.*?)</summary>', e, re.S)
        pub = re.search(r'<published>(.*?)</published>', e, re.S)
        authors = re.findall(r'<name>(.*?)</name>', e)
        out.append(_mk(t.group(1).strip() if t else '', (link.group(1).strip() if link else ''),
                       (summ.group(1).strip() if summ else '')[:280],
                       extra={'authors': ', '.join(authors[:3]) + (' et al.' if len(authors) > 3 else ''),
                              'date': (pub.group(1)[:10] if pub else '')}))
    return out


def csdn(q, limit=10, proxy=None, timeout=15):
    """CSDN 博客搜索 (站内 API)"""
    url = (f'https://so.csdn.net/api/v3/search?q={urllib.parse.quote(q)}'
           f'&t=blog&p=1&size={min(limit, 50)}')
    txt, st, _ = _fetch(url, proxy, timeout, _headers(url, 'api', {
        # CSDN 前端从 so.csdn.net 页面发起搜索
        'Referer': 'https://so.csdn.net/so/search?q=' + urllib.parse.quote(q),
    }))
    d = json.loads(txt)
    out = []
    for it in d.get('result_vos', []):
        out.append(_mk(it.get('title', ''), it.get('url', ''),
                       it.get('description', ''),
                       extra={'author': it.get('nickname'),
                              'views': it.get('view'),
                              'date': (it.get('created_at') or '')[:10]}))
    return out[:limit]


def juejin(q, limit=10, proxy=None, timeout=15):
    """掘金 (稀土掘金社区文章)"""
    url = (f'https://api.juejin.cn/search_api/v1/search?query={urllib.parse.quote(q)}'
           f'&id_type=0&limit={min(limit, 50)}')
    txt, st, _ = _fetch(url, proxy, timeout, _headers(url, 'api', {
        # 掘金前端从 juejin.cn 搜索页发 XHR
        'Referer': 'https://juejin.cn/search?query=' + urllib.parse.quote(q),
    }))
    d = json.loads(txt)
    out = []
    for item in d.get('data') or []:
        m = item.get('result_model') or {}
        info = m.get('article_info') or {}
        if not info.get('title'):
            continue
        out.append(_mk(info['title'],
                       f"https://juejin.cn/post/{info['article_id']}",
                       _clean_html(m.get('article_content', ''))[:200],
                       score=info.get('view_count'),
                       extra={'author': (m.get('author_user_info') or {}).get('user_name'),
                              'views': info.get('view_count'),
                              'date': _ts2date(info.get('ctime'))}))
    return out[:limit]


def bilibili(q, limit=10, proxy=None, timeout=15):
    """B站视频搜索 (站内 API, 必须带 www.bilibili.com Referer, 否则 412)"""
    url = (f'https://api.bilibili.com/x/web-interface/search/all/v2'
           f'?keyword={urllib.parse.quote(q)}')
    # B站跨域: 页面在 www, API 在 api, 前端 XHR 是 cors 跨站请求
    txt, st, _ = _fetch(url, proxy, timeout, _headers(url, 'api', {
        'Referer': 'https://www.bilibili.com/search?keyword=' + urllib.parse.quote(q),
        'Origin': 'https://www.bilibili.com',
        'Sec-Fetch-Site': 'same-site',
        'Cookie': 'buvid3=injected; b_nut=1719999999',  # 简单匿名指纹, 降低风控
    }))
    d = json.loads(txt)
    if d.get('code') == -412:
        raise RuntimeError('bilibili 风控(412), 建议降低频率或走代理')
    out = []
    for blk in (d.get('data', {}) or {}).get('result', []):
        if blk.get('result_type') != 'video':
            continue
        for v in blk.get('data', [])[:limit]:
            out.append(_mk(v.get('title', ''),
                           f"https://www.bilibili.com/video/{v.get('bvid')}",
                           v.get('description', ''),
                           score=v.get('play'),
                           extra={'author': v.get('author'),
                                  'plays': v.get('play'),
                                  'danmaku': v.get('video_review'),
                                  'duration': v.get('duration')}))
        break
    return out[:limit]


def sspai(q, limit=10, proxy=None, timeout=15):
    """少数派文章"""
    url = (f'https://sspai.com/api/v1/search/article/page/get'
           f'?title={urllib.parse.quote(q)}&limit={min(limit, 50)}')
    txt, st, _ = _fetch(url, proxy, timeout, _headers(url, 'api', {
        'Referer': 'https://sspai.com/search/article?q=' + urllib.parse.quote(q),
    }))
    d = json.loads(txt)
    out = []
    for a in (d.get('data') or [])[:limit]:
        out.append(_mk(a.get('title', ''),
                       f"https://sspai.com/post/{a.get('id')}",
                       a.get('summary', ''),
                       extra={'author': a.get('author', {}).get('nickname') if isinstance(a.get('author'), dict) else None,
                              'views': a.get('view_count')}))
    return out


def npm(q, limit=10, proxy=None, timeout=15):
    """npm 包搜索"""
    url = (f'https://registry.npmjs.org/-/v1/search?text={urllib.parse.quote(q)}'
           f'&size={min(limit, 50)}')
    txt, st, _ = _fetch(url, proxy, timeout, _headers(url, 'rest'))
    d = json.loads(txt)
    out = []
    for o in d.get('objects', []):
        p = o.get('package', {})
        out.append(_mk(p.get('name', ''), p.get('links', {}).get('npm', ''),
                       p.get('description', ''),
                       score=o.get('score', {}).get('final'),
                       extra={'version': p.get('version'),
                              'publisher': (p.get('publisher') or {}).get('username'),
                              'date': (p.get('date') or '')[:10]}))
    return out


def _fetch(url, proxy, timeout, headers):
    """站点请求统一走 transport (浏览器指纹), engine=None 不做验证码处置"""
    text, status, _via = transport.get(url, kind='plain', proxy=proxy,
                                       timeout=timeout, headers=headers,
                                       engine=None)
    return text, status, _via


def _ts2date(ts):
    try:
        import datetime
        return datetime.datetime.fromtimestamp(int(ts)).strftime('%Y-%m-%d')
    except Exception:
        return None


SITES = {
    'github':       {'fn': github, 'desc': 'GitHub 仓库', 'proxy': 'direct'},
    'so':           {'fn': stackoverflow, 'desc': 'Stack Overflow', 'proxy': 'direct'},
    'hn':           {'fn': hackernews, 'desc': 'Hacker News (Algolia API)', 'proxy': 'direct'},
    'wikipedia':    {'fn': wikipedia, 'desc': '维基百科 (lang 参数可换 en/zh)', 'proxy': 'proxy'},
    'arxiv':        {'fn': arxiv, 'desc': 'arXiv 论文', 'proxy': 'direct'},
    'csdn':         {'fn': csdn, 'desc': 'CSDN 博客', 'proxy': 'direct'},
    'juejin':       {'fn': juejin, 'desc': '掘金', 'proxy': 'direct'},
    'bilibili':     {'fn': bilibili, 'desc': 'B站视频', 'proxy': 'direct'},
    'sspai':        {'fn': sspai, 'desc': '少数派', 'proxy': 'direct'},
    'npm':          {'fn': npm, 'desc': 'npm 包', 'proxy': 'direct'},
}
