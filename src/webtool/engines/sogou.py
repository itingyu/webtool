# -*- coding: utf-8 -*-
"""搜狗搜索引擎: 中文内容覆盖好, 直连可解析, link 跳转链需二次解析"""
import re
import urllib.parse
import http.cookiejar

from ..http import http_get, build_opener
from .. import captcha

ENDPOINT = 'https://www.sogou.com/web'
SOUGOU = 'https://www.sogou.com'
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def _new_session():
    cj = http.cookiejar.CookieJar()
    opener = build_opener(None, cj)
    opener.add_handler(_NoRedirect())
    return cj, opener


def search(query, max_results=10, proxy=None, timeout=15, market=None, _session=None):
    """返回 [{title,url,snippet}]  url 可能是 /link?url= 跳转链

    反爬对策 (2026-10 实测): sogou 对"无 cookie 冷启动"请求随机弹 antispider,
    浏览器形态 = 首页预热拿 SUID/SNUID cookie + 会话内带 Referer 请求 → 3/3 通过.
    所以主路径用会话预热, 被拦再换新会话重试一次 (预热 cookie 每会话独立).
    """
    if captcha.suspended('sogou'):
        raise RuntimeError(f"sogou 冷却中({captcha.cooldown_left('sogou')}s, 此前触发反爬), 请换引擎: -e bing,baidu")
    q = urllib.parse.quote(query)
    from ..resilient import fetch as rfetch
    html = None
    for attempt in range(2):
        cj, opener = _session if _session else _new_session()
        _via = None
        try:
            # 首页预热: 拿 SUID/SNUID/ABTEST 等会话 cookie (浏览器形态第一步)
            pre = urllib.request.Request(SOUGOU + '/', headers={'User-Agent': UA})
            opener.open(pre, timeout=timeout)
            # 代理时 rfetch 走 resilient (带降级); 无代理走已预热的 opener
            if proxy:
                html, status, _via = rfetch(f'{ENDPOINT}?query={q}', proxy=proxy,
                                            timeout=timeout)
            else:
                req = urllib.request.Request(f'{ENDPOINT}?query={q}',
                                             headers={'User-Agent': UA,
                                                      'Referer': SOUGOU + '/',
                                                      'Accept-Language': 'zh-CN,zh;q=0.9'})
                with opener.open(req, timeout=timeout) as r:
                    html = r.read().decode('utf-8', 'ignore')
                    status = r.status
        except Exception:
            html = None
        if html:
            blocked, sign = captcha.detect('sogou', html)
            if not blocked:
                captcha.mark_ok('sogou')
                break
            captcha.mark_blocked('sogou')
            html = None
        if _session:  # 外部注入的会话不重试
            break
        time.sleep(1.5)  # 换新会话重试
    if not html:
        cd = captcha.cooldown_left('sogou')
        raise RuntimeError(f'sogou 反爬拦截({sign if "sign" in dir() else "unknown"}); '
                           f'已冷却{cd}s, 请换 -e bing,baidu')
    items = re.findall(
        r'<h3 class="vr-title[^"]*"[^>]*>(.*?)</h3>',
        html, re.S)
    out = []
    seen = set()
    for blk in items[:max_results * 2]:
        a = re.search(r'<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', blk, re.S)
        if not a:
            continue
        u, t = a.group(1), a.group(2)
        title = _unescape(re.sub(r'<[^>]+>', '', t)).strip()
        if not title:
            continue
        url = u if u.startswith('http') else 'https://www.sogou.com' + u
        if url in seen:
            continue
        seen.add(url)
        out.append({'rank': len(out) + 1, 'title': title, 'url': url, 'snippet': ''})
        if len(out) >= max_results:
            break
    # 附带摘要 (可选字段, 解析失败不影响)
    _fill_snippets(html, out)
    return out


def _fill_snippets(html, out):
    """尽力提取每个结果下方的摘要文本"""
    blocks = re.split(r'<h3 class="vr-title[^"]*"[^>]*>', html)
    for i, b in enumerate(blocks[1:len(out) + 1]):
        m = re.search(r'class="(?:fz-mid space-txt|str-text-info)[^"]*"[^>]*>(.*?)</(?:div|p|span)>', b, re.S)
        if m:
            txt = _unescape(re.sub(r'<[^>]+>', '', m.group(1))).strip()
            out[i]['snippet'] = txt[:300]


def resolve_link(link_url, proxy=None, timeout=15):
    """把 /link?url=xxx 解析为真实 URL: 需带搜索会话 cookie"""
    cj, opener = _new_session()
    # 先触发 cookie 发放
    try:
        opener.open(urllib.request.Request('https://www.sogou.com/',
                    headers={'User-Agent': 'Mozilla/5.0'}), timeout=timeout)
    except Exception:
        pass
    import urllib.request
    req = urllib.request.Request(
        link_url if link_url.startswith('http') else 'https://www.sogou.com' + link_url,
        headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'https://www.sogou.com/web'})
    body = opener.open(req, timeout=timeout).read().decode('utf-8', 'ignore')
    m = (re.search(r'window\.location\.replace\("([^"]+)"\)', body)
         or re.search(r"URL='([^']+)'", body)
         or re.search(r'href="(https?://[^"]+)"', body))
    return m.group(1) if m else None


def _unescape(s):
    from html import unescape
    return unescape(s).strip()
