# -*- coding: utf-8 -*-
"""百度搜索引擎: TLS 指纹模拟 (curl_cffi) + 多步预热 + 验证页处置

核心突破 (2026-10-09 实测): python-urllib 的 TLS 握手指纹(JA3)被百度识别,
即使完整 cookie+Referer 也会弹安全验证页 (1438B)。用 curl_cffi 的
impersonate='chrome' 模拟 Chrome 完整 TLS/JA3/HTTP2 指纹后:
- Session 首页领 cookie 后搜索: 5/5 成功率 (多 query 连续验证)

多步预热 (浏览器形态, transport 层统一管理指纹/cookie/节奏/降级梯):
1. GET 首页领 BAIDUID/BAIDUID_BFESS (+ state 持久化, 回头客会话是信任信号)
2. GET sugrec 联想词接口 — 浏览器输入时真实调用的 XHR, 让服务端看到
   "输入→联想→搜索" 的完整行为链
3. 带 Referer/完整导航头 GET /s

链接解析: <h3 title><a href="baidu.com/link?url=.."> → 302 Location
广告: result-op 聚合卡片 → is_ad=True
"""
import re
import time
import urllib.parse

from .. import captcha, transport

BAIDU = 'https://www.baidu.com'


def search(query, max_results=10, proxy=None, timeout=15, market=None, page=1):
    q = urllib.parse.quote(query)
    first = (page - 1) * max_results + 1
    url = (f'{BAIDU}/s?wd={q}&rn={max_results}&pn={first - 1}'
           f'&ie=utf-8&rsv_dl=pc_search&rsv_enter=1')
    html, via = _get_html(url, proxy, timeout)
    out = []
    seen = set()
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
        u = real or jump
        if u in seen:
            continue
        seen.add(u)
        out.append({'rank': len(out) + 1, 'title': title,
                    'url': u, 'snippet': _snippet(seg),
                    'is_ad': is_ad, 'resolved': bool(real)})
        if len(out) >= max_results:
            break
    _resolve_links(out, proxy, timeout)
    captcha.mark_ok('baidu')
    return out


def _get_html(url, proxy, timeout):
    """多步预热 → 搜索 (验证码检测/降级梯/节奏全在 transport.get)"""
    # 步骤1+2: 首页领 cookie + sugrec 行为链预热 (失败不致命, 继续搜)
    try:
        warm = transport._cr.Session(
            impersonate=transport.PROFILES['chrome131_win']['impersonate'],
            proxy=proxy or None)
        warm.get(BAIDU + '/', timeout=timeout)
        warm.get(f'{BAIDU}/sugrec?prod=pc&wd={urllib.parse.quote("百")}',
                 timeout=timeout)
        # 步骤3: 带着会话 cookie 搜索
        text, status = transport.session_get(
            url, warm, kind='nav', referer=BAIDU + '/', timeout=timeout)
        blocked, _ = captcha.detect('baidu', text)
        if not blocked:
            captcha.mark_ok('baidu')
            transport._persist_cookies(warm, 'baidu')
            return text, 'cffi+session'
        captcha.mark_blocked('baidu')
    except Exception:
        pass
    # 兜底: transport 统一通道 (含降级梯)
    text, _status, via = transport.get(url, kind='nav', referer=BAIDU + '/',
                                       proxy=proxy, timeout=timeout,
                                       engine='baidu')
    return text, via


def _snippet(seg):
    """摘要: 新版 cosc 卡片 (2026) 直接捞长文本节点; 兼容老 c-abstract"""
    seg = re.sub(r'<script[^>]*>.*?</script>', '', seg, flags=re.S)
    ab = (re.search(r'class="c-abstract[^"]*"[^>]*>(.*?)</div>', seg, re.S)
          or re.search(r'class="[^"]*content-right[^"]*"[^>]*>(.*?)</(?:div|span)>', seg, re.S))
    if ab:
        return _unescape(re.sub(r'<[^>]+>', '', ab.group(1))).strip()[:300]
    # 新版: 块内最长纯文本节点即摘要 (标题/来源都在 40 字以内, 摘要更长)
    cands = re.findall(r'>([^<>{}]{40,200})<', seg)
    if cands:
        return _unescape(max(cands, key=len)).strip()[:300]
    return ''


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
    real = transport.resolve_redirect(link, referer=BAIDU + '/',
                                      proxy=proxy, timeout=timeout)
    if not real:
        return None
    n = urllib.parse.urlparse(real).netloc.lower()
    # 真目标在百度系子域 (百家号/贴吧/知道/百科) 是合法解出结果 — 不能按
    # 'baidu.com in netloc' 误杀; 只有「还停在 www.baidu.com/link」= 没跳走 = 失败
    if n == 'www.baidu.com' and '/link' in urllib.parse.urlparse(real).path:
        return None
    # 302 Location 出现非 ASCII 乱码 = token 过期/风控假响应, 当失败处理
    try:
        real.encode('ascii')
    except UnicodeEncodeError:
        return None
    return real


def _unescape(s):
    from html import unescape
    return unescape(s or '').strip()
