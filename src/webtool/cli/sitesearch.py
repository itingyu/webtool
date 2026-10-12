"""webtool site: 站内搜索调度 (区别于传统搜索引擎)"""
import json
import sys
import time

from webtool.core import cache
from webtool.engines.sites import sites_table


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


def do_site(args, cfg):
    if args.site in (None, 'list'):
        from webtool.engines.customsites import load_custom_sites
        rows = []
        for k, v in sites_table().items():
            rows.append({'site': k, 'desc': v['desc'], 'proxy_hint': v['proxy'], 'source': 'builtin'})
        for k, v in load_custom_sites().items():
            if v.get('_error'):
                rows.append({'site': k, 'desc': v['_error'], 'source': 'custom(BROKEN)'})
            else:
                rows.append({'site': k, 'desc': v.get('desc', ''), 'proxy_hint': v.get('proxy', 'auto'),
                             'source': 'custom(~/.webtool/sites)'})
        # 清单是可机读数据: 一律走 render 分发, 别让 -f 变成摆设
        from webtool.render.hotrender import render_keyed_list
        render_keyed_list({'results': rows}, args.format, kind='site',
                           title='站点搜索源', desc_fields=('desc',))
        return 0
    if args.query is None:
        args.query = ''

    # 自定义站点优先查 (允许覆盖内置)
    from webtool.engines.customsites import load_custom_sites, search_custom
    customs = load_custom_sites()
    kind, spec = None, None
    if args.site in customs and not customs[args.site].get('_error'):
        kind, spec = 'custom', customs[args.site]
    elif args.site in customs:
        print(f'site {args.site} 配置有误: {customs[args.site]["_error"]}', file=sys.stderr)
        return 2
    elif args.site in sites_table():
        kind, spec = 'builtin', sites_table()[args.site]
    else:
        print(f'unknown site: {args.site}\navailable: {", ".join(sorted(set(sites_table()) | set(customs)))}\n'
              f'use `webtool site list` for detail', file=sys.stderr)
        return 2

    t0 = time.time()
    ckey = f'{args.site}|{args.query}|{args.max}|{args.lang}'
    cached = None if args.no_cache else cache.get(cfg, 'search', ckey)
    if cached is not None:
        results, src = cached, 'cache'
    else:
        # 代理策略: 命令行 --no-proxy > 站点配置 proxy 字段 > 全局
        site_proxy = spec.get('proxy', 'auto') if kind == 'custom' else spec['proxy']
        proxy = (cfg.get('engine_proxy') or {}).get(f'site:{args.site}')
        if args.no_proxy:
            proxy = None
        elif proxy is None:
            if site_proxy == 'direct':
                proxy = None
            elif site_proxy == 'proxy' or cfg.get('proxy'):
                proxy = cfg.get('proxy')
        try:
            if kind == 'custom':
                results = search_custom(args.site, spec, args.query, args.max,
                                        proxy, cfg.get('timeout', 15))
            else:
                # 站点在 params.args 声明要哪些额外参数 (如 wikipedia 的 lang),
                # 命令行给了才带上 —— 不再按站点名写特例分支
                results = spec['fn'](args.query, args.max, proxy,
                                     cfg.get('timeout', 15),
                                     **_site_kwargs(args, spec))
            cache.put(cfg, 'search', ckey, results)
            src = 'fresh'
        except Exception as e:
            print(json.dumps({'error': str(e)[:300], 'site': args.site,
                              'hint': '可试 --proxy / --no-proxy 或降低 -n; `webtool site list` 查看站点'},
                             ensure_ascii=False), file=sys.stderr)
            return 1

    # 站内搜索是白名单源 (官方 API, 站点本身已可信), 不走黑名单过滤;
    # --block/--allow 仍保留用于临时域名补充
    n_blocked = 0

    # quality 仅标注不剔除, 与 search 一致
    from webtool.pipeline.merge import merge as _merge
    n_before = len(results)
    results = _merge(results, args.query, use_semantic=cfg.get('semantic') != 'off', dedupe=cfg.get('dedupe') != 'off')
    dedup_removed = n_before - len(results)

    filters = []
    if n_blocked:
        filters.append(f'黑名单剔除 {n_blocked} 条 (--no-blocklist 关闭)')
    if dedup_removed:
        filters.append(f'跨引擎去重合并 {dedup_removed} 条(--no-dedupe 关闭)')

    out = {'site': args.site, 'query': args.query, 'took_ms': int((time.time() - t0) * 1000),
           'source': src, 'total': len(results), 'results': results,
           'dedup_removed': dedup_removed, 'blocked_by_blocklist': n_blocked}
    from webtool.render.render import render
    render(out, args.format, 'site')
    return 0
