# -*- coding: utf-8 -*-
"""radar: RSSHub 路由查询与参数填充

两个数据源, 主备关系:

  1. 官方路由目录 docs.rsshub.app/routes.json (数千站 / 数千路由)
     每条路由带 parameters(参数枚举说明) / example(官方填好的路径) /
     topFeeds(真实实例 + 标题 + 源页面 URL) / features(踩坑标记) / heat(热度)。
     这是唯一能"照着填参"的数据源。
     缓存 ~/.webtool/cache/rsshub_routes.json (TTL 7 天)。

  2. Radar 规则库 (任意公共实例 GET /api/radar/rules)
     只有 source(网页 URL 模式) → target(路由模板), 用于 --from-url 反推;
     以及主源拉取失败时的降级查询路径。

路径模板语法 (RSSHub):
    /:name            必填参数
    /:name?           可选参数, 不填则整段消失
    /:name{regex}?    带正则约束的可选参数, 如 /81rc/:category{.+}?
模板 = 实例前缀 + 模板 + 实参, 即最终订阅 URL。
"""

import json
import re
import time
from pathlib import Path

ROUTES_URL = 'https://docs.rsshub.app/routes.json'
ROUTES_FILE = Path.home() / '.webtool' / 'cache' / 'rsshub_routes.json'
ROUTES_TTL = 7 * 86400

def race(jobs, ok=None, timeout=None, need=None):
    """并发跑 {key: callable}

    need=None: 等到第一个满足 ok 的就返回 (results 只含已完成的 key)。
    need=N  : 等 N 个满足 ok 的。
    need=-1 : 等全部跑完 (早退会把没回来的记成未知)。

    用 daemon 线程而不是 ThreadPoolExecutor: 后者在解释器退出时会 join 所有
    worker, 而这里恰恰要放弃还没回来的慢/挂请求; daemon 线程不阻塞退出。
    """
    import threading
    ok = ok or (lambda r: bool(r))
    results, lock, done = {}, threading.Lock(), threading.Event()
    left = [len(jobs)]
    hits = [0]

    def run(key, fn):
        try:
            r = fn()
        except Exception:
            r = None
        with lock:
            results[key] = r
            left[0] -= 1
            if ok(r):
                hits[0] += 1
            if need == -1:
                finished_enough = left[0] <= 0        # 等全部
            elif need:
                finished_enough = hits[0] >= need      # 等够 N 个
            else:
                finished_enough = True                 # 等第一个
        if finished_enough or left[0] <= 0:
            done.set()

    threads = [threading.Thread(target=run, args=(k, fn), daemon=True)
               for k, fn in jobs.items()]
    for t in threads:
        t.start()
    done.wait(timeout)
    return results


RADAR_FILE = Path.home() / '.webtool' / 'cache' / 'radar_rules.json'
RADAR_TTL = 7 * 86400

# 公共实例表已外置: data/instances.json (默认) + ~/.webtool/instances.json (用户覆盖)。
# 可用性每天在变, 别当常量信 —— 用 instances() 探活。
def _default_instances():
    from webtool.config_data import load as _cfg_load
    return list((_cfg_load('rsshub', 'instances.json') or {}).get('instances') or [])

# 实例探活用的廉价路由, 任意一个出条目即视为实例活着
_PROBE_ROUTE = '/36kr/newsflashes'
INSTANCES_FILE = Path.home() / '.webtool' / 'cache' / 'rsshub_instances.json'
INSTANCES_TTL = 3600

# :name / :name? / :name{regex}? / :name{regex}
_PARAM_RE = re.compile(r':([A-Za-z_]\w*)(\{[^}]*\})?(\?)?')


class MissingParams(Exception):
    """必填参数没给全"""

    def __init__(self, missing):
        self.missing = missing
        super().__init__(', '.join('%s' % m[0] for m in missing))


# ---------------------------------------------------------------- 模板解析


def parse_params(template):
    """模板 → [(参数名, 是否可选, 正则约束或 None)]

    >>> parse_params('/163/ds/:id')
    [('id', False, None)]
    >>> parse_params('/36kr/:category/:subCategory?')
    [('category', False, None), ('subCategory', True, None)]
    >>> parse_params('/81rc/:category{.+}?')
    [('category', True, '.+')]
    """
    out = []
    for m in _PARAM_RE.finditer(template):
        name, rex, opt = m.group(1), m.group(2), m.group(3)
        out.append((name, bool(opt), rex[1:-1] if rex else None))
    return out


def fill_path(template, params, strict=True):
    """模板 + 实参 → 填好的路径 (缺可选段自动剔除)

    params 键可带 path 里的正则后缀, 如 {'category{.+}?': 'x'} 与 {'category': 'x'}
    等价 —— 先按裸名试, 再按原文试。

    strict=True 时必填参数缺失抛 MissingParams; strict=False 时原样保留 :name
    (交给 RSSHub 自己报错, 适合只想看 URL 的时候)。
    """
    specs = parse_params(template)
    out, missing = template, []
    for name, optional, rex in specs:
        val = params.get(name)
        if val is None:
            for k, v in params.items():          # 容忍 'category{.+}?' 这类键
                if k.split('{')[0].rstrip('?') == name:
                    val = v
                    break
        if val is None:
            if optional:
                # 剔掉整个参数段: ':name{regex}?' 连同前导 '/'
                out = re.sub(r'/:' + re.escape(name) + r'(\{[^}]*\})?\?', '', out)
            else:
                missing.append((name, rex))
            continue
        out = out.replace(f':{name}{{{rex}}}?' if rex else f':{name}?',
                          str(val))
        out = out.replace(f':{name}{{{rex}}}' if rex else f':{name}',
                          str(val))
    if missing and strict:
        raise MissingParams(missing)
    return out.rstrip('/') or '/'


def render_url(instance, template, params=None, strict=True):
    """实例前缀 + 模板 + 实参 → 完整订阅 URL"""
    return instance.rstrip('/') + fill_path(template, params or {}, strict)


# ---------------------------------------------------------------- 官方路由目录


def load_routes(proxy=None, refresh=False, timeout=60):
    """载入官方 routes.json (缓存优先), 返回 {站点key: 站点dict}; 失败抛异常"""
    if not refresh and ROUTES_FILE.exists():
        try:
            o = json.loads(ROUTES_FILE.read_text())
            if time.time() - o.get('ts', 0) < ROUTES_TTL and o.get('routes'):
                return o['routes']
        except Exception:
            pass
    from webtool import transport
    text, st, _ = transport.get(ROUTES_URL, kind='plain', timeout=timeout,
                                proxy=proxy, allow_fallback=False)
    if st != 200:
        raise RuntimeError(f'routes.json HTTP {st}')
    routes = json.loads(text)
    if not isinstance(routes, dict) or not routes:
        raise RuntimeError('routes.json 结构异常')
    ROUTES_FILE.parent.mkdir(parents=True, exist_ok=True)
    ROUTES_FILE.write_text(json.dumps({'ts': time.time(), 'routes': routes},
                                      ensure_ascii=False))
    return routes


def _iter_routes(routes):
    """展平成 (站点, 站点key, 路由key, 路由dict)"""
    for site_key, site in (routes or {}).items():
        if not isinstance(site, dict):
            continue
        for rk, r in (site.get('routes') or {}).items():
            if isinstance(r, dict):
                yield site, site_key, rk, r


def search_routes(routes, kw, limit=20, cat=None, skip_config=True):
    """按关键词搜路由, 返回路由卡片列表 (按 heat 降序)

    匹配面: 站点名 / 域名 / 路由名 / 路由模板 / 参数名 / 参数说明 / 分类。
    skip_config=True 跳过"需必填配置"的路由 —— 公共实例上没有那个 cookie 必然空。
    """
    kw_l = (kw or '').lower().strip()
    scored = []
    for site, site_key, rk, r in _iter_routes(routes):
        tmpl = '/' + rk.lstrip('/')
        site_name = site.get('name') or ''
        domain = site.get('url') or ''
        rname = r.get('name') or ''
        params = r.get('parameters') or {}
        ptext = ' '.join(f'{k} {v}' for k, v in params.items())
        cats = r.get('categories') or site.get('categories') or []
        if cat and cat not in cats:
            continue
        feat = r.get('features') if isinstance(r.get('features'), dict) else {}
        need_cfg = feat.get('requireConfig')
        if skip_config and need_cfg:
            if isinstance(need_cfg, list) and any(
                    not c.get('optional') for c in need_cfg):
                continue
        hay = f'{site_name} {domain} {rname} {tmpl} {ptext} {" ".join(cats)}'.lower()
        if kw_l and kw_l not in hay:
            continue
        # 排序: 域名/站名/路由名精确命中 > heat
        if kw_l:
            exact = any(kw_l == x.lower().strip() for x in
                        (site_name, domain, rname))
            rank = 0 if exact else 1
        else:
            rank = 1
        scored.append((rank, -(r.get('heat') or 0), {
            'site': site_name, 'domain': domain, 'template': tmpl,
            'name': rname, 'heat': r.get('heat') or 0, 'params': params,
            'example': r.get('example') or '', 'categories': cats,
            'features': feat, 'top_feeds': _usable_top_feeds(r),
            'desc': r.get('description') or '',
        }))
    scored.sort(key=lambda x: (x[0], x[1]))
    return [c for _, _, c in scored[:limit]]


def _usable_top_feeds(r, cap=5):
    """真实实例样例: 只留有 url 且无 errorMessage 的"""
    out = []
    for f in (r.get('topFeeds') or []):
        if not isinstance(f, dict) or f.get('errorMessage'):
            continue
        u = (f.get('url') or '').replace('rsshub://', '').lstrip('/')
        if not u:
            continue
        out.append({'title': f.get('title') or '', 'site_url': f.get('siteUrl') or '',
                    'path': u})
        if len(out) >= cap:
            break
    return out


def routes_stats(routes):
    n_sites = sum(1 for v in (routes or {}).values() if isinstance(v, dict))
    n_routes = sum(1 for _ in _iter_routes(routes))
    n_free = sum(1 for _, _, rk, _ in _iter_routes(routes) if ':' not in rk)
    return n_sites, n_routes, n_free


def _source_to_regex(src):
    """radar.source (urlpattern 风格) → 正则

    :name / :name? 是参数段, * 是通配段 —— 两者都吃一段不含 / 的字符。
    顺序要紧: 先按 :name 切, 再整体转义, 最后把占位符换回捕获组。
    """
    parts = re.split(r'(:[A-Za-z_]\w*\??|\*)', src.rstrip('/'))
    out = []
    for seg in parts:
        if re.fullmatch(r':[A-Za-z_]\w*\??|\*', seg):
            out.append(r'([^/]+)')
        else:
            out.append(re.escape(seg))
    return ''.join(out)


def from_url(routes, url):
    """给定网页 URL, 用官方路由的 radar.source 模式反推候选路由

    source 形如 ['space.bilibili.com/:uid', 'bilibili.com/user/video'],
    是 urlpattern 风格的通配, 逐条正则匹配。

    注意 radar.target 是相对 namespace 的路径, 要拼上路由 key 的第一段
    (namespace) 才是完整模板; 没有 target 的条目由路由 key 去掉 namespace
    反推。
    """
    if not url:
        return []
    u = re.sub(r'^https?://', '', url).split('#')[0].rstrip('/')
    # www. 前缀在 urlpattern 里各家写法不一, 两种形态都试一遍
    variants = [u] + ([u[4:] if u.startswith('www.') else 'www.' + u]
                      if re.match(r'^(www\.)?[^/]+(/|$)', u) else [])
    out = []
    for site, site_key, rk, r in _iter_routes(routes):
        for rd in (r.get('radar') or []):
            target = rd.get('target')
            for src in (rd.get('source') or []):
                pat = _source_to_regex(src)
                m = next((mm for mm in (re.fullmatch(pat, v) for v in variants)
                          if mm), None)
                if not m:
                    continue
                # 一律用完整路由 key 而不是 radar.target: target 是有损投影
                # (丢掉可选尾参), 而 key 的必填段在前, 从 URL 回填后剩下的
                # 可选段自然可以留空
                tmpl = '/' + rk.lstrip('/')
                _ = target
                groups = [g for g in m.groups() if g is not None]
                params = {}
                names = [n for n, _, _ in parse_params(tmpl)]
                for n, g in zip(names, groups):
                    params[n] = g
                out.append({
                    'site': site.get('name') or '', 'domain': site.get('url') or '',
                    'template': tmpl, 'name': r.get('name') or '',
                    'heat': r.get('heat') or 0, 'params': r.get('parameters') or {},
                    'example': r.get('example') or '',
                    'categories': r.get('categories') or [],
                    'features': r.get('features') or {}, 'top_feeds': [],
                    'desc': r.get('description') or '',
                    'guessed': params,
                })
    out.sort(key=lambda c: -c['heat'])
    return out[:10]


# ---------------------------------------------------------------- Radar 规则库 (降级/反推)


def load_rules(proxy=None, refresh=False, timeout=20):
    """载入 radar rules (缓存优先), 返回 dict; 失败抛异常"""
    if not refresh and RADAR_FILE.exists():
        try:
            o = json.loads(RADAR_FILE.read_text())
            if time.time() - o.get('ts', 0) < RADAR_TTL and o.get('rules'):
                return o['rules']
        except Exception:
            pass
    from webtool import transport
    errs = []
    for base in _default_instances():
        # 直连优先 (CF 对代理出口更敏感), 失败再试代理
        attempts = [None] + ([proxy] if proxy else [])
        for px in attempts:
            try:
                text, st, _ = transport.get(base + '/api/radar/rules', kind='plain',
                                            timeout=timeout, proxy=px,
                                            allow_fallback=False)
                if st == 200 and text.lstrip().startswith('{'):
                    rules = json.loads(text)
                    RADAR_FILE.parent.mkdir(parents=True, exist_ok=True)
                    RADAR_FILE.write_text(json.dumps(
                        {'ts': time.time(), 'base': base, 'rules': rules},
                        ensure_ascii=False))
                    return rules
                errs.append(f'{base}: HTTP {st}')
            except Exception as e:
                errs.append(f'{base}: {str(e)[:60]}')
    raise RuntimeError('radar rules 拉取失败 (全实例): ' + '; '.join(errs))


def search(rules, kw, limit=30):
    """按关键词查 radar 规则 (域名、站名、标题、target 模糊匹配)

    返回 [(domain, site_name, title, target)] — target 保留 :param 模板
    """
    kw_l = kw.lower()
    out = []
    for dom, paths in rules.items():
        if not isinstance(paths, dict):
            continue
        site = paths.get('_name', '')
        hit_site = kw_l in dom.lower() or kw_l in site.lower()
        for path, arr in paths.items():
            if path == '_name' or not isinstance(arr, list):
                continue
            for r in arr:
                t = r.get('title', '')
                tg = r.get('target', '')
                if hit_site or kw_l in t.lower() or kw_l in tg.lower():
                    out.append((dom, site, t, tg))
    # 排序: 域名精确命中 > 站名命中; 同域按 title
    out.sort(key=lambda x: (0 if kw_l in x[0].lower() else 1, x[0], x[2]))
    return out[:limit]


def render(instance, target, **params):
    """兼容旧接口: 实例前缀 + radar target + 关键字参数 → 订阅 URL"""
    return render_url(instance, target, params)


def stats(rules):
    sites = sum(1 for v in rules.values()
                if isinstance(v, dict) and '_name' in v)
    n = sum(len([r for p, rs in v.items() if isinstance(rs, list) for r in rs])
            for v in rules.values() if isinstance(v, dict))
    return sites, n


# ---------------------------------------------------------------- 实例探活


def instances(proxy=None, refresh=False, need=None, timeout=10):
    """实例列表 + 探活结果 [{instance, ok, ms, items, err}], 缓存 1 小时

    公共实例可用性逐日变化, 默认实探而不是信文档。

    need=N 时凑够 N 个可用实例就返回 —— 全量探活要等每个挂掉的实例跑满
    直连+代理两轮超时, 只想找一个能用的没必要等全场。
    """
    if not refresh and INSTANCES_FILE.exists():
        try:
            o = json.loads(INSTANCES_FILE.read_text())
            lst = o.get('list') or []
            fresh = time.time() - o.get('ts', 0) < INSTANCES_TTL
            if fresh and lst:
                got = [i for i in lst if i.get('ok')]
                # partial 缓存 (有实例没探到) 只在"只需要够 N 个"时可信;
                # 要全量清单就得真探完, 否则会把 '未探测' 当结论用
                if need is not None and len(got) >= need:
                    return lst
                if o.get('complete'):
                    return lst
        except Exception:
            pass
    from webtool import transport

    def probe(base):
        t0 = time.time()
        attempts = [None] + ([proxy] if proxy else [])
        last = 'no route'
        for px in attempts:
            try:
                text, st, _ = transport.get(base + _PROBE_ROUTE, kind='plain',
                                            timeout=timeout, proxy=px,
                                            allow_fallback=False)
                n = len(re.findall(r'<(?:item|entry)[\s>]', text or ''))
                if st == 200 and n:
                    return {'instance': base, 'ok': True, 'items': n,
                            'ms': int((time.time() - t0) * 1000), 'err': ''}
                last = f'HTTP {st}' + (' 0 items' if st == 200 else '')
            except Exception as e:
                last = str(e)[:50]
        return {'instance': base, 'ok': False, 'items': 0,
                'ms': int((time.time() - t0) * 1000), 'err': last}

    jobs = {b: (lambda b=b: probe(b)) for b in _default_instances()}
    if need is None:
        # 全量清单 (`feed instances` 用法) 必须等全部回来, 否则早退会把没探
        # 到的显示成 '未探测' —— 看着像挂了, 其实没问过
        found = race(jobs, ok=lambda r: False, timeout=timeout * 3, need=-1)
    else:
        found = race(jobs, ok=lambda r: bool(r and r['ok']),
                     timeout=timeout * 3, need=need)
    out = [found.get(b, {'instance': b, 'ok': False, 'items': 0, 'ms': 0,
                          'err': '未探测'})
           for b in _default_instances()]
    complete = all(x['err'] != '未探测' for x in out)
    # 早退的部分结果也落盘, 否则紧接着的全量调用把刚省下的等待又付一遍
    INSTANCES_FILE.parent.mkdir(parents=True, exist_ok=True)
    INSTANCES_FILE.write_text(json.dumps(
        {'ts': time.time(), 'list': out, 'complete': complete},
        ensure_ascii=False))
    return out


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
    """
    from webtool import transport
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
                                            proxy=proxy, allow_fallback=False)
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
    ns = filled.strip('/').split('/')[0]
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
        inst = _default_instances()
        return inst[1].rstrip('/') if len(inst) > 1 else (inst[0].rstrip('/') if inst else '')
    return min(alive, key=lambda it: it['ms'])['instance'].rstrip('/')
