# -*- coding: utf-8 -*-
"""百度搜索引擎: TLS 指纹模拟 (curl_cffi) + 验证页识别冷却

核心突破 (2026-10-09 实测): python-urllib 的 TLS 握手指纹(JA3)被百度识别,
即使完整 cookie+Referer 也会弹安全验证页 (1438B)。用 curl_cffi 的
impersonate='chrome' 模拟 Chrome 完整 TLS/JA3/HTTP2 指纹后:
- Session 首页领 cookie 后搜索: 5/5 成功率 (多 query 连续验证)
失败自动降级链: curl_cffi session → curl_cffi 直搜 → urllib+退避 → captcha 冷却

链接解析: <h3 title><a href="baidu.com/link?url=.."> → 302 Location
广告: result-op 聚合卡片 → is_ad=True
"""
import re
import time
import urllib.parse

from ..http import UAS
from .. import captcha

BAIDU = 'https://www.baidu.com'

# curl_cffi 可选: 装了用 TLS 指纹模拟(推荐), 没装退化 urllib
try:
    from curl_cffi import requests as _cr
    _HAS_CFFI = True
except ImportError:
    _HAS_CFFI = False


def search(query, max_results=10, proxy=None, timeout=15, market=None, page=1):
    if captcha.suspended('baidu'):
        raise RuntimeError(f"baidu 冷却中({captcha.cooldown_left('baidu')}s, 此前触发人机验证), 请换引擎: -e bing,sogou")
    q = urllib.parse.quote(query)
    first = (page - 1) * max_results + 1
    url = f'{BAIDU}/s?wd={q}&rn={max_results}&pn={first - 1}'
    html, via = _get_html(url, proxy, timeout)
    out = []
    for m in re.finditer(
            r'<div[^>]*class="((?:result|result-op)[^"]*c-container[^"]*)"[^>]*>', html):
        cls = m.group(1)
        seg = html[m.start():m.start() + 4000]
        is_ad = 'result-op' in cls
        t = re.search(r'<h3[^>]*class="[^"]*title[^"]*"[^>]*>\s*<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', seg, re.S)
        if not t:
            continue
        title = _unescape(re.sub(r'<[^>]+>', '', t.group(2))).strip()
        if not title:
            continue
        jump = t.group(1)
        mu = re.search(r'\smu="(https?://[^"]+)"', html[m.start():m.start() + 800])
        real = mu.group(1) if (mu and _is_real_url(mu.group(1))) else None
        out.append({'rank': len(out) + 1, 'title': title,
                    'url': real or jump, 'snippet': _snippet(seg),
                    'is_ad': is_ad, 'resolved': bool(real)})
        if len(out) >= max_results:
            break
    _resolve_links(out, proxy, timeout)
    captcha.mark_ok('baidu')
    return out


def _get_html(url, proxy, timeout):
    """三级通道: curl_cffi session → curl_cffi 直搜 → urllib 退避。返回 (html, via)"""
    # 通道1: curl_cffi TLS 指纹 + 会话 (实测 5/5)
    if _HAS_CFFI:
        try:
            s = _cr.Session(impersonate='chrome',
                            proxy=proxy or None,
                            timeout=timeout)
            s.get(BAIDU + '/', timeout=timeout)
            r = s.get(url, timeout=timeout,
                      headers={'Referer': BAIDU + '/',
                               'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8'})
            blocked, sign = captcha.detect('baidu', r.text)
            if not blocked:
                return r.text, 'curl_cffi+session'
        except Exception:
            pass
        # 通道2: curl_cffi 直搜 (无 cookie 偶尔也放行)
        try:
            r = _cr.get(url, impersonate='chrome', proxy=proxy or None,
                        timeout=timeout,
                        headers={'Referer': BAIDU + '/'})
            blocked, sign = captcha.detect('baidu', r.text)
            if not blocked:
                return r.text, 'curl_cffi'
        except Exception:
            pass
    # 通道3: urllib + 退避重试 (原逻辑)
    return _urllib_fallback(url, proxy, timeout), 'urllib'


def _urllib_fallback(url, proxy, timeout, retries=3):
    import urllib.request
    import http.cookiejar
    from ..http import build_opener
    last_verdict = None
    proxy_options = [proxy, None] if proxy else [None]
    for p in proxy_options:
        for attempt in range(retries):
            ua = UAS[attempt % 2]
            cj = http.cookiejar.CookieJar()
            opener = build_opener(p, cj)
            try:
                opener.open(urllib.request.Request(BAIDU + '/', headers={'User-Agent': ua}),
                            timeout=timeout)
            except Exception:
                pass
            req = urllib.request.Request(url, headers={
                'User-Agent': ua, 'Referer': BAIDU + '/',
                'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8'})
            try:
                r = opener.open(req, timeout=timeout)
                html = r.read().decode('utf-8', errors='ignore')
            except Exception as e:
                last_verdict = f'network: {str(e)[:120]}'
                time.sleep(2.0 * (attempt + 1))
                continue
            blocked, sign = captcha.detect('baidu', html)
            if not blocked:
                return html
            last_verdict = f'captcha({sign})'
            time.sleep(2.0 * (attempt + 1))
    captcha.mark_blocked('baidu')
    raise RuntimeError(f"baidu 人机验证拦截: {last_verdict}; "
                       f"建议 pip install curl_cffi (TLS指纹) 或换 -e bing,sogou")


def _snippet(seg):
    ab = (re.search(r'class="c-abstract[^"]*"[^>]*>(.*?)</div>', seg, re.S)
          or re.search(r'class="[^"]*content-right[^"]*"[^>]*>(.*?)</(?:div|span)>', seg, re.S))
    return _unescape(re.sub(r'<[^>]+>', '', ab.group(1))).strip()[:300] if ab else ''


def _is_real_url(u):
    from urllib.parse import urlparse
    host = urlparse(u).netloc
    return not host.endswith(('baidu.com', 'bdstatic.com', 'bcebos.com'))


def _resolve_links(results, proxy, timeout):
    import concurrent.futures as cf
    todo = [(i, r) for i, r in enumerate(results)
            if not r['resolved'] and 'baidu.com/link?' in r['url']]

    def work(item):
        i, r = item
        return i, _resolve_one(r['url'], proxy, timeout)

    with cf.ThreadPoolExecutor(5) as ex:
        for i, real in ex.map(work, todo):
            if real:
                results[i]['url'] = real
                results[i]['resolved'] = True
            else:
                results[i]['resolved'] = False


def _resolve_one(link, proxy, timeout):
    if _HAS_CFFI:
        try:
            r = _cr.get(link, impersonate='chrome', proxy=proxy or None,
                        timeout=timeout, allow_redirects=False,
                        headers={'Referer': BAIDU + '/'})
            loc = r.headers.get('Location', '') or ''
            if loc.startswith('http') and 'baidu.com' not in loc:
                return loc
        except Exception:
            pass
    import urllib.request

    class NR(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None

    op = urllib.request.build_opener(NR())
    try:
        req = urllib.request.Request(link, headers={
            'User-Agent': UAS[0], 'Referer': BAIDU + '/'})
        op.open(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        loc = e.headers.get('Location', '')
        if loc.startswith('http') and 'baidu.com' not in loc:
            return loc
    except Exception:
        pass
    return None


def _unescape(s):
    from html import unescape
    return unescape(s or '').strip()
