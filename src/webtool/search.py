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
    # 配置文件默认值 ← 命令行覆盖 (config set 的持久配置是底线, CLI 参数可临时改)
    if args.min_weight <= 0 and cfg.get('min_weight') is not None:
        args.min_weight = float(cfg['min_weight'])
    if args.no_weight_filter and cfg.get('weight_filter') == 'off':
        args.no_weight_filter = True     # config 已 off, CLI 也要求 off → off
    if not args.no_weight_filter and cfg.get('weight_filter') == 'off' and args.min_weight <= 0:
        args.no_weight_filter = True     # config off 且 CLI 未显式开 → off
    if args.no_blocklist or cfg.get('blocklist') == 'off':
        args.no_blocklist = True
    if cfg.get('ad_filter') == 'off':
        args.keep_ad = True
    if args.no_dedupe or cfg.get('dedupe') == 'off':
        args.no_dedupe = True
    if args.no_semantic or cfg.get('semantic') == 'off':
        args.no_semantic = True
    engines = [e.strip() for e in (args.engine or cfg.get('default_engines') or 'bing,sogou').split(',') if e.strip()]
    if args.format is None and cfg.get('default_format'):
        args.format = cfg['default_format']
    if cfg.get('cache') == 'off':
        args.no_cache = True
    errors = []
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

    # 合并: 去重 + 黑名单 + 权重排序 (语义向量可选) + 权重阈值
    from .merge import merge as _merge
    from .blocklist import filter_blocklist
    n_before = len(results)
    results = _merge(results, args.query,
                     use_semantic=not args.no_semantic,
                     dedupe=not args.no_dedupe)
    dedup_removed = n_before - len(results)
    if args.no_blocklist:
        n_blocked = 0
    else:
        results, n_blocked = filter_blocklist(
            results, extra_block=args.block or (), extra_allow=args.allow or ())
    if args.min_weight > 0 and not args.no_weight_filter:
        n_low = len(results)
        results = [r for r in results if r['weight'] >= args.min_weight]
        n_low -= len(results)
    elif args.no_weight_filter or args.min_weight > 0:
        n_low = 0
    else:
        n_low = 0
        # 默认兜底: 剔除权重垫底的 15% (至少保留 3 条, 不至空手)
        if results and len(results) > 4:
            ws = sorted(r['weight'] for r in results)
            floor = ws[int(len(ws) * 0.15) - 1] if len(ws) > 3 else ws[0]
            kept = [r for r in results if r['weight'] > floor] or results[:max(3, len(results) - 2)]
            n_low = len(results) - len(kept)
            results = kept

    if args.resolve_links:
        _resolve_sogou_links(results, cfg)

    out = {'query': args.query, 'took_ms': int((time.time() - t0) * 1000),
           'cache': per_engine, 'total': len(results), 'results': results,
           'dedup_removed': dedup_removed,
           'sorted_by': 'weight(semantic)' if not args.no_semantic else 'weight'}
    out['_min_weight'] = args.min_weight
    if errors:
        out['errors'] = errors
    from .render import render
    render(out, args.format, 'search')
    return 0


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
