"""RSSHub 路由库 → feed 源: 全量物化

2069 站 / 3947 条路由展平成可直接 `webtool feed <key>` 的源:
- 键名 = 域名短名 (36kr); 同站多条路由时, 最热那条占短名, 其余 `36kr_hot_list`
- 路由模板原样保留, 取数时用当前最快实例现拼 URL (实例挂了自动换)
- 带参数的路由不猜值: 没传参就打印参数表 + 官方 example 用法

产物落 ~/.webtool/feed_radar.json, radar 路由缓存刷新后自动重建。
"""
import json
import re
import time

from webtool.core.paths import user_path
from webtool.radar.template import parse_params

FILE = 'feed_radar.json'


_SUFFIX = {'com', 'cn', 'net', 'org', 'io', 'co', 'tv', 'me', 'app', 'dev',
           'cc', 'xyz', 'info', 'gov', 'edu', 'top', 'site', 'us', 'uk',
           'jp', 'kr', 'de', 'fr', 'ru', 'au', 'ca', 'in', 'eu'}


def _slug(s):
    s = str(s or '').lower().strip()
    s = re.sub(r'^[a-z]+://', '', s).split('/')[0].split(':')[0]
    labels = [x for x in s.split('.') if x]
    while labels and labels[0] in ('www', 'm', 'mobile'):
        labels.pop(0)
    # 去掉后缀, 取注册域主标签: 36kr.com → 36kr; space.bilibili.com → bilibili
    while len(labels) > 1 and labels[-1] in _SUFFIX:
        labels.pop()
    s = labels[-1] if labels else s
    return re.sub(r'[^a-z0-9]+', '_', s).strip('_') or 'x'


def _key_slug(path, dom):
    """路由路径里的静态段: /36kr/hot-list/:category? → hot_list"""
    segs = [x for x in path.split('/') if x and not x.startswith(':')]
    while segs and _slug(segs[0]) == dom:
        segs.pop(0)
    return '_'.join(_slug(x) for x in segs)


def _entry(site, route, path, key, dom, heat):
    specs = parse_params(path)
    params_meta = route.get('parameters') or {}
    desc = route.get('description') or ''
    return {
        'url': None,                     # 取数时按实例现拼
        'template': path,
        'example': route.get('example') if isinstance(route.get('example'), str) else '',
        'desc': f"{site.get('name') or dom} · {route.get('name') or path}",
        'site': site.get('name') or dom,
        'route_name': route.get('name') or path,
        'group': dom,
        'heat': heat,
        'categories': route.get('categories') or site.get('categories') or [],
        'params': {name: params_meta.get(name) or '' for name, _, _ in specs},
        'required': [name for name, opt, _ in specs if not opt],
        'optional': [name for name, opt, _ in specs if opt],
        'doc': re.sub(r'\s+', ' ', desc)[:400],
    }


def build(routes):
    """路由库 → {源名: 条目}; 纯函数, 不碰网络"""
    out = {}
    for site_key, site in (routes or {}).items():
        if not isinstance(site, dict):
            continue
        dom = _slug(site.get('url') or site_key)
        variants = []
        for rk, r in (site.get('routes') or {}).items():
            if not isinstance(r, dict):
                continue
            raw = r.get('path')
            extra = [x for x in raw if isinstance(x, str)] if isinstance(raw, list) else []
            # 路由 key 本身就是完整路径 (/36kr/hot-list/:category?)
            paths = [rk] + [f'/{site_key.rstrip("/")}/{x.lstrip("/")}'
                            for x in extra if x and x != rk]
            for i, p in enumerate(dict.fromkeys(paths)):
                variants.append((r, p, i, len(paths)))
        variants.sort(key=lambda v: -(v[0].get('heat') or 0))
        for idx, (r, p, i, total) in enumerate(variants):
            rs = _key_slug(p, dom)
            if rs in ('', 'x'):
                rs = ''
            if idx == 0 and total == 1:
                key = dom
            else:
                key = f'{dom}_{rs}' if rs else f'{dom}_{idx + 1}'
            if key in out:
                key = f'{key}_{i + 1}'
            n = 2
            while key in out:
                key = f'{key.rsplit("_", 1)[0]}_{n}'
                n += 1
            out[key] = _entry(site, r, p, key, dom, r.get('heat') or 0)
    return out


def _routes_mtime():
    from webtool.radar.routes import ROUTES_FILE
    try:
        return ROUTES_FILE.stat().st_mtime
    except OSError:
        return 0.0


def load(routes=None, refresh=False):
    """读物化表, 路由缓存更新过就重建; 失败返回 {} (不挡 feed)"""
    try:
        if not refresh:
            o = json.loads(user_path(FILE).read_text())
            if o.get('sources') and o.get('routes_mtime') == _routes_mtime():
                return o['sources']
        if routes is None:
            from webtool import radar
            routes = radar.load_routes()
        src = build(routes)
        out = {'ts': time.time(), 'routes_mtime': _routes_mtime(), 'sources': src}
        user_path(FILE).write_text(json.dumps(out, ensure_ascii=False))
        return src
    except Exception:
        return {}


def render(entry, params=None, example=False, instance=None):
    """条目 + 实参 → 完整订阅 URL; 缺必填抛 radar.MissingParams"""
    from webtool import radar
    base = (instance or radar.best_instance()).rstrip('/')
    if example and entry.get('example'):
        path = entry['example']
    else:
        path = radar.fill_path(entry['template'], params or {}, strict=True)
    return base + '/' + path.lstrip('/')


def hint(key, entry):
    """参数缺失时给人的下一步 (照抄即可执行)"""
    req, opt = entry.get('required') or [], entry.get('optional') or []
    lines = [f'{key} 需要填参: {entry["template"]}']
    for name in req:
        lines.append(f'  必填  {name}   {entry["params"].get(name) or ""}')
    for name in opt:
        lines.append(f'  可选  {name}   {entry["params"].get(name) or ""}')
    if req:
        lines.append(f'  填参  webtool feed {key} -p {req[0]}=...')
    else:
        lines.append(f'  不填可选参数也能抓, 要指定: webtool feed {key} -p {opt[0]}=...')
    if entry.get('example'):
        lines.append(f'  示例  webtool feed {key} -e    (官方 example: {entry["example"]})')
    lines.append(f'  更多  webtool feed radar find {entry.get("group")}')
    return '\n'.join(lines)
