# -*- coding: utf-8 -*-
"""Bing 搜索引擎: curl_cffi chrome 指纹 (浏览器级, 不触发反爬) HTML 通道

2026-10 实测排序一致性:
- urllib (HTTP/1.1 + Python TLS 指纹) 直连: 排序与浏览器主页不同, 走代理
  (www.bing.com 国外出口) 更是给出知乎/CSDN 提前的旧索引序
- curl_cffi chrome 指纹直连 cn.bing.com: 与浏览器主页搜索前 N 名一致,
  0.5s 间隔 5 连打零风控零验证, 排序稳定
- 走代理访问 www.bing.com 会拿到国外版 www 内链页 → 不走代理, bing 国内
  本来就可用, 恒直连

RSS 通道保留为兜底 (curl_cffi 被限流时), 但 RSS 是独立索引, 排序与主页
差异大, 仅在 HTML 失败时使用。
"""
import re
import urllib.parse

from ..resilient import fetch as rfetch, FetchError
from ..http import UAS

try:
    from curl_cffi import requests as _cr
    _HAS_CFFI = True
except ImportError:
    _HAS_CFFI = False


def search(query, max_results=10, proxy=None, timeout=15, market='zh-CN', page=1):
    """返回 [{title,url,snippet}]; chrome指纹 HTML → urllib HTML → RSS 三级降级"""
    err1 = err2 = None
    if _HAS_CFFI:
        try:
            return _cffi_html(query, max_results, proxy, timeout, market, page)
        except Exception as e:
            err1 = e
    try:
        return _urllib_html(query, max_results, proxy, timeout, market, page)
    except Exception as e:
        err2 = e
    return _rss(query, max_results, proxy, timeout, market, page)


def _host(proxy):
    return 'www.bing.com' if proxy else 'cn.bing.com'


def _cffi_html(query, max_results, proxy, timeout, market, page):
    """curl_cffi chrome 指纹: 浏览器级 TLS/HTTP2, bing 无感"""
    q = urllib.parse.quote(query)
    url = (f'https://cn.bing.com/search?q={q}&count={min(max_results, 30)}'
           f'&setmkt={urllib.parse.quote(market)}')
    # bing 国内可用: 恒直连, 代理出口反而触发国外版重排
    s = _cr.Session(impersonate='chrome', timeout=timeout)
    s.get('https://cn.bing.com/', timeout=timeout)
    r = s.get(url, timeout=timeout,
              headers={'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8'})
    if r.status_code in (429, 403) or 'challenge-form' in r.text:
        raise FetchError(f'bing cffi 被风控 ({r.status_code})')
    out = _parse_html(r.text, max_results)
    if not out:
        raise FetchError(f'bing cffi 解析 0 条 (len={len(r.text)})')
    return out


def _urllib_html(query, max_results, proxy, timeout, market, page):
    """urllib HTML 兜底 (无 curl_cffi 时)"""
    q = urllib.parse.quote(query)
    first = (page - 1) * max_results + 1
    count = max_results if max_results <= 30 else 30
    mkt = f'&mkt={urllib.parse.quote(market)}' if market else ''
    url = (f'https://{_host(proxy)}/search?q={q}&count={count}&first={first}'
           f'&setlang={market.split("-")[0]}{mkt}')
    html, status, _via = rfetch(url, proxy=proxy, timeout=timeout,
                                fallback_direct=True,
                                headers={'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8'})
    if 'b_algo' not in html:
        raise FetchError(f'bing urllib HTML 异常页 (status={status})')
    out = _parse_html(html, max_results)
    if not out:
        raise FetchError(f'bing urllib 解析 0 条 (status={status})')
    return out


def _parse_html(html, max_results):
    """li.b_algo → (title, url, snippet); 兼容 h2 a 与裸 a 两种结构"""
    out, seen = [], set()
    for m in re.finditer(r'<li class="b_algo".*?(?=<li class="b_algo"|<li class="b_msg'
                         r'|</ol>)', html, re.S):
        block = m.group(0)
        a = (re.search(r'<h2[^>]*>\s*<a[^>]*href="(https?://[^"]+)"[^>]*>(.*?)</a>',
                       block, re.S)
             or re.search(r'<a[^>]*href="(https?://[^"]+)"[^>]*>(.*?)</a>', block, re.S))
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
            after = block.split('</h2>', 1)[-1]
            cap = re.search(r'<p[^>]*>(.*?)</p>', after, re.S)
        snip = _unescape(_strip_tags(cap.group(1))) if cap else ''
        out.append({'rank': len(out) + 1, 'title': title, 'url': u,
                    'snippet': snip[:300]})
        if len(out) >= max_results:
            break
    return out


def _rss(query, max_results, proxy, timeout, market, page):
    """RSS 兜底: 独立索引, 排序与主页差异大, 仅兜底用"""
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


def _strip_tags(s):
    return re.sub(r'<[^>]+>', '', s or '')


def _unescape(s):
    from html import unescape
    return unescape(s or '').strip()
