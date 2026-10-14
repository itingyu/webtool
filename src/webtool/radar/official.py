"""官方 feed 探测: 绕开 RSSHub 实例, 直接从站点官网取栏目的原始流

先按 /feed /rss /atom.xml 常见路径探, 认出内容是 RSS/Atom 后按栏目分桶;
这是 RSSHub 实例全挂时的兜底, 也用于判定"官网能不能等价替代某条路由"。
"""

import json
import re
import time
from pathlib import Path

from webtool.radar.instances_cfg import default_instances
from webtool.radar.instances import instances


# ---------------------------------------------------------------- 官方 feed 探测

OFFICIAL_FILE = Path.home() / '.webtool' / 'cache' / 'official_feeds.json'
OFFICIAL_TTL = 7 * 86400

# 常见的官方 feed 路径。顺序即优先级 —— /feed 最常见。
_FEED_PATHS = ['/feed', '/rss', '/feed.xml', '/rss.xml', '/atom.xml',
               '/index.xml', '/rss/index.xml', '/blog/atom.xml']
_FEED_CT = ('rss', 'atom', 'xml')


def _looks_like_feed(text):
    """是不是真 feed —— 只认 body, 不看 content-type。

    不少站把 XML 挂成 text/html, 而 SPA 壳页也是 text/html, 唯一可靠判据
    是开头有没有 feed 结构标记。
    """
    head = (text or '')[:2000].lstrip()
    return (head.startswith('<?xml') or '<rss' in head or '<feed' in head
            or '<rdf:RDF' in head)


def _section_buckets(text, cap=40):
    """统计 feed 条目链接的一级栏目分布 → {栏目: 条数}

    判断"官方 feed 是否覆盖目标栏目"的依据: 只看"有没有 feed"会把
    "有但不含该栏目"和"正好有该栏目"混为一谈。
    """
    links = re.findall(r'<link>\s*(?:<!\[CDATA\[)?(https?://[^<\]]+)',
                       text or '')
    out = {}
    for l in links:
        rest = re.sub(r'^https?://[^/]+/?', '', l.split('?')[0])
        if not rest or '/' not in rest:
            continue          # channel 级 <link>, 不是条目
        sec = rest.split('/')[0]
        out[sec] = out.get(sec, 0) + 1
        if len(out) > cap:
            break
    return out


def probe_official(domain, proxy=None, timeout=8):
    """探测某站是否有官方 feed, 返回 (url, items, 栏目分布) 或 (None, 0, {})

    www 与裸域都试 —— 只试一种必然漏一半。

    `proxy=None` 按 'auto' 处理 (问路由表), 不是强制直连: 官网探测打的是
    目标站本身, 该走哪条线由配置决定, 与同批的实例探测 (`instances.py`)
    保持一致 —— 否则同一批 feed 里, 官网直连而公共实例走代理, 结果没法比。
    """
    from webtool.net import transport
    proxy = proxy or 'auto'
    domain = domain.strip().strip('/')
    if not domain or '://' in domain:
        domain = domain.replace('https://', '').replace('http://', '').split('/')[0]
    hosts = [domain] if domain.startswith('www.') else \
        [domain, 'www.' + domain]
    if domain.startswith('www.'):
        hosts.append(domain[4:])
    for host in hosts:
        for path in _FEED_PATHS:
            url = f'https://{host}{path}'
            try:
                # transport.get 第三返回值是 via 不是 headers, 只嗅探 body
                text, st, _ = transport.get(url, kind='plain', timeout=timeout,
                                            proxy=proxy)
            except Exception:
                continue
            if st != 200 or not _looks_like_feed(text):
                continue
            items = re.findall(r'<(?:item|entry)[\s>]', text)
            return url, len(items), _section_buckets(text)
    return None, 0, {}


def official_section_url(card, filled=None):
    """由 RSSHub 路由反推官网栏目页 URL。

    把 https://<实例>/<namespace>/<rest> 里的 "实例/<namespace>/" 整段换成
    官网域名, 后段原样保留 (/36kr/newsflashes → https://www.36kr.com/newsflashes)。

    优先信 topFeeds[].site_url (官方给的真实源页面); 没有样例时才退回
    namespace 换域名的启发式 —— namespace 不总对应官网路径, 只是兜底。
    """
    dom = (card.get('domain') or '').strip()
    for tf in card.get('top_feeds') or []:
        if tf.get('site_url'):
            return tf['site_url']
    if not dom:
        return None
    filled = (filled or card.get('template') or '').strip()
    if not filled:
        return f'https://{dom}'
    rest = filled.strip('/').split('/', 1)
    rest = rest[1] if len(rest) > 1 else ''
    return f'https://{dom}/{rest}' if rest else f'https://{dom}'


def official_coverage(official, cards, from_url=None):
    """判断官网 feed 覆盖不覆盖这些路由的目标栏目。

    目标栏目从 topFeeds[].siteUrl (该路由的真实源页面) 或 --from-url 取路径
    前缀, 再看官网 feed 的栏目分布里有没有它。
    返回 {template: (命中栏目 or None, 条数)}。
    """
    if not official:
        return {}
    _, _, buckets = official
    out = {}
    for c in cards:
        targets = ([from_url] if from_url else []) + [
            tf['site_url'] for tf in c.get('top_feeds') or [] if tf.get('site_url')]
        hit, cnt = None, 0
        for t in targets:
            rest = re.sub(r'^https?://[^/]+/?', '', t.split('?')[0])
            sec = rest.split('/')[0]
            if not sec:                     # 站点根: 官网 feed 全站都算覆盖
                hit, cnt = '(root)', sum(buckets.values())
                break
            if buckets.get(sec):
                hit, cnt = sec, buckets[sec]
                break
        out[c['template']] = (hit, cnt)
    return out


def official_feeds(domains, proxy=None, refresh=False, max_sites=6):
    """批量探测官方 feed, 返回 {domain: (url, items)}; 结果缓存 7 天

    只探命中路由的前几个站 —— 每站一次 10 请求的探测, 全量站点不现实。
    """
    domains = [d for d in dict.fromkeys(domains or []) if d][:max_sites]
    if not domains:
        return {}
    cache = {}
    if not refresh and OFFICIAL_FILE.exists():
        try:
            o = json.loads(OFFICIAL_FILE.read_text())
            if time.time() - o.get('ts', 0) < OFFICIAL_TTL:
                cache = o.get('map') or {}
        except Exception:
            cache = {}
    out, changed = {}, False
    todo = []
    for d in domains:
        if d in cache:
            v = cache[d]
            if v:
                out[d] = (v['url'], v.get('items', 0), v.get('buckets') or {})
        else:
            todo.append(d)
    if todo:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=min(len(todo), 6)) as ex:
            for dom, res in zip(todo, ex.map(
                    lambda d: probe_official(d, proxy=proxy), todo)):
                url, items, buckets = res
                cache[dom] = ({'url': url, 'items': items, 'buckets': buckets}
                              if url else {})
                if url:
                    out[dom] = (url, items, buckets)
                changed = True
    if changed:
        try:
            OFFICIAL_FILE.parent.mkdir(parents=True, exist_ok=True)
            OFFICIAL_FILE.write_text(json.dumps(
                {'ts': time.time(), 'map': cache}, ensure_ascii=False))
        except Exception:
            pass
    return out


def best_instance(proxy=None, refresh=False, default=None):
    """返回当前可用的实例前缀 (探活延迟最低的), 全挂则用内置兜底"""
    if default:
        return default.rstrip('/')
    alive = [it for it in instances(proxy=proxy, refresh=refresh, need=1)
             if it['ok']]
    if not alive:
        inst = default_instances()
        return inst[1].rstrip('/') if len(inst) > 1 else (inst[0].rstrip('/') if inst else '')
    return min(alive, key=lambda it: it['ms'])['instance'].rstrip('/')
