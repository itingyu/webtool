# -*- coding: utf-8 -*-
"""搜狗搜索引擎: 中文内容覆盖好

通道策略 (PC 优先, 双端全指纹):
1. PC 主力 (www.sogou.com/web): chrome131 Win 指纹 + state 持久 cookie
   (SUID/SNUID 回头客会话) + 导航预热 + 换会话梯度重试; PC 版结果带摘要
2. PC 兜底: urllib 全套显式指纹会话
3. 移动端 (m.sogou.com): Android 指纹 — 2026-10-10 实测 PC 端对 DC/无历史
   IP 会随机弹 antispider 滑块 (5384B 固定页), 移动端风控显著更松, 且结果
   href 的 url= 参数直出真实地址, 无需二次跳转解析; 缺点是移动端无摘要

实测注意 (2026-10-10, 数据中心 IP):
- PC 端已对无历史 IP 常态 403 (nginx 硬拦), 移动端随机弹滑块, IP 频繁连打
  后全站记名 (PC 403 + m 站滑块), 数分钟后逐步解封 — IP 信誉问题, 非代码
  问题; 住宅 IP / 低频使用下 PC 通道是主力
- 被拦处置: captcha 冷却 (state 持久化) + 换新会话/新指纹重试
"""
import re
import time
import urllib.parse
import urllib.request

from .. import captcha, transport
from ..http import build_opener

ENDPOINT = 'https://www.sogou.com/web'
SOUGOU = 'https://www.sogou.com'
M_ENDPOINT = 'https://m.sogou.com/web/searchList.jsp'
M_HOME = 'https://m.sogou.com/'


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def search(query, max_results=10, proxy=None, timeout=15, market=None,
           _session=None):
    """PC 优先 (带摘要) → PC urllib 兜底 → 移动端 (直出真实 URL)"""
    q = urllib.parse.quote(query)
    sign = None

    # ---- 1) PC 主力: curl_cffi chrome131 指纹, 两次会话机会 ----
    html = None
    for attempt in range(2):
        html, sign = _pc_cffi(q, proxy, timeout)
        if html:
            break
        time.sleep(1.2 + attempt)
    # ---- 2) PC 兜底: urllib 全指纹会话 ----
    if not html:
        html, sign = _pc_urllib(q, timeout)
    # ---- 3) PC 命中 → 解析 (vr-title, 带摘要) ----
    if html:
        captcha.mark_ok('sogou')
        return _parse_pc(html, max_results)

    # ---- 4) PC 全拦 → 移动端 (两轮会话, 中途 PC 冷却不影响移动通道) ----
    for attempt in range(2):
        out = _mobile_search(q, max_results, proxy, timeout)
        if out:
            return out
        time.sleep(1.5 + attempt)

    cd = captcha.cooldown_left('sogou')
    raise RuntimeError(f'sogou 反爬拦截({sign or "unknown"}); '
                       f'PC+移动双通道均被拦, 冷却{cd}s, 请换 -e bing,baidu')


# ---------------- PC 主力 (curl_cffi) ----------------

def _pc_cffi(q, proxy, timeout):
    """持久 cookie 会话 + 导航预热; 返回 (html|None, sign|None)"""
    s, p = transport._new_session('chrome131_win', proxy, 'sogou')
    try:
        # 导航预热: 领/刷新 SUID/SNUID (state 预载, 像回头客)
        transport.session_get(SOUGOU + '/', s, kind='nav', timeout=timeout,
                              profile=p)
        text, status = transport.session_get(f'{ENDPOINT}?query={q}', s,
                                             kind='nav', referer=SOUGOU + '/',
                                             timeout=timeout, profile=p)
        transport._persist_cookies(s, 'sogou')
        blocked, sign = captcha.detect('sogou', text)
        if not blocked:
            return text, None
        captcha.mark_blocked('sogou')
        return None, sign
    except Exception as e:
        return None, f'{type(e).__name__}'


def _pc_urllib(q, timeout):
    """urllib 全套显式指纹会话兜底, 换新会话重试一次"""
    sign = None
    for attempt in range(2):
        import http.cookiejar
        cj = http.cookiejar.CookieJar()
        opener = build_opener(None, cj)
        opener.add_handler(_NoRedirect())
        try:
            pre = urllib.request.Request(SOUGOU + '/',
                                         headers=transport.headers_for(
                                             'nav', SOUGOU + '/', full=True))
            opener.open(pre, timeout=timeout)
            req = urllib.request.Request(
                f'{ENDPOINT}?query={q}',
                headers=transport.headers_for('nav', f'{ENDPOINT}?query={q}',
                                              referer=SOUGOU + '/', full=True))
            with opener.open(req, timeout=timeout) as r:
                html = r.read().decode('utf-8', 'ignore')
        except Exception as e:
            sign = f'{type(e).__name__}'
            time.sleep(1.5)
            continue
        blocked, sign = captcha.detect('sogou', html)
        if not blocked:
            return html, None
        captcha.mark_blocked('sogou')
        html = None
        time.sleep(1.5)
    return None, sign


# ---------------- 移动端 (Android 指纹) ----------------

def _mh(profile):
    """移动端基础头: UA + client hints (impersonate 内置的是桌面 UA, 需显式覆盖)"""
    return {'User-Agent': profile['ua'],
            'sec-ch-ua': profile['sec_ch_ua'],
            'sec-ch-ua-mobile': profile['mobile'],
            'sec-ch-ua-platform': profile['platform']}


def _mobile_search(q, max_results, proxy, timeout, _inner=False):
    """m.sogou Android 指纹: 首页预热 → searchList.jsp, url= 参数直出真实地址"""
    prof = transport.PROFILES['chrome131_android']
    base = _mh(prof)
    html = None
    for attempt in range(2):
        try:
            s = transport._cr.Session(impersonate='chrome131',
                                      proxy=proxy or None)
            s.get(M_HOME, timeout=timeout, headers=dict(base))
            if attempt:
                time.sleep(1.2)          # 被拦后换会话稍微喘口气
            r = s.get(f'{M_ENDPOINT}?keyword={q}', timeout=timeout,
                      headers=dict(base, Referer=M_HOME))
            html = r.text
        except Exception:
            html = None
        if html and not captcha.detect('sogou', html)[0] \
                and 'antispider' not in html.lower():
            break
        captcha.mark_blocked('sogou')
        html = None
    if not html:
        return None
    out, seen = [], set()
    for m in re.finditer(r'<h3[^>]*>(.*?)</h3>', html, re.S):
        title = _unescape(re.sub(r'<[^>]+>', '', m.group(1))).strip()
        if not title or '还在搜' in title or '相关搜索' in title:
            continue
        after = html[m.end():m.end() + 1500]
        # url= 参数可能出现在同块任一 href (含视频聚合卡片), 取第一个外链;
        # 排除图片 CDN (qqpublic.qpic.cn / sogoucdn.com / myqcloud.com 头像图)
        for a in re.finditer(r'[?&]url=(https?%3A[^&"\s]+)', after):
            url = urllib.parse.unquote(a.group(1))
            if not url.startswith('http'):
                continue
            host = urllib.parse.urlparse(url).netloc
            if ('sogou' in host or 'qpic.cn' in host or 'qlogo.cn' in host
                    or 'gtimg.com' in host or 'myqcloud.com' in host
                    or re.search(r'\.(jpg|jpeg|png|gif|webp)(\?|$)', url, re.I)):
                continue
            if url in seen:
                continue
            seen.add(url)
            out.append({'rank': len(out) + 1, 'title': title, 'url': url,
                        'snippet': '', 'via_mobile': True})
            break
        if len(out) >= max_results:
            break
    return out


# ---------------- PC 结果解析 ----------------

def _parse_pc(html, max_results):
    items = re.findall(r'<h3 class="vr-title[^"]*"[^>]*>(.*?)</h3>', html, re.S)
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
        out.append({'rank': len(out) + 1, 'title': title, 'url': url,
                    'snippet': ''})
        if len(out) >= max_results:
            break
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
    """把 /link?url=xxx 解析为真实 URL: 需带搜索会话 cookie (state 持久会话优先)"""
    try:
        s, p = transport._new_session('chrome131_win', proxy, 'sogou')
        transport.session_get(SOUGOU + '/', s, kind='nav', timeout=timeout,
                              profile=p)
        text, _ = transport.session_get(
            link_url if link_url.startswith('http') else SOUGOU + link_url,
            s, kind='nav', referer=f'{SOUGOU}/web', timeout=timeout, profile=p)
        transport._persist_cookies(s, 'sogou')
        m = (re.search(r'window\.location\.replace\("([^"]+)"\)', text)
             or re.search(r"URL='([^']+)'", text)
             or re.search(r'href="(https?://[^"]+)"', text))
        if m:
            return m.group(1)
    except Exception:
        pass
    # urllib 兜底
    import http.cookiejar
    cj = http.cookiejar.CookieJar()
    opener = build_opener(None, cj)
    opener.add_handler(_NoRedirect())
    try:
        opener.open(urllib.request.Request(
            SOUGOU + '/', headers=transport.headers_for('nav', SOUGOU + '/',
                                                        full=True)),
            timeout=timeout)
    except Exception:
        pass
    req = urllib.request.Request(
        link_url if link_url.startswith('http') else 'https://www.sogou.com' + link_url,
        headers={'User-Agent': transport.PROFILES['chrome131_win']['ua'],
                 'Referer': f'{SOUGOU}/web'})
    body = opener.open(req, timeout=timeout).read().decode('utf-8', 'ignore')
    m = (re.search(r'window\.location\.replace\("([^"]+)"\)', body)
         or re.search(r"URL='([^']+)'", body)
         or re.search(r'href="(https?://[^"]+)"', body))
    return m.group(1) if m else None


def _unescape(s):
    from html import unescape
    return unescape(s).strip()
