# -*- coding: utf-8 -*-
"""Bing RSS 搜索引擎: 免费/免key/免JS, 国内外可直连, 支持市场与翻页"""
import re
import urllib.parse

from ..resilient import fetch as rfetch, FetchError


def search(query, max_results=10, proxy=None, timeout=15, market='zh-CN', page=1):
    """返回 [{title,url,snippet}]"""
    q = urllib.parse.quote(query)
    first = (page - 1) * max_results + 1
    url = (f'https://cn.bing.com/search?q={q}&format=rss&count={max_results}&first={first}'
           f'&setmkt={urllib.parse.quote(market)}')
    xml, status, _via = rfetch(url, proxy=proxy, timeout=timeout,
                               fallback_direct=False)  # bing RSS 国内直连必通, 无需降级
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
    return out


def _unescape(s):
    from html import unescape
    return unescape(s).strip()
