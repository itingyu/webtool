"""Google 引擎: 仅 Web HTML 通道 (需代理), 结果带 quality 标注

数据中心代理出口 IP 对 www.google.com/search 会触发 IP 级 reCAPTCHA
(429 + 'unusual traffic', consent cookie/TLD/参数变体均无效, 纯 HTTP 不可解)。
news RSS 降级通道已移除: 新闻检索不是 Web 搜索, 宁可报错也不拿新闻冒充结果。

web 通道走 transport 统一指纹; consent cookie (SOCS) 预置排除欧盟同意墙
变量; 冷却记忆持久化 (state)。
"""
import re
import urllib.parse

from webtool.core import text
from webtool.net import intercept, transport

_BATCH_URL = 'https://news.google.com/_/DotsSplashUi/data/batchexecute'

# 上一次 search 实际走的通道 (web / news) + 降级原因。
# 降级是静默的 (429 被 catch 后直接换通道, 不进 errors), 消费方无法从结果反推
# "这批到底是全 Web 搜索还是新闻检索" —— 这里如实上报, 由 search 汇总输出。
_LAST = {'channel': None, 'degraded_from': None, 'reason': None}


def last_channel():
    """返回上一次 search 的通道信息 (副本): {'channel','degraded_from','reason'}"""
    return dict(_LAST)


def search(query, max_results=10, proxy=None, timeout=15, market='zh-CN', page=1,
           since=None, until=None):
    """google 通道: 仅 Web HTML (需代理); news RSS 降级通道已移除

    web 端点即使 chrome131 指纹 + udm14 也可能被 IP 级 reCAPTCHA 拦;
    被拦或无代理就直接报错, 不再退回新闻 RSS —— 那是新闻检索不是 Web 搜索,
    且会把索引时间当发布时间。
    """
    _LAST.update(channel='web', degraded_from=None, reason=None)
    if not proxy:
        raise RuntimeError('google 需要代理 (news RSS 通道已停用, 无代理无结果)')
    _cool = intercept.cooldown_of('https://www.google.com/search')
    if _cool is not None:
        raise RuntimeError(f'google web 端点{_cool.why}冷却中({_cool.left}s)')
    return _web(query, max_results, proxy, timeout, market, page,
                since=since, until=until)


# Web HTML

def _web(query, max_results, proxy, timeout, market, page,
         since=None, until=None):
    if not proxy:
        raise RuntimeError('google web 需要代理')
    q = urllib.parse.quote(query)
    num = min(max_results, 20)
    start = (page - 1) * 10 + 1
    hl, gl = ('zh-CN', 'CN') if market.startswith('zh') else ('en-US', 'US')
    url = (f'https://www.google.com/search?q={q}&num={num}&start={start}'
           f'&hl={hl}&gl={gl}&pws=0&udm=14')
    url += _time_qs(since, until)
    # SOCS consent cookie: 排除欧盟同意墙变量 (CAISHAgB 即"拒绝全部"的骨架值)
    extra = {'Cookie': 'SOCS=CAISHAgBEhJnd3NfMjAyMzAxMjQtMF9SQzIaAmVuIAEgBkgB'}
    text, status, via = transport.get(
        url, kind='nav', referer='https://www.google.com/', proxy=proxy,
        timeout=timeout, engine='google', headers=extra,
        lang=transport.LANG_EN)
    if status in (429, 403) or 'unusual traffic' in text or '/sorry/' in text:
        # 不在此处 mark_blocked: 冷却从 30s 起、×min(hits,4) 指数加长,
        # 梯内+上层各记一次会翻倍到 2 分钟 —— 没必要, 判定的插件已经记过了
        # 先试纯 HTTP 攻坚挑战 (gcaptcha: anchor token + sorry 表单回填)
        try:
            from webtool.engines import gcaptcha as _gc
            if _gc.is_challenge(text, status=status) or '/sorry/' in text:
                gs, gp = transport._new_session(
                    'chrome131_win', proxy, 'google',
                    url='https://www.google.com/sorry/')
                try:
                    ok2, text2, how = _gc.solve(gs, text, 'https://www.google.com/sorry/', timeout=timeout)
                finally:
                    try:
                        gs.close()
                    except Exception:
                        pass
                if ok2:
                    intercept.note_ok(intercept.Ctx(engine='google', url=url))
                    return text2, status
        except Exception:
            pass
        _cool2 = intercept.cooldown_of('https://www.google.com/search')
        raise RuntimeError(f'google web IP级反爬({status}), 已降级/冷却'
                           f'{_cool2.left if _cool2 else 0}s')

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
        raise RuntimeError(f'google web 解析 0 条 (status={status}, '
                           f'{"enablejs壳页" if "enablejs" in text[:2000] else "可能改版"})')
    intercept.note_ok(intercept.Ctx(engine='google', url=url))
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


_text = text.plain


# 时间参数

def _time_qs(since, until):
    """Google 自定义区间: tbs=cdr:1,cd_min:M/D/YYYY,cd_max:M/D/YYYY"""
    if not since and not until:
        return ''
    import datetime as _dt
    from webtool.core.datewindow import gfmt
    lo = gfmt(since or _dt.date(1990, 1, 1))
    hi = gfmt(until or _dt.date.today())
    return '&' + urllib.parse.urlencode({'tbs': f'cdr:1,cd_min:{lo},cd_max:{hi}'})


def resolve_link(url, proxy=None, timeout=10):
    """跳转链还原: /url?q= 老式内链直接解

    解不出来返回 None (**不返回原链**): 调用方据此判定"没解出来"。返回原链会被
    上层当成解码成功写进缓存, 一次失败即永久失败。
    """
    if 'google.com/url' not in url:
        return None                     # 非跳转链, 无需解码
    m = _URL_RE.search(url)
    if m:
        return urllib.parse.unquote(m.group(1))
    return None
