# -*- coding: utf-8 -*-
"""多引擎搜索调度"""
import json
import re
import sys
import time

from . import cache
from .engines.bing import search as bing_search
from .engines.sogou import search as sogou_search

ENGINES = {'bing': bing_search, 'sogou': sogou_search}


def do_search(args, cfg):
    t0 = time.time()
    engines = [e.strip() for e in args.engine.split(',') if e.strip()]
    results = []
    errors = []
    per_engine = {}
    for eng in engines:
        fn = ENGINES.get(eng)
        if not fn:
            errors.append({'engine': eng, 'error': f'unknown engine, available: {",".join(ENGINES)}'})
            continue
        ckey = f'{eng}|{args.query}|{args.max}|{args.market}'
        cached = None if args.no_cache else cache.get(cfg, 'search', ckey)
        if cached is not None:
            rs = cached
            per_engine[eng] = 'cache'
        else:
            eproxy = (cfg.get('engine_proxy') or {}).get(eng)
            proxy = eproxy if eproxy is not None else cfg.get('proxy')
            try:
                rs = fn(args.query, max_results=args.max, proxy=proxy,
                        timeout=cfg.get('timeout', 15), market=args.market)
                cache.put(cfg, 'search', ckey, rs)
                per_engine[eng] = 'fresh'
            except Exception as e:
                errors.append({'engine': eng, 'error': str(e)[:200]})
                continue
        results.extend([dict(r, engine=eng) for r in rs])

    if args.resolve_links:
        _resolve_sogou_links(results, cfg)

    out = {'query': args.query, 'took_ms': int((time.time() - t0) * 1000),
           'cache': per_engine, 'total': len(results), 'results': results}
    if errors:
        out['errors'] = errors
    if args.format == 'json':
        print(json.dumps(out, ensure_ascii=False, indent=1))
    else:
        _print_text(out)
    return 0


def _print_text(out):
    for r in out['results']:
        print(f"[{r.get('engine','?')}#{r.get('rank','?')}] {r['title']}")
        print(f"    {r['url']}")
        if r.get('snippet'):
            print(f"    {r['snippet'][:150]}")
    if out.get('errors'):
        print('errors: ' + json.dumps(out['errors'], ensure_ascii=False), file=sys.stderr)


def _resolve_sogou_links(results, cfg):
    """把搜狗 /link?url= 跳转链解析成真实 URL (带 cookie 状态)"""
    from urllib.parse import urlparse
    from .engines.sogou import resolve_link
    import concurrent.futures as cf
    todo = [(i, r) for i, r in enumerate(results)
            if 'sogou.com/link' in urlparse(r['url']).netloc + r['url']]
    if not todo:
        return
    proxy = (cfg.get('engine_proxy') or {}).get('sogou') or cfg.get('proxy')
    timeout = cfg.get('timeout', 15)

    def work(item):
        i, r = item
        real = None if args_no_cache else cache.get(cfg, 'resolve', r['url'])
        if not real:
            real = resolve_link(r['url'], proxy=proxy, timeout=timeout)
            if real:
                cache.put(cfg, 'resolve', r['url'], real)
        return i, real

    args_no_cache = False  # resolve 结果有独立 7d 缓存, 无需透传
    with cf.ThreadPoolExecutor(5) as ex:
        for i, real in ex.map(work, todo):
            if real:
                results[i]['url'] = real
                results[i]['resolved'] = True
            else:
                results[i]['resolved'] = False
