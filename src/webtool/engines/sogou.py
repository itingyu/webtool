# -*- coding: utf-8 -*-
"""搜狗搜索引擎: 中文内容覆盖好, 直连可解析, link 跳转链需二次解析"""
import re
import urllib.parse
import http.cookiejar

from ..http import http_get, build_opener
from .. import captcha

ENDPOINT = 'https://www.sogou.com/web'


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def _new_session():
    cj = http.cookiejar.CookieJar()
    opener = build_opener(None, cj)
    opener.add_handler(_NoRedirect())
    return cj, opener


def search(query, max_results=10, proxy=None, timeout=15, market=None, _session=None):
    """返回 [{title,url,snippet}]  url 可能是 /link?url= 跳转链"""
    if captcha.suspended('sogou'):
        raise RuntimeError(f"sogou 冷却中({captcha.cooldown_left('sogou')}s, 此前触发反爬), 请换引擎: -e bing,baidu")
    cj, opener = _session if _session else _new_session()
    q = urllib.parse.quote(query)
    page = 1
    from ..resilient import fetch as rfetch
    html, status, _via = rfetch(f'{ENDPOINT}?query={q}', proxy=proxy, timeout=timeout)
    # 验证页识别 (统一走 captcha 模块指纹)
    blocked, sign = captcha.detect('sogou', html)
    if blocked:
        captcha.mark_blocked('sogou')
        raise RuntimeError(f'sogou 反爬拦截({sign}); 已冷却{captcha.cooldown_left("sogou")}s, 请换 -e bing,baidu')
    items = re.findall(
        r'<h3 class="vr-title">(?:[^<]|<!--[^>]*-->)*<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
        html, re.S)
    out = []
    for u, t in items[:max_results * 2]:
        title = _unescape(re.sub(r'<[^>]+>', '', t)).strip()
        if not title:
            continue
        url = u if u.startswith('http') else 'https://www.sogou.com' + u
        out.append({'rank': len(out) + 1, 'title': title, 'url': url, 'snippet': ''})
        if len(out) >= max_results:
            break
    captcha.mark_ok('sogou')
    # 附带摘要 (可选字段, 解析失败不影响)
    _fill_snippets(html, out)
    return out


def _fill_snippets(html, out):
    """尽力提取每个结果下方的摘要文本"""
    blocks = re.split(r'<h3 class="vr-title">', html)
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
