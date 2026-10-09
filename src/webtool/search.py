# -*- coding: utf-8 -*-
"""多引擎搜索调度"""
import json
import re
import sys
import time

from . import cache
from .adfilter import is_ad, mark_ads
from .engines.bing import search as bing_search
from .engines.sogou import search as sogou_search
from .engines.google import search as google_search
from .engines.baidu import search as baidu_search

ENGINES = {'bing': bing_search, 'sogou': sogou_search,
           'google': google_search, 'baidu': baidu_search}
# 各引擎代理建议: None=跟随全局; 'required'=必须代理; 'direct'=建议直连
ENGINE_PROXY_HINT = {'bing': 'direct', 'sogou': 'direct',
                     'google': 'required', 'baidu': 'direct'}


def do_search(args, cfg):
    """默认入口: 广告已过滤 (--no-ad 恒真, cli 层控制)"""
    return _do_search(args, cfg, filter_ad=args.no_ad)


def do_search_raw(args, cfg):
    """--keep-ad: 保留广告并标 is_ad 字段"""
    return _do_search(args, cfg, filter_ad=False)


def _do_search(args, cfg, filter_ad=True):
    t0 = time.time()
    engines = [e.strip() for e in args.engine.split(',') if e.strip()]
    results = []
    errors = []
    per_engine = {}
    ad_filtered = 0
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
            hint = ENGINE_PROXY_HINT.get(eng)
            if args.no_proxy:
                proxy = None            # 命令行指定不走代理, 最高优先
            elif eproxy is not None:
                proxy = eproxy          # 引擎级配置次之
            elif hint == 'required' and not cfg.get('proxy'):
                errors.append({'engine': eng,
                               'error': f'{eng} 需要代理: webtool proxy set <proxy> 或 --proxy'})
                continue
            else:
                proxy = cfg.get('proxy')
            try:
                rs = fn(args.query, max_results=args.max, proxy=proxy,
                        timeout=cfg.get('timeout', 15), market=args.market)
                n_ad = sum(1 for r in rs if r.get('is_ad'))
                if filter_ad:
                    rs = [r for r in rs if not r.get('is_ad')]
                    ad_filtered += n_ad
                else:
                    from .adfilter import mark_ads
                    mark_ads(rs)
                cache.put(cfg, 'search', ckey, rs)
                per_engine[eng] = 'fresh'
            except Exception as e:
                errors.append({'engine': eng, 'error': str(e)[:200]})
                continue
        results.extend([dict(r, engine=eng) for r in rs])

    # 合并: 去重 + 权重排序 (语义向量可选)
    from .merge import merge as _merge
    n_before = len(results)
    results = _merge(results, args.query,
                     use_semantic=not args.no_semantic,
                     dedupe=not args.no_dedupe)
    dedup_removed = n_before - len(results)

    if args.resolve_links:
        _resolve_sogou_links(results, cfg)

    out = {'query': args.query, 'took_ms': int((time.time() - t0) * 1000),
           'cache': per_engine, 'total': len(results), 'results': results,
           'dedup_removed': dedup_removed, 'sorted_by': 'weight(semantic)' if not args.no_semantic else 'weight'}
    if ad_filtered:
        out['ad_filtered'] = ad_filtered
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
