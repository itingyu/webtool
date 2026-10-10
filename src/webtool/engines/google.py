# -*- coding: utf-8 -*-
"""Google 引擎: Web HTML 优先 (需代理), news RSS 降级, 结果带 quality 标注

2026-10 实测: 数据中心代理出口 IP 对 www.google.com/search 触发 IP 级
reCAPTCHA (429 + 'unusual traffic', consent cookie/TLD/参数变体均无效,
纯 HTTP 不可解) — 429 时自动降级 news.google.com RSS (同 IP 全端点 200,
跳转链需浏览器打开, 靠 title 内 source 后缀供二次定位)。

v1.6: web 通道改走 transport 统一指纹 (此前 urllib 指纹是 DC 出口被秒 429
的帮凶之一, 值得用 chrome 指纹重测); consent cookie (SOCS) 预置排除欧盟
同意墙变量; 冷却记忆持久化 (state)。

news RSS 是新闻检索不是全 Web 搜索:
- 结果带 channel='news' 标注, 消费方 (agent) 可据此判断覆盖面
- 支持 when: 相对时间窗 (Web 语义下默认 1y, 避免被旧闻淹没)
- 直搜语义可用 (LMArena/Artificial Analysis 等高相关命中)
"""
import re
import urllib.parse

from .. import captcha, transport

_BATCH_URL = 'https://news.google.com/_/DotsSplashUi/data/batchexecute'


def search(query, max_results=10, proxy=None, timeout=15, market='zh-CN', page=1):
    """google 通道: 有代理 → web(常被IP级reCAPTCHA拦)→news RSS 自动降级;
    无代理 → news RSS 直连 (国内网络通常不可达, 报错带处置建议)

    代理优先级: engine_proxy.google > 全局 proxy. 2026-10-10 实测:
    web 端点即使 chrome131 指纹+SOCS+udm14 也全量 429 (reCAPTCHA Enterprise,
    IP 级, 纯HTTP无解) — news RSS 通道是主力, 结果标 channel=news,
    news.google.com 文章链经 batchexecute 自动还原真实 URL.
    """
    if proxy:
        if captcha.suspended('google'):
            pass  # 冷却期内不再试 web, 直接 news (news 不受 /search 风控影响)
        else:
            try:
                return _web(query, max_results, proxy, timeout, market, page)
            except transport.BlockedError:
                # transport 降级梯 3 跳全撞 reCAPTCHA (IP 级, 指纹无解) → news
                # (冷却门不再 raise: web 与 news 共挂 'google' 名, web 被拦
                #  不该把 news 也锁死 — 直接降级, news 自己的请求不受 /search 风控)
                return _news(query, max_results, proxy, timeout, market, page)
            except RuntimeError as e:
                # IP 级反爬特征时降级 news (错误串含状态码/unusual/sorry)
                s = str(e)
                if not ('429' in s or 'unusual' in s or '/sorry/' in s
                        or '403' in s):
                    raise
    # 无代理或 web 被封: news RSS (国内直连可达性差但配了代理就能通,
    # gnews 域名不在 /search 的限流范围内)
    return _news(query, max_results, proxy, timeout, market, page)


# ---------- Web HTML ----------

def _web(query, max_results, proxy, timeout, market, page):
    if not proxy:
        raise RuntimeError('google web 需要代理')
    q = urllib.parse.quote(query)
    num = min(max_results, 20)
    start = (page - 1) * 10 + 1
    hl, gl = ('zh-CN', 'CN') if market.startswith('zh') else ('en-US', 'US')
    url = (f'https://www.google.com/search?q={q}&num={num}&start={start}'
           f'&hl={hl}&gl={gl}&pws=0&udm=14')
    # SOCS consent cookie: 排除欧盟同意墙变量 (CAISHAgB 即"拒绝全部"的骨架值)
    extra = {'Cookie': 'SOCS=CAISHAgBEhJnd3NfMjAyMzAxMjQtMF9SQzIaAmVuIAEgBkgB'}
    text, status, via = transport.get(
        url, kind='nav', referer='https://www.google.com/', proxy=proxy,
        timeout=timeout, engine='google', allow_fallback=False, headers=extra,
        lang=transport.LANG_EN)
    if status in (429, 403) or 'unusual traffic' in text or '/sorry/' in text:
        # 不在此处 mark_blocked: google 冷却 300s×min(hits,4) 指数加长,
        # 梯内+上层各记一次会瞬间堆到 1200s, 把 news 通道也锁死 (共享 engine 名)
        # 先试纯 HTTP 攻坚挑战 (gcaptcha: anchor token + sorry 表单回填)
        try:
            from . import gcaptcha as _gc
            if _gc.is_challenge(text, status=status) or '/sorry/' in text:
                ok2, text2, how = _gc.solve(session, text, str(session.baseurl if hasattr(session, 'baseurl') else 'https://www.google.com/sorry/'), timeout=timeout)
                if ok2:
                    captcha.mark_ok('google')
                    return text2, status
        except Exception:
            pass
        raise RuntimeError(f'google web IP级反爬({status}), 已降级/冷却'
                           f'{captcha.cooldown_left("google")}s')

    anchors = re.findall(
        r'<a\b[^>]*href="(/url\?[^"]*|https?://[^"]*)"[^>]*>(.*?)</a>', text, re.S)
    out, seen = [], set()
    for href, inner in anchors:
        u = _real_url(href)
        if not u:
            continue
        h3 = re.search(r'<h3\b[^>]*>(.*?)</h3>', inner, re.S)
        if not h3:
            continue
        title = _text(h3.group(1))
        if not title or u in seen:
            continue
        seen.add(u)
        out.append({'rank': 0, 'title': title, 'url': u, 'snippet': ''})
        if len(out) >= max_results:
            break
    _attach_snippets(text, out)
    for i, r in enumerate(out):
        r['rank'] = i + 1
    if not out:
        raise RuntimeError(f'google web 解析 0 条 (status={status}, 可能改版)')
    captcha.mark_ok('google')
    return out


def _real_url(href):
    if href.startswith('/url?'):
        m = _URL_RE.search(href)
        if not m:
            return None
        href = urllib.parse.unquote(m.group(1))
    if href.startswith('//'):
        href = 'https:' + href
    if not href.startswith('http'):
        return None
    host = urllib.parse.urlparse(href).netloc
    if host.split(':')[0] in _GOOGLE_HOSTS:
        return None
    return href


_GOOGLE_HOSTS = ('www.google.com', 'google.com', 'accounts.google.com',
                 'support.google.com', 'policies.google.com',
                 'maps.google.com', 'news.google.com', 'books.google.com')

_URL_RE = re.compile(r'/url\?(?:[^&]*&)*q=(https?%3A[^&"]+)')


def _attach_snippets(html, out):
    blocks = re.findall(r'class="VwiC3b[^"]*"[^>]*>(.*?)</div>', html, re.S)
    for r, b in zip(out, blocks):
        r['snippet'] = _text(b)[:300]


def _text(s):
    s = re.sub(r'<[^>]+>', '', s or '')
    from html import unescape
    return unescape(s).strip()


# ---------- news RSS 降级 ----------

def _news(query, max_results, proxy, timeout, market, page):
    lang, gl, ceid = _market(market)
    q = urllib.parse.quote(query)
    # Web 语义借道新闻检索: 默认 1 年窗口, 翻页映射 start→offset
    offset = (page - 1) * max_results
    when = 'when:1y'
    url = (f'https://news.google.com/rss/search?q={q}+{when}'
           f'&hl={lang}&gl={gl}&ceid={gl}:{ceid}')
    # RSS 用持久会话 (chrome 指纹 + cookie 预热): 首页领 NID 再拉 RSS,
    # 会话跨调用 state 持久化; 裸请求部分代理出口会被 302 challenge
    text = None
    try:
        s, p = transport._new_session('chrome131_win', proxy, 'google')
        try:
            transport.session_get('https://news.google.com/', s, kind='nav',
                                  timeout=timeout, profile=p)
        except Exception:
            pass                                  # 预热失败不致命, RSS 照打
        rss_url = url
        text, status = transport.session_get(rss_url, s, kind='plain',
                                             timeout=timeout, profile=p)
        transport._persist_cookies(s, 'google')
        if status != 200 or '<item>' not in text:
            text = None
    except Exception:
        text = None
    if text is None:
        # urllib 兜底 (transport 指纹通道异常时)
        text, status, _via = transport.get(url, kind='plain', proxy=proxy,
                                           timeout=timeout, engine=None)
    items = re.findall(r'<item>(.*?)</item>', text, re.S)
    out = []
    for it in items[offset:offset + max_results]:
        t = re.search(r'<title>(.*?)</title>', it, re.S)
        l = re.search(r'<link>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</link>', it, re.S)
        d = re.search(r'<pubDate>(.*?)</pubDate>', it, re.S)
        src = re.search(r'<source[^>]*>(.*?)</source>', it, re.S)
        title = _unescape(t.group(1)) if t else ''
        if not title:
            continue
        out.append({'rank': len(out) + 1, 'title': title.strip(),
                    'url': (l.group(1).strip() if l else ''),
                    'snippet': (src.group(1).strip() + ' · ' if src else '')
                               + (d.group(1).strip() if d else ''),
                    'source': src.group(1).strip() if src else '',
                    'date': (d.group(1).strip() if d else ''),
                    'channel': 'news'})
    # 无新闻覆盖不算错误: 返回空列表, 上层自然跳过该引擎贡献
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


def resolve_link(url, proxy=None, timeout=10):
    """跳转链还原: /url?q= 老式内链直接解; news.google.com/articles
    走 gnews batchexecute 解码 (纯 HTTP, 带缓存+熔断); 失败原样返回"""
    if 'news.google.com/rss/articles/' in url or 'news.google.com/articles/' in url:
        from . import gnews
        return gnews.decode(url, proxy=proxy, timeout=timeout) or url
    if 'google.com/url' not in url:
        return url
    m = _URL_RE.search(url)
    if m:
        return urllib.parse.unquote(m.group(1))
    return url
