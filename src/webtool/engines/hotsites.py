# -*- coding: utf-8 -*-
"""webtool rank 榜单源适配器: 热榜/趋势类

search: False 的源不支持关键词, rank 拉全榜后本地 BM25 筛选;
search: True 的源 query 直接透传。全部走 transport 指纹通道。
"""
import json
import re
import urllib.parse

from .sites import _headers, _mk, _fetch


def _clean(s):
    """去 HTML 标签/高亮 em 标记"""
    s = re.sub(r'</?em[^>]*>', '', s or '')
    s = re.sub(r'<[^>]+>', '', s)
    return re.sub(r'\s+', ' ', s).strip()


def _local_filter(items, q, limit):
    """q 非空时本地包含过滤 (全空命中则回退全榜), 再截 limit"""
    kw = (q or '').strip().lower()
    if kw:
        hits = [x for x in items
                if kw in str(x.get('title', '')).lower()
                or kw in str(x.get('snippet') or '').lower()]
        if hits:
            return hits[:limit]
    return items[:limit]


# ============================================================ 知乎热榜

def zhihu_hot(q, limit=10, proxy=None, timeout=15):
    """知乎热榜 (api.zhihu.com 热榜接口, XHR 指纹; 不支持关键词搜索)"""
    url = f'https://api.zhihu.com/topstory/hot-list?limit={min(max(limit, 10), 50)}'
    headers = _headers(url, 'api', {
        'Referer': 'https://www.zhihu.com/hot',
        'Origin': 'https://www.zhihu.com',
    })
    txt, st, _ = _fetch(url, proxy, timeout, headers)
    d = json.loads(txt)
    out = []
    for item in d.get('data') or []:
        tg = item.get('target') or {}
        area = tg.get('title_area')
        title = (area.get('text') if isinstance(area, dict) else None) \
            or tg.get('title') or item.get('detail_text') or ''
        if not title:
            continue
        u = tg.get('url') or ''
        if u.startswith('//'):
            u = 'https:' + u
        out.append(_mk(title, u, tg.get('excerpt') or '',
                       extra={'answers': tg.get('answer_count'),
                              'comments': tg.get('comment_count'),
                              'hot_value': item.get('detail_text')}))
    return _local_filter(out, q, limit)


# ============================================================ 今日头条

def toutiao(q, limit=10, proxy=None, timeout=15):
    """今日头条 feed (m.toutiao.com SSR 页, 移动指纹; 榜单接口不支持关键词)"""
    from .. import spa
    url = 'https://m.toutiao.com/feed'
    # 头条按 UA/TLS 指纹分流: 桌面档案回 4.8KB 壳页, 真·移动 TLS 指纹才给 SSR 数据
    headers = _headers(url, 'nav', {'Sec-Fetch-Site': 'none'})
    txt, st, _ = _fetch(url, proxy, timeout, headers,
                        profile='chrome131_android')
    if txt.count('RENDER_DATA') == 0 or len(txt) < 6000:
        txt, st, _ = _fetch(url, proxy, timeout, headers,
                            profile='safari18_4_ios')
    o = spa.first_state(txt)
    items = []
    if o:
        for it in (o.get('initialFeedList') or {}).get('data') or []:
            base = (((it.get('assembleCell') or {}).get('itemCell')) or {}).get('articleBase') or {}
            if not base.get('title'):
                continue
            items.append(_mk(base['title'], base.get('displayURL') or base.get('articleURL') or '',
                             base.get('abstractText') or '',
                             extra={'gid': base.get('gidStr')}))
    return _local_filter(items, q, limit)


# ============================================================ 微博热搜

def weibo(q, limit=10, proxy=None, timeout=15):
    """微博热搜 (weibo.com ajax 免登录; 榜单接口不支持关键词)"""
    url = 'https://weibo.com/ajax/side/hotSearch'
    headers = _headers(url, 'api', {'Referer': 'https://s.weibo.com/top/summary',
                                    'Origin': 'https://weibo.com'})
    txt, st, _ = _fetch(url, proxy, timeout, headers)
    d = (json.loads(txt).get('data') or {})
    out = []
    for x in d.get('realtime') or []:
        word = x.get('word') or ''
        if not word:
            continue
        qn = urllib.parse.quote(word)
        out.append(_mk(word, f'https://s.weibo.com/weibo?q=%23{qn}%23',
                       x.get('note') or '', extra={'hot': x.get('num'),
                                                   'label': x.get('label_name') or None}))
    return _local_filter(out, q, limit)


# ============================================================ 百度热搜

def baidu(q, limit=10, proxy=None, timeout=15):
    """百度热搜 (top.baidu.com 免登录; 双层 content 结构)"""
    url = 'https://top.baidu.com/api/board?platform=wise&tab=realtime'
    headers = _headers(url, 'api', {'Referer': 'https://top.baidu.com/board',
                                    'Origin': 'https://top.baidu.com'})
    txt, st, _ = _fetch(url, proxy, timeout, headers)
    cards = (json.loads(txt).get('data') or {}).get('cards') or []
    out = []
    for c in cards:
        for inner in (c.get('content') or []):
            for x in (inner.get('content') or []):
                word = x.get('word') or ''
                if not word:
                    continue
                qn = urllib.parse.quote(word)
                out.append(_mk(word, x.get('url') or f'https://www.baidu.com/s?wd={qn}',
                               _clean(str(x.get('desc') or '')) or '',
                               extra={'hot': x.get('hotScore') or x.get('score')}))
    return _local_filter(out, q, limit)


# ============================================================ IT之家

def ithome(q, limit=10, proxy=None, timeout=15):
    """IT之家资讯榜 (api.ithome.com 热榜; 榜单接口不支持关键词)"""
    url = 'https://api.ithome.com/json/newslist/news?r=0'
    headers = _headers(url, 'api', {'Referer': 'https://www.ithome.com/'})
    txt, st, _ = _fetch(url, proxy, timeout, headers)
    o = json.loads(txt)
    out = []
    for x in o.get('newslist') or []:
        title = _clean(str(x.get('title') or ''))
        if not title:
            continue
        nid = x.get('newsid') or ''
        u = x.get('url') or (f'https://www.ithome.com/0/{nid}/{nid}.htm' if nid else '')
        out.append(_mk(title, u, _clean(str(x.get('description') or ''))[:120],
                       extra={'comments': x.get('commentcount')}))
    return _local_filter(out, q, limit)


# ============================================================ Reddit

def reddit(q, limit=10, proxy=None, timeout=15):
    """Reddit (r/<sub> 或全站热帖; 支持子版块+关键词过滤)

    通道: old.reddit.com .json (需代理)。2026-10 探测: reddit 对数据中心
    IP 全面收紧 — old.reddit .json 302 登录页 / www 403 / .rss 429 (全指纹),
    RSS 兜底保留 ( residential 出口或未来放宽时可自动恢复)。
    本环境不可达时 rank 将其记入 failed, 不阻塞其他源。
    """
    sub = (q or '').strip().lstrip('r/').lstrip('/') or 'popular'
    kw = ''
    if ' ' in sub:                       # "python" vs "r/xxx 关键词" 形态
        sub, kw = sub.split(' ', 1)
    out = []
    try:
        url = f'https://old.reddit.com/r/{sub}/hot.json?limit={min(max(limit, 10), 50)}&raw_json=1'
        headers = _headers(url, 'rest', {'Accept': 'application/json',
                                         'Referer': 'https://www.reddit.com/'})
        txt, st, _ = _fetch(url, proxy, timeout, headers)
        d = json.loads(txt)
        for c in ((d.get('data') or {}).get('children') or []):
            x = c.get('data') or {}
            title = x.get('title') or ''
            if not title:
                continue
            out.append(_mk(title, 'https://www.reddit.com' + (x.get('permalink') or ''),
                           (x.get('selftext') or '')[:140],
                           extra={'sub': x.get('subreddit'), 'score': x.get('score'),
                                  'comments': x.get('num_comments')}))
    except Exception:
        out = []                          # JSON 通道挂了 → RSS 兜底
    if not out:
        out = _reddit_rss(sub, limit, proxy, timeout)
    if kw:
        out = [x for x in out if kw.lower() in x['title'].lower()] or out
    return out[:limit]


def _reddit_rss(sub, limit, proxy, timeout):
    """www/old.reddit .rss Atom 兜底 (JSON 通道被重定向/403 时)"""
    last_err = None
    for base in (f'https://www.reddit.com/r/{sub}/.rss',
                 f'https://old.reddit.com/r/{sub}/.rss'):
        try:
            headers = _headers(base, 'nav', {
                'Accept': 'application/atom+xml, application/xml, text/xml, */*'})
            txt, st, _ = _fetch(base, proxy, timeout, headers)
            out = []
            for e in re.findall(r'<entry>(.*?)</entry>', txt or '', re.S):
                t = re.search(r'<media:title>(.*?)</media:title>', e, re.S) \
                    or re.search(r'<title>(.*?)</title>', e, re.S)
                if not t:
                    continue
                l = re.search(r'href="(https://www\.reddit\.com/r/[^"]+)"', e)
                title = _clean(t.group(1))
                if not title:
                    continue
                out.append(_mk(title, l.group(1) if l else '', '',
                               extra={'sub': sub}))
                if len(out) >= limit:
                    return out
            if out:
                return out
        except Exception as e:
            last_err = e
    if last_err:
        raise RuntimeError(f'reddit .json + .rss 均失败: {str(last_err)[:120]}')
    return []


# ============================================================ HN 官方热榜

def hn_official(q, limit=10, proxy=None, timeout=15):
    """Hacker News 官方 Firebase API (top stories, 逐条补元数据)"""
    url = 'https://hacker-news.firebaseio.com/v0/topstories.json'
    txt, st, _ = _fetch(url, proxy, timeout,
                        headers=_headers(url, 'rest', {'Accept': 'application/json'}))
    ids = (json.loads(txt) or [])[:min(max(limit, 5), 30)]
    out = []
    for i in ids:
        try:
            iu = f'https://hacker-news.firebaseio.com/v0/item/{i}.json'
            t2, _, _ = _fetch(iu, proxy, timeout,
                              headers=_headers(iu, 'rest', {'Accept': 'application/json'}))
            x = json.loads(t2) or {}
        except Exception:
            continue
        title = x.get('title') or ''
        if not title:
            continue
        u = x.get('url') or f'https://news.ycombinator.com/item?id={i}'
        out.append(_mk(title, u, '',
                       extra={'score': x.get('score'),
                              'comments': x.get('descendants'),
                              'hn': f'https://news.ycombinator.com/item?id={i}'}))
    return _local_filter(out, q, limit)


# ============================================================ Lobsters

def lobsters(q, limit=10, proxy=None, timeout=15):
    """Lobsters 热帖 JSON (HN 风格社区, 免登录)"""
    url = 'https://lobste.rs/hottest.json'
    txt, st, _ = _fetch(url, proxy, timeout,
                        headers=_headers(url, 'rest', {'Accept': 'application/json'}))
    out = []
    for x in json.loads(txt) or []:
        title = x.get('title') or ''
        if not title:
            continue
        out.append(_mk(title, x.get('short_id_url') or x.get('comments_url') or '',
                       (x.get('description') or '')[:140],
                       extra={'tags': x.get('tags'), 'score': x.get('score'),
                              'comments': x.get('comment_count')}))
    kw = (q or '').strip().lower()
    if kw:
        out = [x for x in out if kw in x['title'].lower()
               or kw in ' '.join(str(x.get('tags') or [])).lower()] or out
    return out[:limit]


# ============================================================ GitHub Trending

def github_trend(q, limit=10, proxy=None, timeout=15):
    """GitHub Trending (GH Search API: 近7日创建按 star 排序; 短词作语言过滤,
    支持关键词透传)"""
    import datetime
    since = (datetime.date.today() - datetime.timedelta(days=7)).isoformat()
    kw = (q or '').strip()
    qstr = f'created:>{since}'
    if kw:
        qstr = f'{qstr} {kw}' if kw.isalpha() and len(kw) < 20 and ' ' not in kw \
            else qstr          # 短词当语言过滤; 长句不拼 (避免语法错)
    url = (f'https://api.github.com/search/repositories?q={urllib.parse.quote(qstr)}'
           f'&sort=stars&order=desc&per_page={min(max(limit, 5), 30)}')
    headers = _headers(url, 'rest', {'Accept': 'application/vnd.github+json'})
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
                              'lang': x.get('language')}))
    return out[:limit]


# ============================================================ 贴吧热议

def tieba(q, limit=10, proxy=None, timeout=15):
    """百度贴吧热议榜 (hottopic/browse/topicList, 30 话题; 不支持关键词)"""
    url = 'https://tieba.baidu.com/hottopic/browse/topicList'
    headers = _headers(url, 'api', {'Referer': 'https://tieba.baidu.com/hottopic/'})
    txt, st, _ = _fetch(url, proxy, timeout, headers)
    bl = ((json.loads(txt).get('data') or {}).get('bang_topic') or {}).get('topic_list') or []
    out = []
    for x in bl:
        topic = x.get('topic_name') or ''
        if not topic:
            continue
        tid = x.get('topic_id')
        out.append(_mk(topic, x.get('topic_url')
                       or (f'https://tieba.baidu.com/hottopic/browse/topic?topic_id={tid}' if tid else ''),
                       _clean(str(x.get('topic_desc') or x.get('abstract') or ''))[:140],
                       extra={'hot': x.get('discuss_num') or x.get('read_num'),
                              'read': x.get('read_num'),
                              'discuss': x.get('discuss_num')}))
    return _local_filter(out, q, limit)


# ============================================================ 新浪新闻热榜

def sina_hot(q, limit=10, proxy=None, timeout=15):
    """新浪新闻热榜 (GetTopDataList, JSONP 变量形态; 不支持关键词)"""
    url = ('https://top.news.sina.com.cn/ws/GetTopDataList.php?top_type=day'
           '&top_cat=www_www_all_suda_suda&top_time=today&top_show_num=50')
    headers = _headers(url, 'api', {'Referer': 'https://news.sina.com.cn/'})
    txt, st, _ = _fetch(url, proxy, timeout, headers)
    i = txt.find('=')
    if i < 0:
        raise RuntimeError('sina hotlist: JSONP 解析失败')
    payload = txt[i + 1:].strip().rstrip(';')
    rows = (json.loads(payload).get('data') or [])
    out = []
    for x in rows:
        title = _clean(str(x.get('title') or ''))
        if not title:
            continue
        out.append(_mk(title, x.get('url') or x.get('top_url') or '',
                       None, extra={'media': x.get('media') or None,
                                    'date': x.get('create_date') or None}))
    return _local_filter(out, q, limit)


# ============================================================ 豆瓣热门电影

def douban_movie(q, limit=10, proxy=None, timeout=15):
    """豆瓣热门电影 (j/search_subjects, 评分+链接; q 本地过滤标题)"""
    url = ('https://movie.douban.com/j/search_subjects?type=movie&tag=热门'
           '&sort=recommend&page_limit=50&page_start=0')
    headers = _headers(url, 'api', {'Referer': 'https://movie.douban.com/',
                                    'X-Requested-With': 'XMLHttpRequest'})
    txt, st, _ = _fetch(url, proxy, timeout, headers)
    s = (json.loads(txt).get('subjects') or [])
    out = []
    for x in s:
        title = x.get('title') or ''
        if not title:
            continue
        out.append(_mk(title, x.get('url') or '',
                       None, extra={'rate': x.get('rate') or None,
                                    'cover': x.get('cover') or None}))
    return _local_filter(out, q, limit)


# ============================================================ 网易云音乐新歌榜

def netease_music(q, limit=10, proxy=None, timeout=15):
    """网易云音乐新歌榜 (playlist/detail id=3779629, 100 首; q 本地过滤歌名/歌手)"""
    url = 'https://music.163.com/api/playlist/detail?id=3779629'
    headers = _headers(url, 'api', {'Referer': 'https://music.163.com/'})
    txt, st, _ = _fetch(url, proxy, timeout, headers)
    pl = (json.loads(txt).get('result') or {})
    out = []
    for x in pl.get('tracks') or []:
        name = x.get('name') or ''
        artist = ', '.join(a.get('name') or '' for a in x.get('artists') or [])
        title = f'{name} - {artist}' if artist else name
        if not name:
            continue
        out.append(_mk(title, f'https://music.163.com/song?id={x.get("id")}',
                       None, extra={'artist': artist, 'pop': x.get('popularity'),
                                    'album': (x.get('album') or {}).get('name') or None}))
    return _local_filter(out, q, limit)


# ============================================================ IT之家日榜(top)

def douyin(q, limit=10, proxy=None, timeout=15):
    """抖音热搜词榜 (iesdouyin H5 API 免登录; 50 词; 榜单接口不支持关键词)"""
    url = 'https://www.iesdouyin.com/web/api/v2/hotsearch/billboard/word/'
    headers = _headers(url, 'api', {'Referer': 'https://www.iesdouyin.com/'})
    txt, st, _ = _fetch(url, proxy, timeout, headers)
    d = json.loads(txt)
    out = []
    for x in d.get('word_list') or []:
        word = x.get('word') or ''
        if not word:
            continue
        qn = urllib.parse.quote(word)
        out.append(_mk(word, f'https://www.douyin.com/search/{qn}',
                       None, extra={'hot': x.get('hot_value'),
                                    'label': x.get('label')}))
    return _local_filter(out, q, limit)


# ============================================================ 抖音热点榜(事件榜)

def douyin_hot(q, limit=10, proxy=None, timeout=15):
    """抖音热点榜 (douyin.com aweme hot/search/list; 事件聚合+视频数; 不支持关键词)"""
    url = 'https://www.douyin.com/aweme/v1/hot/search/list/'
    headers = _headers(url, 'api', {'Referer': 'https://www.douyin.com/',
                                    'Origin': 'https://www.douyin.com'})
    txt, st, _ = _fetch(url, proxy, timeout, headers)
    data = (json.loads(txt).get('data') or {})
    out = []
    for x in data.get('word_list') or []:
        word = x.get('word') or ''
        if not word:
            continue
        qn = urllib.parse.quote(word)
        n_video = x.get('video_count')
        out.append(_mk(word, f'https://www.douyin.com/search/{qn}',
                       None, extra={'hot': x.get('hot_value'),
                                    'videos': n_video,
                                    'label': x.get('label')}))
    return _local_filter(out, q, limit)


# ============================================================ 头条热榜

def toutiao_hot(q, limit=10, proxy=None, timeout=15):
    """今日头条热榜 (hot-event/hot-board 官方 JSON, 50 条; 不支持关键词)"""
    url = 'https://www.toutiao.com/hot-event/hot-board/?origin=toutiao_pc'
    headers = _headers(url, 'api', {'Referer': 'https://www.toutiao.com/'})
    txt, st, _ = _fetch(url, proxy, timeout, headers)
    d = json.loads(txt)
    out = []
    for x in d.get('data') or []:
        title = _clean(str(x.get('Title') or ''))
        if not title:
            continue
        u = x.get('Url') or ''
        if u.startswith('//'):
            u = 'https:' + u
        out.append(_mk(title, u, '',
                       extra={'hot': x.get('HotValue'),
                              'label': x.get('LabelDesc') or x.get('Label')}))
    return _local_filter(out, q, limit)


# ============================================================ B站热门视频

def bili_hot(q, limit=10, proxy=None, timeout=15):
    """B站热门视频榜 (web-interface/popular 免登录; q 本地过滤标题/简介)"""
    url = f'https://api.bilibili.com/x/web-interface/popular?ps={min(max(limit, 10), 50)}'
    headers = _headers(url, 'api', {'Referer': 'https://www.bilibili.com/',
                                    'Origin': 'https://www.bilibili.com'})
    txt, st, _ = _fetch(url, proxy, timeout, headers)
    d = json.loads(txt)
    if d.get('code') != 0:
        raise RuntimeError(f'bilibili api: {d.get("code")} {d.get("message")}')
    out = []
    for x in (d.get('data') or {}).get('list') or []:
        title = _clean(str(x.get('title') or ''))
        if not title:
            continue
        u = x.get('short_link_v2') or x.get('short_link') \
            or (f"https://www.bilibili.com/video/av{x.get('aid')}" if x.get('aid') else '')
        owner = (x.get('owner') or {}).get('name') or ''
        out.append(_mk(title, u, _clean(str(x.get('desc') or ''))[:140],
                       extra={'up': owner,
                              'play': x.get('stat', {}).get('view') if x.get('stat') else None,
                              'tname': x.get('tname')}))
    return _local_filter(out, q, limit)


# ============================================================ B站排行榜(全站周榜)

def bili_rank(q, limit=10, proxy=None, timeout=15):
    """B站全站排行榜 (ranking/v2; 综合质量周榜 100 条; q 本地过滤)"""
    url = 'https://api.bilibili.com/x/web-interface/ranking/v2?rid=0&type=all'
    headers = _headers(url, 'api', {'Referer': 'https://www.bilibili.com/',
                                    'Origin': 'https://www.bilibili.com'})
    txt, st, _ = _fetch(url, proxy, timeout, headers)
    d = json.loads(txt)
    if d.get('code') != 0:
        raise RuntimeError(f'bilibili api: {d.get("code")} {d.get("message")}')
    out = []
    for x in (d.get('data') or {}).get('list') or []:
        title = _clean(str(x.get('title') or ''))
        if not title:
            continue
        u = x.get('short_link_v2') or x.get('short_link') \
            or (f"https://www.bilibili.com/video/av{x.get('aid')}" if x.get('aid') else '')
        owner = (x.get('owner') or {}).get('name') or ''
        out.append(_mk(title, u, _clean(str(x.get('desc') or ''))[:140],
                       extra={'up': owner,
                              'score': x.get('score'),
                              'tname': x.get('tname')}))
    return _local_filter(out, q, limit)


# ============================================================ B站搜索热词

def bili_word(q, limit=10, proxy=None, timeout=15):
    """B站搜索热词 (app trending/ranking; 20 词; 榜单接口不支持关键词)"""
    url = 'https://app.bilibili.com/x/v2/search/trending/ranking'
    headers = _headers(url, 'api', {'Referer': 'https://app.bilibili.com/'})
    txt, st, _ = _fetch(url, proxy, timeout, headers)
    d = json.loads(txt)
    if d.get('code') != 0:
        raise RuntimeError(f'bilibili api: {d.get("code")} {d.get("message")}')
    out = []
    for x in (d.get('data') or {}).get('list') or []:
        kw = x.get('keyword') or x.get('show_name') or ''
        if not kw:
            continue
        qn = urllib.parse.quote(kw)
        out.append(_mk(kw, f'https://search.bilibili.com/all?keyword={qn}',
                       None, extra={'position': x.get('position'),
                                    'hot_id': x.get('hot_id')}))
    return _local_filter(out, q, limit)


# ============================================================ 注册表
# search: True  = 支持关键词, rank 把 -q 直接传适配器 (站内过滤)
# search: False = 纯榜单, rank 拉全榜后本地 BM25 语义筛选
HOT_SITES = {
    # ---- 国内综合 (默认源) ----
    'zhihu':        {'fn': zhihu_hot,    'desc': '知乎热榜', 'search': False},
    'weibo':        {'fn': weibo,        'desc': '微博热搜', 'search': False},
    'baidu':        {'fn': baidu,        'desc': '百度热搜', 'search': False},
    'douyin':       {'fn': douyin,       'desc': '抖音热搜词榜 (50词)', 'search': False},
    'douyin_hot':   {'fn': douyin_hot,   'desc': '抖音热点榜 (事件聚合+视频数)', 'search': False},
    'toutiao_hot':  {'fn': toutiao_hot,  'desc': '今日头条热榜 (官方 hot-board)', 'search': False},
    'bili_hot':     {'fn': bili_hot,     'desc': 'B站热门视频榜', 'search': False},
    'bili_rank':    {'fn': bili_rank,    'desc': 'B站全站排行榜 (质量周榜)', 'search': False},
    'bili_word':    {'fn': bili_word,    'desc': 'B站搜索热词 (20词)', 'search': False},
    'tieba':        {'fn': tieba,        'desc': '百度贴吧热议榜 (30话题)', 'search': False},
    'sina_hot':     {'fn': sina_hot,     'desc': '新浪新闻热榜', 'search': False},
    'douban_movie': {'fn': douban_movie, 'desc': '豆瓣热门电影 (评分+链接)', 'search': False},
    'netease_music': {'fn': netease_music, 'desc': '网易云新歌榜 (100首)', 'search': False},
    'ithome':       {'fn': ithome,       'desc': 'IT之家资讯榜', 'search': False},
    # ---- 国际/技术 (默认源) ----
    'hn_official':  {'fn': hn_official,  'desc': 'Hacker News 热榜', 'search': False},
    'github_trend': {'fn': github_trend, 'desc': 'GitHub Trending (近7日)', 'search': True},
    'lobsters':     {'fn': lobsters,     'desc': 'Lobsters 热帖', 'search': False},
    # ---- 扩展 ----
    'toutiao':      {'fn': toutiao,      'desc': '今日头条推荐 feed (移动指纹, 非热榜)', 'search': False},
    'reddit':       {'fn': reddit,       'desc': 'Reddit r/<sub> 热帖 (需代理; 本环境 IP 受限)', 'search': True},
}

DEFAULT_HOT_SOURCES = ['zhihu', 'weibo', 'baidu', 'douyin', 'douyin_hot',
                       'toutiao_hot', 'bili_hot', 'tieba', 'hn_official',
                       'github_trend']
