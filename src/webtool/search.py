# -*- coding: utf-8 -*-
"""多引擎搜索调度"""
import json
import re
import socket
import sys
import time

from . import cache
from .adfilter import is_ad, mark_ads
from .engines.bing import search as bing_search
from .engines.sogou import search as sogou_search
from .engines.google import search as google_search
from .engines.baidu import search as baidu_search
from .engines.marginalia import search as marginalia_search

ENGINES = {'bing': bing_search, 'sogou': sogou_search,
           'google': google_search, 'baidu': baidu_search,
           'marginalia': marginalia_search}
_PROBE_CACHE = None
def _proxy_alive(cfg, ttl=60):
    """全局代理 TCP 探活, 结果缓存 ttl 秒. 代理未配置返回 False."""
    global _PROBE_CACHE
    if not cfg.get('proxy'):
        return False
    now = time.time()
    if _PROBE_CACHE and now - _PROBE_CACHE[0] < ttl:
        return _PROBE_CACHE[1]
    from urllib.parse import urlparse
    p = urlparse(cfg['proxy'])
    try:
        s = socket.create_connection((p.hostname, p.port or 8080), timeout=1.5)
        s.close()
        ok = True
    except OSError:
        ok = False
    _PROBE_CACHE = (now, ok)
    return ok


# 各引擎代理建议: None=跟随全局; 'required'=必须代理; 'direct'=建议直连
# google: 必须代理 — 代理未配置或探活失败(进程挂/端口不通)都静默跳过, 不搜谷歌
ENGINE_PROXY_HINT = {'bing': 'direct', 'sogou': 'direct',
                     'google': 'required', 'baidu': 'direct',
                     'marginalia': 'direct'}
# 默认引擎组合: bing/sogou/baidu 三引擎 (免 key 直连, Web 检索主力);
# google 不进默认: DC 代理出口普遍被 IP 级 reCAPTCHA 拦截只剩新闻通道,
# marginalia 不进默认: 独立索引, 中文覆盖弱, 长尾补充源 (-e marginalia 显式加)
DEFAULT_ENGINES = 'bing,sogou,baidu'


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
    engines = [e.strip() for e in (args.engine or cfg.get('default_engines')
                                   or DEFAULT_ENGINES).split(',') if e.strip()]
    if args.format is None and cfg.get('default_format'):
        args.format = cfg['default_format']
    if cfg.get('cache') == 'off':
        args.no_cache = True
    errors = []
    results = []
    errors = []
    per_engine = {}
    ad_filtered = 0
    # 首轮拉取量与 -n 解耦: 多拉进池 (top n 从大池里选, 质量更高);
    # 引擎端各自有单页天花板 (bing 10 / baidu 20 / sogou 10), 超出白传无害
    _pull = max(args.max, 15)
    for eng in engines:
        fn = ENGINES.get(eng)
        if not fn:
            errors.append({'engine': eng, 'error': f'unknown engine, available: {",".join(ENGINES)}'})
            continue
        ckey = f'{eng}|{args.query}|{_pull}|{args.market}'
        cached = None if args.no_cache else cache.get(cfg, 'search', ckey)
        if cached is not None:
            rs = cached
            per_engine[eng] = 'cache'
        else:
            eproxy = (cfg.get('engine_proxy') or {}).get(eng)
            hint = ENGINE_PROXY_HINT.get(eng)
            if args.no_proxy:
                if hint == 'required':
                    continue            # --no-proxy 时 required 引擎直接跳过
                proxy = None            # 命令行指定不走代理, 最高优先
            elif eproxy is not None:
                proxy = eproxy          # 引擎级配置次之
            elif hint == 'required':
                # google: 代理未配置或探活失败 → 静默跳过 (不算 error,
                # 代理挂了不挂假错误, bing/sogou/baidu 直连照常)
                if not _proxy_alive(cfg):
                    continue
                proxy = cfg.get('proxy')
            else:
                proxy = cfg.get('proxy')
            try:
                rs = fn(args.query, max_results=_pull, proxy=proxy,
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

    # 跳转链解码: 默认开启 — 搜狗 link / baidu link / gnews articles 一律
    # 还原为原始 URL 再返回 (带并发+缓存+熔断); --no-resolve 关闭
    # 解码在黑名单/补量之前完成: ①link 包装链的真实域名只有解码后才知道,
    # 黑名单按真域判定才不漏 ②补量的粗去重按真 URL, 不重复计数
    if not getattr(args, 'no_resolve', False):
        _resolve_sogou_links(results, cfg)

    # 合并: 去重 + 黑名单 + 权重排序 (语义向量可选) + 权重阈值 + 质量闸门
    from .merge import merge as _merge
    from .blocklist import filter_blocklist, is_blocked
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

    # ---- 自动补量: 过滤后不足 requested 且有翻页能力 → 翻页补拉重过滤 ----
    # 触发条件: 总数 < args.max 且未被 --no-dedupe/--no-blocklist 关掉主过滤
    # (补拉翻页对反爬引擎是额外风险, 上限 2 页/引擎 + 页间随机延迟)
    topup_fetched = 0
    _want = args.max
    if len(results) < _want and not args.no_dedupe:
        from .topup import top_up
        seen_urls = {r.get('url') for r in results} | \
                    {r.get('url') for r in []}
        for eng in engines:
            fn = ENGINES.get(eng)
            if not fn or len(results) >= _want:
                break
            eproxy = (cfg.get('engine_proxy') or {}).get(eng)
            hint = ENGINE_PROXY_HINT.get(eng)
            if args.no_proxy:
                proxy = None
            elif eproxy is not None:
                proxy = eproxy
            elif hint == 'required':
                if not _proxy_alive(cfg):
                    continue
                proxy = cfg.get('proxy')
            else:
                proxy = cfg.get('proxy')
            extra, fetched = top_up(
                eng, fn, args.query, _want, min(_want, len(results)),
                proxy, cfg.get('timeout', 15), args.market,
                filter_ad=filter_ad,
                is_blocked_fn=(None if args.no_blocklist
                               else lambda u, _b=(), _a=(): is_blocked(
                                   u, extra_block=_b, extra_allow=_a)))
            topup_fetched += fetched
            # 补来的先解码: 引擎翻页给的是 link 包装链 (baidu/sogou),
            # 不解码则黑名单按包装域误判、粗去重按包装 URL 重复计数
            if extra and not getattr(args, 'no_resolve', False):
                _resolve_sogou_links(extra, cfg)
            # 补来的进同一合并管线 (dedupe 会在下一轮统一做, 这里先粗去重)
            for r in extra:
                if r.get('url') not in seen_urls:
                    seen_urls.add(r.get('url'))
                    results.append(dict(r, engine=eng))
        if topup_fetched:
            # 补量后重新排序去重, 保持输出质量一致
            n_before = len(results)
            results = _merge(results, args.query,
                             use_semantic=not args.no_semantic,
                             dedupe=not args.no_dedupe)
            dedup_removed += n_before - len(results)
            if not args.no_blocklist:
                results, nb2 = filter_blocklist(
                    results, extra_block=args.block or (),
                    extra_allow=args.allow or ())
                n_blocked += nb2

    # 最终截断: 排序后取质量最高的 n 条 (多引擎大池 → top n, 硬上限语义)
    if len(results) > args.max:
        results = results[:args.max]

    # 质量诊断: 结果集与 query 整体脱节 → 输出 query 优化建议 (不自动改写,
    # 自动改词可能引入歧义, 改写权在用户; 这里只做检测 + 提醒)
    quality_hint = None
    if not args.no_semantic and not args.no_retry and _low_quality(results):
        from .qhint import build_hint
        quality_hint = build_hint(args.query, results)

    # 跳转链解码: 默认开启 — 搜狗 link / baidu link / gnews articles 一律
    # 还原为原始 URL 再返回 (带并发+缓存+熔断); --no-resolve 关闭
    if not getattr(args, 'no_resolve', False):
        _resolve_sogou_links(results, cfg)

    out = {'query': args.query, 'took_ms': int((time.time() - t0) * 1000),
           'cache': per_engine, 'total': len(results), 'results': results,
           'dedup_removed': dedup_removed, 'blocked_by_blocklist': n_blocked,
           'sorted_by': 'weight(semantic)' if not args.no_semantic else 'weight'}
    if topup_fetched:
        out['topup'] = {'fetched': topup_fetched,
                        'note': '翻页补拉(最多2页/引擎)'}
        out['requested'] = _want
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
            elif hint == 'required' and not _proxy_alive(cfg):
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
    """跳转链批量解码成原始 URL: 搜狗 /link + baidu /link + gnews articles"""
    from urllib.parse import urlparse
    from .engines.sogou import resolve_link as _sogou_resolve
    from .engines.baidu import _resolve_one as _baidu_resolve
    from .engines.google import resolve_link as _google_resolve
    import concurrent.futures as cf

    def _kind(u):
        n = urlparse(u).netloc + u
        if 'sogou.com/link' in n:
            return 'sogou'
        if 'baidu.com/link?' in n:
            return 'baidu'
        if 'news.google.com' in n and '/articles/' in n:
            return 'gnews'
        return None

    todo = [(i, r, _kind(r['url'])) for i, r in enumerate(results)]
    todo = [x for x in todo if x[2]]
    if not todo:
        return
    timeout = cfg.get('timeout', 15)

    def work(item):
        i, r, kind = item
        real = cache.get(cfg, 'resolve', r['url'])
        if not real:
            eproxy = (cfg.get('engine_proxy') or {}).get(kind)
            proxy = eproxy if eproxy is not None else cfg.get('proxy')
            if kind == 'sogou':
                real = _sogou_resolve(r['url'], proxy=proxy, timeout=timeout)
            elif kind == 'baidu':
                real = _baidu_resolve(r['url'], proxy=proxy, timeout=timeout)
            else:
                real = _google_resolve(r['url'], proxy=proxy, timeout=timeout)
            if real:
                cache.put(cfg, 'resolve', r['url'], real)
        return i, real

    with cf.ThreadPoolExecutor(5) as ex:
        for i, real in ex.map(work, todo):
            if real and real != results[i]['url']:
                results[i]['url'] = real
                results[i]['resolved'] = True
            elif not real:
                results[i]['resolved'] = False
