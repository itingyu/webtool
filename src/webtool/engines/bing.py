# -*- coding: utf-8 -*-
"""Bing 搜索引擎: RSS 优先, HTML 兜底; 国内 cn.bing.com 直连, 国外 www.bing.com

- HTML 端点 https://www.bing.com/search?q=&first=&count= (count 上限 30),
  '#b_results > li.b_algo' 为结果块, 'h2 a' 取标题+链接, '.b_caption p' 取摘要
- 代理策略: 默认直连 cn.bing.com (国内稳); 配了全局代理则走 www.bing.com
  (代理出口在国外, cn 域名解析到同一个 bing, 用 www 语义更正)
- fetch 带 fallback_direct=True: 代理抖动时自动降级直连, 不会整引擎挂掉
"""
import re
import urllib.parse

from ..resilient import fetch as rfetch, FetchError

GOOGLE_HOSTED = ('cn.bing.com', 'www.bing.com')  # 两者搜索结果结构一致


def search(query, max_results=10, proxy=None, timeout=15, market='zh-CN', page=1):
    """返回 [{title,url,snippet}]; RSS→HTML 自动降级"""
    try:
        return _rss(query, max_results, proxy, timeout, market, page)
    except Exception:
        return _html(query, max_results, proxy, timeout, market, page)


def _host(proxy):
    # 有代理 → 国外出口用 www.bing.com; 直连 → cn.bing.com 国内最快
    return 'www.bing.com' if proxy else 'cn.bing.com'


def _rss(query, max_results, proxy, timeout, market, page):
    q = urllib.parse.quote(query)
    first = (page - 1) * max_results + 1
    url = (f'https://{_host(proxy)}/search?q={q}&format=rss&count={max_results}'
           f'&first={first}&setmkt={urllib.parse.quote(market)}')
    xml, status, _via = rfetch(url, proxy=proxy, timeout=timeout,
                               fallback_direct=True)
    items = re.findall(r'<item>(.*?)</item>', xml, re.S)
    out = []
    for it in items:
        t = re.search(r'<title>(.*?)</title>', it, re.S)
        l = re.search(r'<link>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</link>', it, re.S)
        d = re.search(r'<description>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</description>', it, re.S)
        title = _unescape((t.group(1) if t else '').strip())
        link = (l.group(1) if l else '').strip()
        snip = re.sub(r'<[^>]+>', '', d.group(1)) if d else ''
        if not link or link.startswith('http://' + 'bing.com'):
            continue
        out.append({'rank': len(out) + 1, 'title': title, 'url': link,
                    'snippet': _unescape(snip)[:300]})
        if len(out) >= max_results:
            break
    if not out:
        raise FetchError(f'bing RSS 0 条 (status={status})')
    return out


def _html(query, max_results, proxy, timeout, market, page):
    """HTML 兜底: RSS 被限流/风控时用, count 上限 30"""
    q = urllib.parse.quote(query)
    first = (page - 1) * max_results + 1
    count = max_results if max_results <= 30 else 30
    mkt = f'&mkt={urllib.parse.quote(market)}' if market else ''
    url = (f'https://{_host(proxy)}/search?q={q}&count={count}&first={first}'
           f'&setlang={market.split("-")[0]}{mkt}')
    html, status, _via = rfetch(url, proxy=proxy, timeout=timeout,
                                fallback_direct=True,
                                headers={'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8'})
    if 'g_bP' not in html and 'b_algo' not in html:
        raise FetchError(f'bing HTML 返回异常页 (status={status}, 长度 {len(html)})')
    out, seen = [], set()
    # 每个 <li class="b_algo"> 是一条结果
    for m in re.finditer(r'<li class="b_algo".*?(?=<li class="b_algo"|<li class="b_msg'
                         r'|</ol>)', html, re.S):
        block = m.group(0)
        a = re.search(r'<h2[^>]*>\s*<a[^>]*href="(https?://[^"]+)"[^>]*>(.*?)</a>',
                      block, re.S)
        if not a:
            continue
        u, t_html = a.group(1), a.group(2)
        if u in seen:
            continue
        title = _unescape(_strip_tags(t_html))
        if not title:
            continue
        seen.add(u)
        cap = re.search(r'<p class="b_lineclamp[^"]*"[^>]*>(.*?)</p>', block, re.S) \
              or re.search(r'class="b_caption[^"]*"[^>]*>.*?<p[^>]*>(.*?)</p>', block, re.S)
        if not cap:
            # 退化: h2 之后第一个 <p> (个别版式摘要无 b_caption 包裹)
            after_h2 = block.split('</h2>', 1)[-1]
            cap = re.search(r'<p[^>]*>(.*?)</p>', after_h2, re.S)
        snip = _unescape(_strip_tags(cap.group(1))) if cap else ''
        out.append({'rank': len(out) + 1, 'title': title, 'url': u,
                    'snippet': snip[:300]})
        if len(out) >= max_results:
            break
    if not out:
        raise FetchError(f'bing HTML 解析 0 条 (status={status})')
    return out


def _strip_tags(s):
    return re.sub(r'<[^>]+>', '', s or '')


def _unescape(s):
    from html import unescape
    return unescape(s or '').strip()
