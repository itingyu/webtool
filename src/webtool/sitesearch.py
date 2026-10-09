# -*- coding: utf-8 -*-
"""webtool site: 站内搜索调度 (区别于传统搜索引擎)"""
import json
import sys
import time

from . import cache
from .engines.sites import SITES


def do_site(args, cfg):
    if args.site in (None, 'list'):
        print(json.dumps(
            [{'site': k, 'desc': v['desc'], 'proxy_hint': v['proxy']} for k, v in SITES.items()],
            ensure_ascii=False, indent=1))
        return 0
    if not args.query:
        print('usage: webtool site <site> <query>', file=sys.stderr)
        return 2
    entry = SITES.get(args.site)
    if not entry:
        print(f'unknown site: {args.site}\navailable: {", ".join(SITES)}\nuse `webtool site list` for detail',
              file=sys.stderr)
        return 2

    t0 = time.time()
    ckey = f'{args.site}|{args.query}|{args.max}|{args.lang}'
    cached = None if args.no_cache else cache.get(cfg, 'search', ckey)
    if cached is not None:
        results, src = cached, 'cache'
    else:
        fn = entry['fn']
        hint = entry['proxy']
        proxy = (cfg.get('engine_proxy') or {}).get(f'site:{args.site}')
        if proxy is None:
            proxy = cfg.get('proxy') if hint == 'proxy' else cfg.get('proxy')  # auto: 全局代理, resilient 会自动降级
        if args.site == 'wikipedia' and args.lang != 'zh':
            def fn(q, limit, proxy, timeout, **kw):
                return SITES['wikipedia']['fn'](q, limit, proxy, timeout, lang=args.lang)
        try:
            results = fn(args.query, args.max, proxy, cfg.get('timeout', 15))
            cache.put(cfg, 'search', ckey, results)
            src = 'fresh'
        except Exception as e:
            print(json.dumps({'error': str(e)[:300], 'site': args.site,
                              'hint': f'可试 --proxy 或降低 -n; site list 查看可用站点'},
                             ensure_ascii=False), file=sys.stderr)
            return 1

    out = {'site': args.site, 'query': args.query, 'took_ms': int((time.time() - t0) * 1000),
           'source': src, 'total': len(results), 'results': results}
    if args.format == 'json':
        print(json.dumps(out, ensure_ascii=False, indent=1))
    else:
        for r in results:
            print(f"- {r['title']}\n  {r['url']}")
            if r.get('snippet'):
                print(f"  {r['snippet'][:140]}")
    return 0
