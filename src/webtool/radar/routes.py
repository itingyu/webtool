"""官方路由目录 (docs.rsshub.app/routes.json): 照着填参的唯一权威数据源

每条路由带 parameters(参数枚举) / example(官方填好的路径) / topFeeds(真实
实例与标题) / features(踩坑标记) / heat(热度); 缓存 ~/.webtool/cache/
rsshub_routes.json, TTL 7 天。
"""

import json
import re
import time
from pathlib import Path

from webtool.radar.template import parse_params

ROUTES_URL = 'https://docs.rsshub.app/routes.json'
ROUTES_FILE = Path.home() / '.webtool' / 'cache' / 'rsshub_routes.json'
ROUTES_TTL = 7 * 86400


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
    from webtool.net import transport
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
