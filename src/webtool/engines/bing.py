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

from .. import captcha, transport

_ENDPOINT = 'https://cn.bing.com'


def search(query, max_results=10, proxy=None, timeout=15, market='zh-CN', page=1):
    """返回 [{title,url,snippet}]; chrome指纹 HTML → urllib HTML → RSS 三级降级"""
    try:
        return _cffi_html(query, max_results, proxy, timeout, market, page)
    except transport.CooldownError:
        raise
    except Exception:
        pass
    try:
        return _urllib_html(query, max_results, proxy, timeout, market, page)
    except Exception:
        pass
    return _rss(query, max_results, proxy, timeout, market, page)


def _host(proxy):
    return 'www.bing.com' if proxy else 'cn.bing.com'


def _cffi_html(query, max_results, proxy, timeout, market, page):
    """curl_cffi chrome 指纹: 浏览器级 TLS/HTTP2, bing 无感"""
    q = urllib.parse.quote(query)
    first = (page - 1) * max_results + 1
    count = min(max_results, 30)
    url = (f'{_ENDPOINT}/search?q={q}&count={count}&first={first}'
           f'&setmkt={urllib.parse.quote(market)}')
    # bing 国内可用: 恒直连, 代理出口反而触发国外版重排
    s, p = transport._new_session('chrome131_win', None, 'bing')
    # 首页预热: 领会话 cookie + 让服务端看到导航行为
    try:
        s.get(_ENDPOINT + '/', timeout=timeout)
    except Exception:
        pass
    r = s.get(url, timeout=timeout,
              headers=transport.headers_for('nav', url, referer=_ENDPOINT + '/',
                                            profile=p))
    if r.status_code in (429, 403) or 'challenge-form' in r.text:
        captcha.mark_blocked('bing')
        raise RuntimeError(f'bing cffi 被风控 ({r.status_code})')
    transport._persist_cookies(s, 'bing')
    out = _parse_html(r.text, max_results)
    if not out:
        raise RuntimeError(f'bing cffi 解析 0 条 (len={len(r.text)})')
    captcha.mark_ok('bing')
    return out


def _urllib_html(query, max_results, proxy, timeout, market, page):
    """urllib HTML 兜底"""
    q = urllib.parse.quote(query)
    first = (page - 1) * max_results + 1
    count = max_results if max_results <= 30 else 30
    mkt = f'&mkt={urllib.parse.quote(market)}' if market else ''
    url = (f'https://{_host(proxy)}/search?q={q}&count={count}&first={first}'
           f'&setlang={market.split("-")[0]}{mkt}')
    h = transport.headers_for('nav', url, referer=f'https://{_host(proxy)}/',
                              full=True)
    text, status, _via = _resilient(url, proxy=proxy, timeout=timeout,
                                    headers=h)
    if 'b_algo' not in text:
        raise RuntimeError(f'bing urllib HTML 异常页 (status={status})')
    out = _parse_html(text, max_results)
    if not out:
        raise RuntimeError(f'bing urllib 解析 0 条 (status={status})')
    return out


def _resilient(url, proxy=None, timeout=15, headers=None):
    """代理失败自动直连重试 (fetch 等非引擎通道复用)"""
    from ..http import http_get
    last = None
    for p in ([proxy, None] if proxy else [None]):
        try:
            text, status = http_get(url, proxy=p, timeout=timeout, headers=headers)
            return text, status, 'proxy' if p else 'direct'
        except Exception as e:
            last = e
    raise RuntimeError(f'{url} failed: {last}')


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
    xml, status, _via = _resilient(url, proxy=proxy, timeout=timeout)
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
        raise RuntimeError(f'bing RSS 0 条 (status={status})')
    return out


def _strip_tags(s):
    return re.sub(r'<[^>]+>', '', s or '')


def _unescape(s):
    from html import unescape
    return unescape(s or '').strip()
