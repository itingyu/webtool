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

    # 合并: 去重 + 黑名单 + 权重排序 (语义向量可选) + 权重阈值 + 质量闸门
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

    # 质量诊断: 结果集与 query 整体脱节 → 输出 query 优化建议 (不自动改写,
    # 自动改词可能引入歧义, 改写权在用户; 这里只做检测 + 提醒)
    quality_hint = None
    if not args.no_semantic and not args.no_retry and _low_quality(results):
        from .qhint import build_hint
        quality_hint = build_hint(args.query, results)

    if args.resolve_links:
        _resolve_sogou_links(results, cfg)

    out = {'query': args.query, 'took_ms': int((time.time() - t0) * 1000),
           'cache': per_engine, 'total': len(results), 'results': results,
           'dedup_removed': dedup_removed,
           'sorted_by': 'weight(semantic)' if not args.no_semantic else 'weight'}
    if quality_hint:
        out['quality_hint'] = quality_hint
    if errors:
        out['errors'] = errors
    from .render import render
    render(out, args.format, 'search')
    return 0


def _low_quality(results, query=None):
    """质量诊断: 结果整体 sem 偏低 → query 与召回脱节

    v1.4.2 起默认不过滤, 只标注 quality + hint; 剩余条数即全部结果。
    """
    from .qhint import need_retry
    if not results:
        return False
    return need_retry({i: r.get('sem_score', 0) for i, r in enumerate(results)})


def _fetch_engines(args, cfg, engines, query, filter_ad):
    """对指定 query 跑一轮多引擎抓取 (供 site/子命令复用, 返回原始结果)"""
    rs_all, errs, ads = [], [], 0
    for eng in engines:
        fn = ENGINES.get(eng)
        if not fn:
            continue
        ckey = f'{eng}|{query}|{args.max}|{args.market}'
        cached = None if args.no_cache else cache.get(cfg, 'search', ckey)
        if cached is not None:
            rs = cached
        else:
            eproxy = (cfg.get('engine_proxy') or {}).get(eng)
            hint = ENGINE_PROXY_HINT.get(eng)
            if args.no_proxy:
                proxy = None
            elif eproxy is not None:
                proxy = eproxy
            elif hint == 'required' and not cfg.get('proxy'):
                continue
            else:
                proxy = cfg.get('proxy')
            try:
                rs = fn(query, max_results=args.max, proxy=proxy,
                        timeout=cfg.get('timeout', 15), market=args.market)
                n_ad = sum(1 for r in rs if r.get('is_ad'))
                if filter_ad:
                    rs = [r for r in rs if not r.get('is_ad')]
                    ads += n_ad
                cache.put(cfg, 'search', ckey, rs)
            except Exception as e:
                errs.append({'engine': eng, 'error': f'retry: {str(e)[:180]}'})
                continue
        rs_all.extend([dict(r, engine=eng) for r in rs])
    return rs_all, errs, ads


def _resolve_sogou_links(results, cfg):
    """把搜狗 /link?url= 跳转链解析成真实 URL (带 cookie 状态)"""
    from urllib.parse import urlparse
    from .engines.sogou import resolve_link as _sogou_resolve
    from .engines.google import resolve_link as _google_resolve
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
            real = _sogou_resolve(r['url'], proxy=proxy, timeout=timeout)
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
