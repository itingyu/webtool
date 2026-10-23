"""Bing 搜索引擎: curl_cffi chrome 指纹 HTML 通道

通道对比:
- urllib (HTTP/1.1 + Python TLS 指纹) 直连: 排序与浏览器主页不同, 走代理
  (www.bing.com 国外出口) 更是给出知乎/CSDN 提前的旧索引序
- curl_cffi chrome 指纹直连 cn.bing.com: 排序与浏览器主页一致, 低频连打
  未触发风控
- 走代理访问 www.bing.com 会拿到国外版 www 内链页 → 恒直连

域名随线路走: 直连用 cn.bing.com, 走代理用 www.bing.com —— 这是 bing 的**站点
行为** (两个域名给不同索引序), 不是出网策略。线路本身仍由 netx.resolve_proxy
按配置 + 路由表决定, 本模块不判断、也不降级换线。

RSS 通道保留为兜底 (curl_cffi 被限流时), 仅在 HTML 失败时使用。实测它
(1) 最多 8 条, count/first 都不生效; (2) 忽略时间过滤参数; (3) pubDate 是
抓取/索引时间而非发布时间; (4) 多数 query 与 HTML 同序同结果。
"""
import email.utils
import re
import time
import urllib.parse

from webtool.core import text
from webtool.net import intercept, transport

_CN_ENDPOINT = 'https://cn.bing.com'   # 直连线路的站点端点, 供 search 解析 auto 用


def search(query, max_results=10, proxy=None, timeout=15, market='zh-CN', page=1,
           since=None, until=None):
    """返回 [{title,url,snippet}]; chrome指纹 HTML → urllib HTML → RSS 三级降级"""
    # 归一一次: 'auto' 要问路由表才知道走不走代理, 而下面的 _host() 和
    # _new_session() 都要**实际线路**才能定 (www vs cn、要不要挂代理)。
    # 'auto' 原样往下传会让 _host 以为走代理、_new_session 却是直连 ——
    # 两者必须来自同一次决策。
    from webtool.net import netx
    route = netx.resolve_proxy(proxy, _CN_ENDPOINT + '/search')
    try:
        return _cffi_html(query, max_results, route, timeout, market, page,
                          since=since, until=until)
    except transport.CooldownError:
        raise
    except Exception:
        pass
    try:
        return _urllib_html(query, max_results, route, timeout, market, page,
                            since=since, until=until)
    except Exception:
        pass
    return _rss(query, max_results, route, timeout, market, page,
                since=since, until=until)


def _time_qs(since, until):
    """Bing 自定义区间: filters=ex1:"ez5_MM/DD/YYYY_MM/DD/YYYY"

    只给一端时另一端补 1990-01-01 / 今天。
    """
    if not since and not until:
        return ''
    import datetime as _dt
    from webtool.core.datewindow import gfmt
    lo = gfmt(since or _dt.date(1990, 1, 1))
    hi = gfmt(until or _dt.date.today())
    return '&filters=' + urllib.parse.quote(f'ex1:"ez5_{lo}_{hi}"', safe='')


def _host(proxy):
    """出口线路 → 域名: 走代理用 www.bing.com, 直连用 cn.bing.com。

    这里接的是**已归一**的线路 (None 或代理 URL), 不是 'auto'。
    """
    return 'www.bing.com' if proxy else 'cn.bing.com'


def _cffi_html(query, max_results, proxy, timeout, market, page,
               since=None, until=None):
    """curl_cffi chrome 指纹 (TLS/HTTP2 与浏览器一致)"""
    q = urllib.parse.quote(query)
    first = (page - 1) * max_results + 1
    count = min(max_results, 30)
    base = f'https://{_host(proxy)}'
    url = (f'{base}/search?q={q}&count={count}&first={first}'
           f'&setmkt={urllib.parse.quote(market)}')
    url += _time_qs(since, until)
    # 线路照传 (归一已在上游做完): 写死 None 等于无视用户配的代理, 主机名
    # 换成了 www 却不挂代理, 出口 IP 与域名对不上, 拿到的还是国外版重排。
    # 补 `or 'direct'`: 上游归一出的 None 是"直连"的**结论**, 不是"没表态" ——
    # 直接回传 None 会被 netx 当成 'auto' 再问一遍规则表 (多问一次, 且以另一个
    # URL 问, 规则按 path/port 写时可能翻案)。'direct' 才幂等。
    s, p = transport._new_session('chrome131_win', proxy or 'direct', 'bing', url=url)
    # 首页预热: 领会话 cookie + 让服务端看到导航行为 (公共通道, 指纹与搜索请求同源)
    transport.warm_session(s, base + '/', timeout=timeout, profile=p)
    r = s.get(url, timeout=timeout,
              headers=transport.headers_for('nav', url, referer=base + '/',
                                            profile=p))
    if r.status_code in (429, 403) or 'challenge-form' in r.text:
        _hit, _ctx = intercept.gate(r.text, url=url,
                                   status=r.status_code)
        raise RuntimeError(f'bing cffi 被风控 ({r.status_code})')
    transport._persist_cookies(s, 'bing')
    out = _parse_html(r.text, max_results)
    if not out:
        raise RuntimeError(f'bing cffi 解析 0 条 (len={len(r.text)})')
    intercept.note_ok(intercept.Ctx(engine='bing', url=url))
    return out


def _urllib_html(query, max_results, proxy, timeout, market, page,
                 since=None, until=None):
    """urllib HTML 兜底"""
    q = urllib.parse.quote(query)
    first = (page - 1) * max_results + 1
    count = max_results if max_results <= 30 else 30
    mkt = f'&mkt={urllib.parse.quote(market)}' if market else ''
    url = (f'https://{_host(proxy)}/search?q={q}&count={count}&first={first}'
           f'&setlang={market.split("-")[0]}{mkt}')
    url += _time_qs(since, until)
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
    """单线路取数 (HTML / RSS 两级降级都用它)

    单线路: 代理挂了不悄悄直连 —— 走代理的目标会变成直连超时, 而直连能通的
    目标又会被"降级"成功, 状态永远说不清走的是哪条线。线路由路由表一次决定。

    出网走 net.transport 的 urllib 底层 (via='urllib'): 这条兜底的存在意义就是
    换一套 HTTP/TLS 栈, 但代理、证书、密码补全仍归那一层 —— 否则 bing 的兜底
    会自成一套线路判断。headers 已由调用方按 full=True 拼好, 这里 raw 透传。

    `proxy or 'direct'`: 传进来的是上游已归一的**结论** (None = 直连)。回传 None
    会被 netx 当 'auto' 重问规则表, 传 'direct' 才表示"已决策, 别再问"。
    """
    from webtool.net import transport
    try:
        r = transport.request('GET', url, proxy=proxy or 'direct', timeout=timeout,
                              headers=headers, raw_headers=True, via='urllib')
        return r.text, r.status_code, 'direct' if not proxy else 'proxy'
    except Exception as e:
        raise RuntimeError(f'{url} failed: {e}') from e


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


def _rss_date(s):
    """RSS pubDate → YYYY-MM-DD; bing 的中文本地化格式也能认 ("周五, 23 10月 2026 ...")"""
    s = (s or '').strip()
    if not s:
        return ''
    try:
        return email.utils.parsedate_to_datetime(s).date().isoformat()
    except (TypeError, ValueError):
        pass
    m = re.search(r'(\d{4})-(\d{2})-(\d{2})', s)                    # 2026-10-23
    if m:
        return m.group(0)
    m = re.search(r'(\d{1,2})\s+(\d{1,2})月\s+(\d{4})', s)          # 23 10月 2026
    if m:
        return f'{int(m.group(3)):04d}-{int(m.group(2)):02d}-{int(m.group(1)):02d}'
    if m:
        return f'{int(m.group(3)):04d}-{int(m.group(2)):02d}-{int(m.group(1)):02d}'
    m = re.search(r'(\d{1,2})\s+([A-Za-z]{3})[a-z]*\s+(\d{4})', s)  # 23 Oct 2026
    if m:
        try:
            mon = time.strptime(m.group(2).title(), '%b').tm_mon
            return f'{int(m.group(3)):04d}-{mon:02d}-{int(m.group(1)):02d}'
        except ValueError:
            return ''
    return ''

def _rss(query, max_results, proxy, timeout, market, page,
         since=None, until=None):
    """RSS 兜底: 最多 8 条, 忽略翻页与时间参数; pubDate 为索引时间 (打 date_src=index)"""
    q = urllib.parse.quote(query)
    first = (page - 1) * max_results + 1
    url = (f'https://{_host(proxy)}/search?q={q}&format=rss&count={max_results}'
           f'&first={first}&setmkt={urllib.parse.quote(market)}')
    url += _time_qs(since, until)
    h = transport.headers_for('nav', url, referer=f'https://{_host(proxy)}/',
                              full=True)
    xml, status, _via = _resilient(url, proxy=proxy, timeout=timeout, headers=h)
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
        pd = re.search(r'<pubDate>(.*?)</pubDate>', it, re.S)
        iso = _rss_date(pd.group(1)) if pd else ''
        rec = {'rank': len(out) + 1, 'title': title, 'url': link,
               'snippet': _unescape(snip)[:300]}
        if iso:
            rec['date'] = iso
            rec['date_src'] = 'index'   # RSS pubDate 是抓取/索引时间, 不是发布时间
        out.append(rec)
        if len(out) >= max_results:
            break
    if not out:
        raise RuntimeError(f'bing RSS 0 条 (status={status})')
    return out


# 去标签只有 core.text 一份实现 (含 <em> 也吃掉、折叠空白); bing 随后还会
# _unescape, 与原来"手工 re.sub 再转义"的先后一致
_strip_tags = text.clean_markup


_unescape = text.unescape
