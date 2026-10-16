"""百度搜索: curl_cffi TLS 指纹 + 多步预热 + 验证页处置

urllib 的 JA3 指纹会触发安全验证页, 必须走浏览器指纹。预热: 首页领
BAIDUID → sugrec 行为链 → 带会话 cookie 搜索; result-op 卡片标 is_ad。
"""
import re
import urllib.parse

from webtool.core import text
from webtool.net import intercept, transport

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
    if not out:
        # 静默空返回最坏: 上游给验证码页/壳页时看起来"正常但没结果"。
        # bing/google 都是 raise 交给上层降级, baidu 补齐同款。
        raise RuntimeError(f'baidu 解析 0 条 (len={len(html)}), 疑似验证码页/壳页')
    _resolve_links(out, proxy, timeout)
    intercept.note_ok(intercept.Ctx(engine='baidu', url=url))
    return out


def _get_html(url, proxy, timeout):
    """多步预热 → 搜索 (验证码检测/降级梯/节奏全在 transport.get)"""
    try:
        warm, wprof = transport._new_session('chrome131_win', proxy, 'baidu',
                                           url=url)
        transport.warm_session(warm, BAIDU + '/', profile=wprof, timeout=timeout)
        transport.session_get(f'{BAIDU}/sugrec?prod=pc&wd={urllib.parse.quote("百")}',
                              warm, kind='xhr', referer=BAIDU + '/',
                              profile=wprof, timeout=timeout)
        text, status = transport.session_get(
            url, warm, kind='nav', referer=BAIDU + '/', timeout=timeout)
        # 这条自造会话的路径也要过全部拦截器 (判定 + 记账一次做完)
        hit, _ctx = intercept.gate('baidu', text, url=url)
        if hit is None:
            transport._persist_cookies(warm, 'baidu')
            return text, 'cffi+session'
    except Exception:
        pass
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
    # 百度系子域 (百家号/贴吧/百科) 是合法解出结果; 还停在 www.baidu.com/link 才是失败
    if n == 'www.baidu.com' and '/link' in urllib.parse.urlparse(real).path:
        return None
    # 302 Location 出现非 ASCII 乱码 = token 过期/风控假响应, 当失败处理
    try:
        real.encode('ascii')
    except UnicodeEncodeError:
        return None
    return real


_unescape = text.unescape
