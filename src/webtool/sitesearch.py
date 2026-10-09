# -*- coding: utf-8 -*-
"""webtool site: 站内搜索调度 (区别于传统搜索引擎)"""
import json
import os
import sys
import time

from . import cache
from .engines.sites import SITES


def do_site(args, cfg):
    if args.site in (None, 'list'):
        from .customsites import load_custom_sites
        rows = []
        for k, v in SITES.items():
            rows.append({'site': k, 'desc': v['desc'], 'proxy_hint': v['proxy'], 'source': 'builtin'})
        for k, v in load_custom_sites().items():
            if v.get('_error'):
                rows.append({'site': k, 'desc': v['_error'], 'source': 'custom(BROKEN)'})
            else:
                rows.append({'site': k, 'desc': v.get('desc', ''), 'proxy_hint': v.get('proxy', 'auto'),
                             'source': 'custom(~/.webtool/sites)'})
        print(json.dumps(rows, ensure_ascii=False, indent=1))
        return 0
    if not args.query:
        print('usage: webtool site <site> <query>', file=sys.stderr)
        return 2

    # 自定义站点优先查 (允许覆盖内置)
    from .customsites import load_custom_sites, search_custom
    customs = load_custom_sites()
    kind, spec = None, None
    if args.site in customs and not customs[args.site].get('_error'):
        kind, spec = 'custom', customs[args.site]
    elif args.site in customs:
        print(f'site {args.site} 配置有误: {customs[args.site]["_error"]}', file=sys.stderr)
        return 2
    elif args.site in SITES:
        kind, spec = 'builtin', SITES[args.site]
    else:
        print(f'unknown site: {args.site}\navailable: {", ".join(sorted(set(SITES) | set(customs)))}\n'
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
            elif args.site == 'wikipedia' and args.lang != 'zh':
                results = SITES['wikipedia']['fn'](args.query, args.max, proxy,
                                                   cfg.get('timeout', 15), lang=args.lang)
            else:
                results = spec['fn'](args.query, args.max, proxy, cfg.get('timeout', 15))
            cache.put(cfg, 'search', ckey, results)
            src = 'fresh'
        except Exception as e:
            print(json.dumps({'error': str(e)[:300], 'site': args.site,
                              'hint': '可试 --proxy / --no-proxy 或降低 -n; `webtool site list` 查看站点'},
                             ensure_ascii=False), file=sys.stderr)
            return 1

    if not args.no_blocklist:
        from .blocklist import filter_blocklist
        results, n_blocked = filter_blocklist(results, extra_block=args.block or ())
    else:
        n_blocked = 0

    # 质量排序 + 过滤 (与 search 一致: 断层标签过滤, config/CLI 开关双通道)
    from .merge import merge as _merge
    no_wf = args.no_weight_filter or cfg.get('weight_filter') == 'off'
    n_before = len(results)
    results = _merge(results, args.query, use_semantic=cfg.get('semantic') != 'off', dedupe=cfg.get('dedupe') != 'off')
    dedup_removed = n_before - len(results)
    n_low = 0
    if not no_wf and not cfg.get('semantic') == 'off':
        n_low = len(results)
        kept = [r for r in results if r.get('quality') != 'poor']
        if not kept:
            kept = [max(results, key=lambda r: r['weight'])]
        n_low = len(results) - len(kept)
        results = kept

    # 组装 filters 说明 (黑名单/去重/权重三行)
    filters = []
    if n_blocked:
        filters.append(f'黑名单剔除 {n_blocked} 条 (--no-blocklist 关闭)')
    if dedup_removed:
        filters.append(f'跨引擎去重合并 {dedup_removed} 条(--no-dedupe 关闭)')
    if n_low:
        label = '质量poor(断层) 剔除'
        filters.append(f'{label} {n_low} 条 (--no-weight-filter 关闭)')

    out = {'site': args.site, 'query': args.query, 'took_ms': int((time.time() - t0) * 1000),
           'source': src, 'total': len(results), 'results': results,
           'dedup_removed': dedup_removed, 'blocked_by_blocklist': n_blocked,
           'filtered_low_weight': n_low}
    from .render import render
    render(out, args.format, 'site')
    return 0
