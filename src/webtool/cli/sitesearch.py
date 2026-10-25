"""站内搜索调度 (入口: webtool search -s <site> <query>)"""
import json
import sys
import time

from webtool.dao import cache
from webtool.engines.sites import sites_table

# 站点别名: 正式名里有 gh_search / bili2 / juejin2 这种记不住的,
# 用户嘴上的自然叫法都认 (大小写不敏感)
_SITE_ALIAS = {
    'bili': 'bilibili', 'b站': 'bilibili', '小破站': 'bilibili',
    '掘金': 'juejin', '掘金文章': 'juejin2',
    'v2ex': 'sov2ex', 'v2': 'sov2ex',
    'stackoverflow': 'so', 'stack-overflow': 'so', 'stack': 'so',
    'wiki': 'wikipedia', '维基': 'wikipedia', '维基百科': 'wikipedia',
    'gh': 'github', 'github-search': 'gh_search', 'github搜索': 'gh_search',
    '豆瓣': 'douban', '豆瓣读书': 'douban',
    'it之家': 'ithome_so', 'ithome': 'ithome_so',
    'sf': 'segmentfault', 'segment': 'segmentfault',
    'csdn问答': 'csdn_so', 'csdn-qa': 'csdn_so',
    '澎湃': 'thepaper', '澎湃新闻': 'thepaper',
    '东财': 'eastmoney', '东方财富': 'eastmoney',
    '少数派': 'sspai', 'npm包': 'npm',
}

def _canon_site(name):
    """别名 -> 正式站点名; 不认识的原样返回"""
    return _SITE_ALIAS.get(str(name).strip().lower(), name)


def _site_kwargs(args, spec):
    """站点声明要的额外参数 (params.args) 与命令行值的交集

    站点自己在清单里写 "params": {"args": ["lang"]}, 命令行给了同名值
    才传下去 —— 新增带参站点只需改清单, 不必改调度代码。
    """
    out = {}
    for key in (spec.get('args') or ()):
        val = getattr(args, key, None)
        if val not in (None, '', 'zh'):     # 默认值不传, 让站点用自己的默认
            out[key] = val
    return out


def fetch_site(name, args, cfg):
    """单站点取原始结果 (别名归一/自定义优先/参数透传/缓存)

    返回 (results, status, kind)。未知站点抛 LookupError, 配置错抛 ValueError。
    do_site 与 `search -s` 共用 —— 站点不进独立管线, 和多引擎一样交给 merge。
    """
    from webtool.engines.customsites import load_custom_sites, search_custom
    site = _canon_site(name)
    customs = load_custom_sites()
    kind, spec = None, None
    if site in customs and not customs[site].get('_error'):
        kind, spec = 'custom', customs[site]
    elif site in customs:
        raise ValueError(f'site {site} 配置有误: {customs[site]["_error"]}')
    elif site in sites_table():
        kind, spec = 'builtin', sites_table()[site]
    else:
        raise LookupError(site)

    ckey = (f'{site}|{args.query}|{args.max}|{getattr(args, "lang", "") or ""}'
            f'|{getattr(args, "since", "") or ""}|{getattr(args, "until", "") or ""}')
    if not getattr(args, 'no_cache', False):
        cached = cache.get(cfg, 'search', ckey)
        if cached is not None:
            return cached, 'cache', kind

    # 线路只有两个来源: 用户的显式要求 (--no-proxy, 或自定义站点配置里的
    # proxy 字段), 其余一律交规则表 ('auto')。
    if getattr(args, 'no_proxy', False):
        proxy = 'direct'
    elif kind == 'custom':
        proxy = spec.get('proxy', 'auto')
    else:
        proxy = 'auto'
    if kind == 'custom':
        results = search_custom(site, spec, args.query, args.max,
                                proxy, cfg.get('timeout', 15))
    else:
        results = spec['fn'](args.query, args.max, proxy,
                             cfg.get('timeout', 15),
                             **_site_kwargs(args, spec))
    cache.put(cfg, 'search', ckey, results)
    return results, 'fresh', kind


def do_site(args, cfg):
    if args.site in (None, 'list'):
        from webtool.engines.customsites import load_custom_sites
        rows = []
        for k, v in sites_table().items():
            # 内置站点不声明线路: 直连还是代理看规则表, 临时绕过用 --no-proxy
            rows.append({'site': k, 'desc': v['desc'], 'proxy': 'auto',
                         'source': 'builtin'})
        for k, v in load_custom_sites().items():
            if v.get('_error'):
                rows.append({'site': k, 'desc': v['_error'], 'source': 'custom(BROKEN)'})
            else:
                rows.append({'site': k, 'desc': v.get('desc', ''), 'proxy': v.get('proxy', 'auto'),
                             'source': 'custom(~/.webtool/sites)'})
        # 清单是可机读数据: 一律走 render 分发, 别让 -f 变成摆设
        from webtool.render.hotrender import render_keyed_list
        render_keyed_list({'results': rows}, args.format, kind='site',
                           title='站点搜索源', desc_fields=('desc',))
        return 0
    if args.query is None:
        args.query = ''
    args.site = _canon_site(args.site)      # bili / 掘金 / v2ex 等别名先归一

    t0 = time.time()
    try:
        results, src, kind = fetch_site(args.site, args, cfg)
    except LookupError:
        import difflib
        from webtool.engines.customsites import load_custom_sites
        names = sorted(set(sites_table()) | set(load_custom_sites()))
        near = difflib.get_close_matches(str(args.site), names + sorted(_SITE_ALIAS), n=3)
        hint = ('\n你是不是想找: ' + ', '.join(near)) if near else ''
        print(f'unknown site: {args.site}{hint}\navailable: {", ".join(names)}\n'
              f'use `webtool search -l` for detail', file=sys.stderr)
        return 2
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2
    except Exception as e:
        print(json.dumps({'error': str(e)[:300], 'site': args.site,
                          'hint': '可试 --proxy / --no-proxy 或降低 -n; `webtool search -l` 查看站点'},
                         ensure_ascii=False), file=sys.stderr)
        return 1

    # 站内搜索是白名单源 (官方 API, 站点本身已可信), 不走黑名单过滤;
    n_blocked = 0

    # quality 仅标注不剔除, 与 search 一致
    from webtool.pipeline.merge import merge as _merge
    n_before = len(results)
    # 站内搜索不跨引擎, 但结果来源就是该站点 —— 标上它, 否则 engines 是空数组
    # (注意用 args.site, 不是 src —— 后者是 cache/fresh 缓存状态)
    for r in results:
        if not r.get('engine'):
            r['engine'] = args.site
    results = _merge(results, args.query, use_semantic=True, dedupe=True)
    dedup_removed = n_before - len(results)

    # 时间过滤 (与 search 同一套 date 过滤器)。站内源的日期字段通常比关键词
    # 引擎全 (ithome_so 直接给 time), 这里过滤比在 search 里更管用。
    n_date = 0
    if getattr(args, 'since', None) or getattr(args, 'until', None):
        from webtool.filters.datefilter import filter_by_date
        _before = len(results)
        results = filter_by_date(results, {'args': args, 'cfg': cfg})
        n_date = _before - len(results)

    # filters_applied 由 render 层从 blocked_by_blocklist 等字段生成, 此处
    # 不再自建 filters 列表 (那是局部死变量)。
    out = {'site': args.site, 'query': args.query, 'took_ms': int((time.time() - t0) * 1000),
           'source': src, 'total': len(results), 'results': results,
           'dedup_removed': dedup_removed, 'blocked_by_blocklist': n_blocked,
           'date_filtered': n_date}
    from webtool.render.render import render
    render(out, args.format, 'site')
    return 0
