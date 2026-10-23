"""Google 引擎: Web HTML 优先 (需代理), news RSS 降级, 结果带 quality 标注

数据中心代理出口 IP 对 www.google.com/search 会触发 IP 级 reCAPTCHA
(429 + 'unusual traffic', consent cookie/TLD/参数变体均无效, 纯 HTTP 不可解)
— 429 时自动降级 news.google.com RSS (同 IP 全端点 200, 跳转链需浏览器
打开, 靠 title 内 source 后缀供二次定位)。

web 通道走 transport 统一指纹; consent cookie (SOCS) 预置排除欧盟同意墙
变量; 冷却记忆持久化 (state)。

news RSS 是新闻检索不是全 Web 搜索:
- 结果带 channel='news' 标注, 消费方 (agent) 可据此判断覆盖面
- 支持 when: 相对时间窗 (Web 语义下默认 1y, 避免被旧闻淹没)
- 直搜语义可用 (LMArena/Artificial Analysis 等高相关命中)
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
    """google 通道: 有代理 → web(常被IP级reCAPTCHA拦)→news RSS 自动降级;
    无代理 → news RSS 直连 (国内网络通常不可达, 报错带处置建议)

    线路由规则表定 (全局 proxy 只决定用哪条代理). web 端点即使 chrome131
    指纹+SOCS+udm14 也大概率被 IP 级 reCAPTCHA 拦 (纯 HTTP 无解) —
    news RSS 通道是主力, 结果标 channel=news, news.google.com 文章链经
    batchexecute 自动还原真实 URL.
    """
    _LAST.update(channel=None, degraded_from=None, reason=None)
    if proxy:
        _cool = intercept.cooldown_of('https://www.google.com/search')
        if _cool is not None:
            # 冷却期内不再试 web, 直接 news (谁封的、封多久由插件说)
            _LAST.update(channel='news', degraded_from='web',
                         reason=f'web 端点{_cool.why}冷却中({_cool.left}s), 跳过')
        else:
            try:
                out = _web(query, max_results, proxy, timeout, market, page,
                           since=since, until=until)
                _LAST.update(channel='web')
                return out
            except transport.BlockedError as e:
                # transport 降级梯 3 跳全撞 reCAPTCHA (IP 级, 指纹无解) → news
                # 冷却按站点记账: web 是 www.google.com, news 是 news.google.com,
                # 两个站各记各的 — web 被拦不会锁死 news
                _LAST.update(channel='news', degraded_from='web', reason=str(e)[:120])
            except RuntimeError as e:
                # IP 级反爬特征时降级 news (错误串含状态码/unusual/sorry);
                # enablejs 壳页 (200 但要求 JS) 同样是风控信号, 一并降级
                s = str(e)
                if not ('429' in s or 'unusual' in s or '/sorry/' in s
                        or '403' in s or 'enablejs' in s):
                    raise
                _LAST.update(channel='news', degraded_from='web', reason=s[:120])
    # 无代理或 web 被封: news RSS (国内直连可达性差但配了代理就能通,
    # gnews 域名不在 /search 的限流范围内)
    if _LAST['channel'] is None:
        _LAST.update(channel='news', degraded_from='web',
                     reason='未配代理, web 端点不可达' if not proxy else None)
    return _news(query, max_results, proxy, timeout, market, page,
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


# news RSS 降级

def _time_qs(since, until):
    """Google 自定义区间: tbs=cdr:1,cd_min:M/D/YYYY,cd_max:M/D/YYYY"""
    if not since and not until:
        return ''
    import datetime as _dt
    from webtool.core.datewindow import gfmt
    lo = gfmt(since or _dt.date(1990, 1, 1))
    hi = gfmt(until or _dt.date.today())
    return '&' + urllib.parse.urlencode({'tbs': f'cdr:1,cd_min:{lo},cd_max:{hi}'})


def _news(query, max_results, proxy, timeout, market, page,
          since=None, until=None):
    lang, gl, ceid = _market(market)
    # Web 语义借道新闻检索: 默认 1 年窗口, 翻页映射 start→offset
    offset = (page - 1) * max_results
    extra = ''
    if since:
        extra += f' after:{since.isoformat()}'
    if until:
        extra += f' before:{until.isoformat()}'
    when = '' if extra else 'when:1y'
    q = urllib.parse.quote(query + extra)
    url = (f'https://news.google.com/rss/search?q={q}'
           + (f'+{when}' if when else '')
           + f'&hl={lang}&gl={gl}&ceid={gl}:{ceid}')
    # RSS 用持久会话 (chrome 指纹 + cookie 预热): 首页领 NID 再拉 RSS,
    # 会话跨调用 state 持久化; 裸请求部分代理出口会被 302 challenge
    text = None
    rss_url = url
    try:
        s, p = transport._new_session('chrome131_win', proxy, 'google',
                                      url=rss_url)
        # 预热失败不致命, RSS 照打
        transport.warm_session(s, 'https://news.google.com/', timeout=timeout,
                               profile=p)
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


_unescape = text.unescape


def resolve_link(url, proxy=None, timeout=10):
    """跳转链还原: /url?q= 老式内链直接解; news.google.com/articles
    走 gnews batchexecute 解码 (纯 HTTP, 带缓存+熔断)

    解不出来返回 None (**不返回原链**): 调用方据此判定"没解出来"。返回原链会被
    上层当成解码成功写进缓存, 一次失败即永久失败。
    """
    if 'news.google.com/rss/articles/' in url or 'news.google.com/articles/' in url:
        from webtool.engines import gnews
        return gnews.decode(url, proxy=proxy, timeout=timeout)
    if 'google.com/url' not in url:
        return None                     # 非跳转链, 无需解码
    m = _URL_RE.search(url)
    if m:
        return urllib.parse.unquote(m.group(1))
    return None
