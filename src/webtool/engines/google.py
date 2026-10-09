# -*- coding: utf-8 -*-
"""Google News RSS 搜索引擎: 免key, 需代理(国内被墙)

链接是 news.google.com/rss/articles/.. 跳转链, 新版无法离线解码,
保留原链 + title 内含来源站名; 供 Agent 二次 fetch 或按 source 过滤。
"""
import re
import urllib.parse

from ..resilient import fetch as rfetch


def search(query, max_results=10, proxy=None, timeout=15, market='zh-CN', page=1):
    lang, gl, ceid = _market(market)
    q = urllib.parse.quote(query)
    url = (f'https://news.google.com/rss/search?q={q}'
           f'&hl={lang}&gl={gl}&ceid={gl}:{ceid}')
    xml, status, _via = rfetch(url, proxy=proxy, timeout=timeout)
    items = re.findall(r'<item>(.*?)</item>', xml, re.S)
    out = []
    for it in items:
        t = re.search(r'<title>(.*?)</title>', it, re.S)
        l = re.search(r'<link>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</link>', it, re.S)
        d = re.search(r'<pubDate>(.*?)</pubDate>', it, re.S)
        src = re.search(r'<source[^>]*>(.*?)</source>', it, re.S)
        title = _unescape(t.group(1)) if t else ''
        if not title:
            continue
        out.append({'rank': len(out) + 1, 'title': title.strip(),
                    'url': (l.group(1).strip() if l else ''),
                    'snippet': (src.group(1).strip() + ' · ' if src else '') + (d.group(1).strip() if d else ''),
                    'source': src.group(1).strip() if src else '',
                    'date': (d.group(1).strip() if d else '')})
        if len(out) >= max_results:
            break
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
