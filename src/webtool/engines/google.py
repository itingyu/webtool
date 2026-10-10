# -*- coding: utf-8 -*-
"""Google 引擎: Web HTML 优先 (需代理), news RSS 降级, 结果带 quality 标注

2026-10 实测: 数据中心代理出口 IP 对 www.google.com/search 触发 IP 级
reCAPTCHA (429 + 'unusual traffic', consent cookie/TLD/参数变体均无效,
纯 HTTP 不可解) — 429 时自动降级 news.google.com RSS (同 IP 全端点 200,
跳转链需浏览器打开, 靠 title 内 source 后缀供二次定位)。

news RSS 是新闻检索不是全 Web 搜索:
- 结果带 channel='news' 标注, 消费方 (agent) 可据此判断覆盖面
- 支持 when: 相对时间窗 (Web 语义下默认 1y, 避免被旧闻淹没)
- 直搜语义可用 (LMArena/Artificial Analysis 等高相关命中)
"""
import re
import urllib.parse

from ..resilient import fetch as rfetch, FetchError
from .. import captcha
from ..http import build_opener


def search(query, max_results=10, proxy=None, timeout=15, market='zh-CN', page=1):
    """Web HTML 失败 (429/验证页) → 自动降级 news RSS, 结果标 channel

    代理优先级: 引擎级配置 > 全局 proxy > 无代理 (直连仅 news RSS 国内可达,
    web 端点必被墙, 无代理时直接走 news 不浪费时间试 web)
    """
    if proxy:
        if captcha.suspended('google'):
            pass  # 冷却期内不再试 web, 直接 news
        else:
            try:
                return _web(query, max_results, proxy, timeout, market, page)
            except FetchError as e:
                # resilient.fetch 对 429 先试直连再抛聚合错误, 错误串带
                # [proxy_http_status=]; IP 级反爬特征时降级
                s = str(e)
                if not ('429' in s or 'unusual' in s or '/sorry/' in s
                        or 'proxy_http_status=429' in s):
                    raise
    # 无代理或 web 被封: news RSS (国内直连可达性差但配了代理就能通,
    # gnews 域名不在 /search 的限流范围内)
    return _news(query, max_results, proxy, timeout, market, page)


# ---------- Web HTML ----------

def _web(query, max_results, proxy, timeout, market, page):
    if not proxy:
        raise FetchError('google web 需要代理')
    q = urllib.parse.quote(query)
    num = min(max_results, 20)
    start = (page - 1) * 10 + 1
    hl, gl = ('zh-CN', 'CN') if market.startswith('zh') else ('en-US', 'US')
    url = (f'https://www.google.com/search?q={q}&num={num}&start={start}'
           f'&hl={hl}&gl={gl}&pws=0')
    html, status, _via = rfetch(url, proxy=proxy, timeout=timeout,
                                fallback_direct=False)
    if status in (429, 403) or 'unusual traffic' in html or '/sorry/' in html:
        captcha.mark_blocked('google')
        raise FetchError(f'google web IP级反爬({status}), 已降级/冷却'
                         f'{captcha.cooldown_left("google")}s')

    anchors = re.findall(
        r'<a\b[^>]*href="(/url\?[^"]*|https?://[^"]*)"[^>]*>(.*?)</a>', html, re.S)
    out, seen = [], set()
    for href, inner in anchors:
        u = _real_url(href)
        if not u:
            continue
        h3 = re.search(r'<h3\b[^>]*>(.*?)</h3>', inner, re.S)
        if not h3:
            continue
        title = _text(h3.group(1))
        if not title or u in seen:
            continue
        seen.add(u)
        out.append({'rank': 0, 'title': title, 'url': u, 'snippet': ''})
        if len(out) >= max_results:
            break
    _attach_snippets(html, out)
    for i, r in enumerate(out):
        r['rank'] = i + 1
    if not out:
        raise FetchError(f'google web 解析 0 条 (status={status}, 可能改版)')
    captcha.mark_ok('google')
    return out


def _real_url(href):
    if href.startswith('/url?'):
        m = _URL_RE.search(href)
        if not m:
            return None
        href = urllib.parse.unquote(m.group(1))
    if href.startswith('//'):
        href = 'https:' + href
    if not href.startswith('http'):
        return None
    host = urllib.parse.urlparse(href).netloc
    if host.split(':')[0] in _GOOGLE_HOSTS:
        return None
    return href


_GOOGLE_HOSTS = ('www.google.com', 'google.com', 'accounts.google.com',
                 'support.google.com', 'policies.google.com',
                 'maps.google.com', 'news.google.com', 'books.google.com')

_URL_RE = re.compile(r'/url\?(?:[^&]*&)*q=(https?%3A[^&"]+)')


def _attach_snippets(html, out):
    blocks = re.findall(r'class="VwiC3b[^"]*"[^>]*>(.*?)</div>', html, re.S)
    for r, b in zip(out, blocks):
        r['snippet'] = _text(b)[:300]


def _text(s):
    s = re.sub(r'<[^>]+>', '', s or '')
    from html import unescape
    return unescape(s).strip()


# ---------- news RSS 降级 ----------

def _news(query, max_results, proxy, timeout, market, page):
    lang, gl, ceid = _market(market)
    q = urllib.parse.quote(query)
    # Web 语义借道新闻检索: 默认 1 年窗口, 翻页映射 start→offset
    offset = (page - 1) * max_results
    when = 'when:1y'
    url = (f'https://news.google.com/rss/search?q={q}+{when}'
           f'&hl={lang}&gl={gl}&ceid={gl}:{ceid}')
    xml, status, _via = rfetch(url, proxy=proxy, timeout=timeout)
    items = re.findall(r'<item>(.*?)</item>', xml, re.S)
    out = []
    for it in items[offset:offset + max_results]:
        t = re.search(r'<title>(.*?)</title>', it, re.S)
        l = re.search(r'<link>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</link>', it, re.S)
        d = re.search(r'<pubDate>(.*?)</pubDate>', it, re.S)
        src = re.search(r'<source[^>]*>(.*?)</source>', it, re.S)
        title = _unescape(t.group(1)) if t else ''
        if not title:
            continue
        out.append({'rank': len(out) + 1, 'title': title.strip(),
                    'url': (l.group(1).strip() if l else ''),
                    'snippet': (src.group(1).strip() + ' · ' if src else '')
                               + (d.group(1).strip() if d else ''),
                    'source': src.group(1).strip() if src else '',
                    'date': (d.group(1).strip() if d else ''),
                    'channel': 'news'})
    # 无新闻覆盖不算错误: 返回空列表, 上层自然跳过该引擎贡献
    return out


def _market(market):
    if market.startswith('zh'):
        return 'zh-Hans', 'CN', 'zh-Hans'
    if market.startswith('en'):
        return 'en-US', 'US', 'en-US'
    return 'zh-Hans', 'CN', 'zh-Hans'


def _unescape(s):
    from html import unescape
    return unescape(s or '').strip()


def resolve_link(url, proxy=None, timeout=10):
    """跳转链还原: /url?q= 老式内链直接解; news.google.com/articles
    走 gnews batchexecute 解码 (纯 HTTP, 带缓存+熔断); 失败原样返回"""
    if 'news.google.com/rss/articles/' in url or 'news.google.com/articles/' in url:
        from . import gnews
        return gnews.decode(url, proxy=proxy, timeout=timeout) or url
    if 'google.com/url' not in url:
        return url
    m = _URL_RE.search(url)
    if m:
        return urllib.parse.unquote(m.group(1))
    return url
