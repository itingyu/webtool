"""站点内搜索 (site search): 知名站点的官方/公开接口, 与传统搜索引擎区分

设计原则:
1. 每个站点一个适配器, 统一输出 {title,url,snippet,score,site} 结构
2. 优先收录有稳定公开 JSON/XML 接口的站点; 服务端渲染的 HTML 站可以收,
   但解析规则必须有离线 fixture 测试兜底 (改版时测试先红, 不静默失效)
3. 与 search 子命令分开: webtool site <site> <query>
4. 失败信息带 hint, 代理策略继承全局配置
5. 请求头走 transport 统一指纹: 浏览器站点用 XHR 指纹, 开放 API 用 API
   惯例头, 避免 header 与行为不一致触发反爬

UA 策略:
- 全部出网走 transport 指纹档案 (curl_cffi impersonate + 同源 UA), 轮换池
  chrome131 win/mac/linux + safari18_4_ios, 同引擎同进程固定档案;
- 开放 REST API (github/so/hn...) 同样用浏览器 UA —— Python 默认 UA 是
  一级机器人特征; Accept-Language 按站点语言 (EN 站 API 用 en-US)
"""
import json
import re
import urllib.parse

from webtool.net import transport
from webtool.core import text

# 浏览器 UA 常量 (文档/兼容用; 实际 header 全部经 transport._headers 动态构造)
_UA = transport.PROFILES['chrome131_win']['ua']
_TOOL_UA = _UA


def _headers(site_url, kind='api', extra=None):
    """按站点形态构造请求头 (全部经 transport 指纹档案, 与 TLS 同源)

    kind: 'api'  = 页面 JS 发起的 XHR/fetch 请求 (cors 模式)
          'nav'  = 直接导航打开 (document 模式)
          'rest' = 开放 REST API (github/arxiv...): 浏览器 UA + JSON Accept,
                   不带 sec-fetch 浏览器专属头
    site_url: 请求目标 URL, 用于推导 Origin/Referer/sec-fetch-site
    """
    # urllib 兜底与 cffi 不同: 无 impersonate, UA 必须显式给 — 用档案 UA
    # (与全局轮换同源), rest 通道同理; cffi 通道 UA 一律交给 impersonate
    h = {}
    p = urllib.parse.urlparse(site_url)
    origin = f'{p.scheme}://{p.netloc}'
    if kind == 'rest':
        h = {'Accept': 'application/json',
             'User-Agent': transport.PROFILES[transport._pick_profile(None)]['ua'],
             'Accept-Language': transport.LANG_EN,
             **(extra or {})}
        return h
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


# 结果条目工厂: 所有站点源统一出口, 标题/摘要在这里清洗定长, 下游不用再兜
def _mk(title, url, snippet='', score=None, extra=None):
    """构造标准结果条目 {title,url,snippet,score?,...extra}"""
    r = {'title': text.plain(title), 'url': url,
         'snippet': text.plain(snippet)[:300]}
    if score is not None:
        r['score'] = score
    if extra:
        r.update(extra)
    return r


# adapters

def github(q, limit=10, proxy=None, timeout=15):
    """GitHub 仓库 (api.github.com, 匿名 10 req/min; 一般用这个)"""
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
    """掘金 · 官方 search_api (优先)"""
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
                       text.plain(m.get('article_content', ''))[:200],
                       score=info.get('view_count'),
                       extra={'author': (m.get('author_user_info') or {}).get('user_name'),
                              'views': info.get('view_count'),
                              'date': _ts2date(info.get('ctime'))}))
    return out[:limit]


def bilibili(q, limit=10, proxy=None, timeout=15):
    """B站视频 · 站内 API (优先; 需 bilibili Referer)"""
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
        author = a.get('author', {})
        out.append(_mk(a.get('title', ''),
                       f"https://sspai.com/post/{a.get('id')}",
                       a.get('summary', ''),
                       extra={'author': author.get('nickname')
                              if isinstance(author, dict) else None,
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


_SF_ITEM = re.compile(
    r'<li class="py-3 list-group-item list-group-item-action">\s*'
    r'<a href="(/(?:a|q)/\d+)"[^>]*>\s*<h5[^>]*>(.*?)</h5>\s*</a>'
    r'(.*?)</li>', re.S)
_SF_BODY = re.compile(r'class="text-secondary[^"]*"[^>]*>(.*?)</div>', re.S)
_SF_CMT = re.compile(r'<!--.*?-->', re.S)


def _parse_segmentfault(html, limit=10):
    """从搜索页抽条目 (纯函数: 用离线 fixture 测, 不联网)

    页面混排文章 (/a/ID) 与问答 (/q/ID), 两者都收; 标题里夹着 React 的
    注释节点 (<!-- -->), 先剥掉再进 text.plain, 否则会留下空 comment。
    """
    out = []
    for href, title, rest in _SF_ITEM.findall(html or ''):
        m = _SF_BODY.search(rest)
        out.append(_mk(_SF_CMT.sub('', title),
                       'https://segmentfault.com' + href,
                       m.group(1) if m else ''))
        if len(out) >= limit:
            break
    return out


def segmentfault(q, limit=10, proxy=None, timeout=15):
    """SegmentFault 技术问答/文章

    没有公开 JSON 接口 (gateway 要页面 token, 直接调返回"非法请求"),
    只能取服务端渲染的搜索页 —— 解析规则有离线 fixture 兜底, 改版会先
    在 tests/test_sites_html.py 里挂掉。
    """
    url = f'https://segmentfault.com/search?q={urllib.parse.quote(q)}'
    txt, _st, _via = _fetch(url, proxy, timeout, _headers(url, 'nav'))
    return _parse_segmentfault(txt, limit)


def _fetch(url, proxy, timeout, headers, profile=None, engine=None):
    """站点请求统一走 transport (浏览器指纹), engine=None 不做验证码处置

    profile: 传输指纹档案名; None 时由 transport 按引擎轮换 (同引擎同进程
    固定)。engine 非 None 时启用反爬全套: 验证码检测/冷却/cookie 持久化/
    节奏控制。
    """
    p = transport.PROFILES.get(profile) if isinstance(profile, str) else profile
    text, status, _via = transport.get(url, kind='plain', proxy=proxy,
                                       timeout=timeout, headers=headers,
                                       engine=engine, profile=p)
    if status != 200:
        raise RuntimeError(f'HTTP {status} (via {_via})')
    return text, status, _via


def _post(url, proxy, timeout, headers, data=None, profile=None, engine=None):
    """POST 版 _fetch: 走 transport.request (指纹同源), 非幂等故不自动重试

    data: 字符串或 dict (dict 走 form 编码)。传空 body 时仍要带
    Content-Length —— 有些站点 (IT之家 /category/listpage) 对无长度 POST
    直接回 411 Length Required。
    """
    p = transport.PROFILES.get(profile) if isinstance(profile, str) else profile
    h = dict(headers or {})
    body = '' if data is None else data
    if isinstance(body, dict):
        body = urllib.parse.urlencode(body)
    h.setdefault('Content-Type', 'application/x-www-form-urlencoded')
    h.setdefault('Content-Length', str(len(body.encode('utf-8'))))
    r = transport.request('POST', url, kind='plain', proxy=proxy,
                          timeout=timeout, headers=h, data=body,
                          engine=engine, profile=p)
    if r.status_code != 200:
        raise RuntimeError(f'HTTP {r.status_code} (via {r.via})')
    return r.text, r.status_code, r.via


# 注册表
# site_key -> {desc, module, params}  (清单在 data/plugins.json 的 "site" 段)
# 不再有 proxy 字段: 站点不出网, 只暴露 (q, limit, proxy, timeout) 适配器,
# 走哪条线由调用方 (routes → 路由表) 传进来


def _ts2date(ts):
    try:
        import datetime
        return datetime.datetime.fromtimestamp(int(ts)).strftime('%Y-%m-%d')
    except Exception:
        return None


# 注册表
# site_key -> {desc, module, params}; 清单在 data/plugins.json 的 "site" 段,
# 加站点 = 写一个 (q, limit, proxy, timeout) -> [结果] 的适配器 + plugins.json 加一条
from webtool.core.plugins import table as _plugin_table


def sites_table():
    """站点表; 每次现取插件表, 清单改动即时生效"""
    return _plugin_table('site')
