# -*- coding: utf-8 -*-
"""多引擎搜索调度"""
import json
import re
import socket
import sys
import time

from . import cache
from .adfilter import is_ad, mark_ads
from .plugins import table as _plugin_table


def _engines():
    """引擎表 (name -> spec); 每次现取插件表, 清单改动即时生效"""
    return _plugin_table('engine')

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


# 各引擎代理建议来自插件清单 engine.*.params.proxy_hint:
# None=跟随全局; 'required'=必须代理; 'direct'=建议直连
# google 为 required — 代理未配置或探活失败(进程挂/端口不通)都静默跳过, 不搜谷歌
def proxy_hint(engine):
    """按插件元数据取代理策略, 未声明的引擎保守跟随全局"""
    spec = _engines().get(engine) or {}
    return spec.get('proxy_hint')


def default_engines():
    """默认引擎组合 = 清单里 enabled_by_default 为真的引擎"""
    on = [n for n, s in _engines().items() if s.get('enabled_by_default')]
    return ','.join(on) if on else 'bing,sogou,baidu'


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
                                   or default_engines()).split(',') if e.strip()]
    if args.format is None and cfg.get('default_format'):
        args.format = cfg['default_format']
    if cfg.get('cache') == 'off':
        args.no_cache = True
    errors = []
    results = []
    errors = []
    per_engine = {}
    ad_filtered = 0
    # 首轮多拉进池再选 top n; 引擎端各有单页上限, 超出无害
    _pull = max(args.max, 15)

    # 操作符路由: 每引擎按支持面拿到各自查询串; qmap 参与 cache key
    from .query_ops import apply as _apply_ops
    qmap, unsupported = _apply_ops(
        args.query, engines, getattr(args, 'operators', 'passthrough'))
    if qmap is None:                                   # --operators strict 报错
        lines = ['error: --operators strict: 以下引擎不支持查询里的操作符:']
        for name, bad in unsupported.items():
            lines.append(f'  {name}: ' + ', '.join(f'{op}:{val}' for op, val in bad))
        lines += ['', '用 --operators strip 静默剔除不支持的操作符, '
                       '或去掉这些操作符重试。']
        print('\n'.join(lines), file=sys.stderr)
        return 2
    for name, bad in unsupported.items():
        print(f'info: {name} 已剔除不支持的操作符: '
              + ', '.join(f'{op}:{val}' for op, val in bad)
              + f' → {qmap[name]!r}', file=sys.stderr)

    for eng in engines:
        spec = _engines().get(eng)
        fn = spec['fn'] if spec else None
        if not fn:
            errors.append({'engine': eng, 'error': f'unknown engine, available: {",".join(_engines())}'})
            continue
        ckey = f'{eng}|{qmap[eng]}|{_pull}|{args.market}'
        cached = None if args.no_cache else cache.get(cfg, 'search', ckey)
        if cached is not None:
            rs = cached
            per_engine[eng] = 'cache'
        else:
            eproxy = (cfg.get('engine_proxy') or {}).get(eng)
            hint = proxy_hint(eng)
            if args.no_proxy:
                if hint == 'required':
                    continue            # --no-proxy 时 required 引擎直接跳过
                proxy = None            # 命令行指定不走代理, 最高优先
            elif eproxy is not None:
                proxy = eproxy          # 引擎级配置次之
            elif hint == 'required':
                # 代理未配置或探活失败 → 静默跳过, 不算 error
                if not _proxy_alive(cfg):
                    continue
                proxy = cfg.get('proxy')
            else:
                proxy = cfg.get('proxy')
            try:
                rs = fn(qmap[eng], max_results=_pull, proxy=proxy,
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

    # 黑名单先行 (按真域拦截), 再 merge 去重排序:
    # ① 排序只算有资格留下的条目 (不白算被拦的)
    # ② quality 批内断层阈值 (cut=max(0.12, top*0.35)) 基于真实保留批,
    #    不再被即将拉黑的高 sem 头部抬高 → 标签更真实
    # 注: BM25 的 IDF 基于传入批自身, 黑名单先行会让 sem 数值随黑名单配置
    # 漂移 — 本就批内自适应, 跨配置不可比, 非回归
    from .merge import merge as _merge
    from .plugins import table as _pt
    from .blocklist import filter_blocklist, is_blocked
    # 过滤器走插件表, 顺序即优先级; blocklist 单列计数供 json 输出
    n_blocked = 0
    if not args.no_blocklist:
        n_before_bl = len(results)
        for fname, spec in _pt('filter').items():
            if fname == 'blocklist':
                kept, nb = filter_blocklist(
                    results, extra_block=args.block or (),
                    extra_allow=args.allow or ())
                n_blocked += nb
                results = kept
            else:
                results = spec['fn'](results, {'args': args, 'cfg': cfg})
    n_before = len(results)
    results = _merge(results, args.query,
                     use_semantic=not args.no_semantic,
                     dedupe=not args.no_dedupe)
    dedup_removed = n_before - len(results)

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
            spec = _engines().get(eng)
            fn = spec['fn'] if spec else None
            if not fn or len(results) >= _want:
                break
            eproxy = (cfg.get('engine_proxy') or {}).get(eng)
            hint = proxy_hint(eng)
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
                eng, fn, qmap[eng], _want, min(_want, len(results)),
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
            # 补量后重过滤+重排序: 补来的已在 top_up 内过广告+黑名单(按真域,
            # 补前已解码), 这里再整体 merge 去重排序即可
            n_before = len(results)
            results = _merge(results, args.query,
                             use_semantic=not args.no_semantic,
                             dedupe=not args.no_dedupe)
            dedup_removed += n_before - len(results)

    # 最终截断: 排序后取质量最高的 n 条 (多引擎大池 → top n, 硬上限语义)
    if len(results) > args.max:
        results = results[:args.max]

    # 跳转链解码: 默认开启 — 搜狗 link / baidu link / gnews articles 一律
    # 还原为原始 URL 再返回 (带并发+缓存+熔断); --no-resolve 关闭
    if not getattr(args, 'no_resolve', False):
        _resolve_sogou_links(results, cfg)

    # transformer 插件: 解码完成后逐条改写 (补字段/规范化/重写 url), 顺序即优先级
    from .plugins import table as _pt
    for tname, tspec in _pt('transformer').items():
        results = tspec['fn'](results, {'args': args, 'cfg': cfg})

    # 质量诊断: 结果集与 query 整体脱节 → 输出 query 优化建议 (不自动改写,
    # 自动改词可能引入歧义, 改写权在用户; 这里只做检测 + 提醒)
    quality_hint = None
    if not args.no_semantic and not args.no_retry and _low_quality(results):
        from .qhint import build_hint
        quality_hint = build_hint(args.query, results)

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

    # 引擎通道自报 + 结果证据: 降级是静默的 (429 被引擎内部 catch 换通道,
    # 不进 errors), 消费方无法从结果反推"这批是全 Web 搜索还是新闻检索"。
    # 两个来源互补: 引擎实跑时用自报 (带降级原因); 命中缓存时引擎压根没被调用,
    # 只能靠结果里的 channel 字段判定。
    ch, reasons = {}, {}
    for r in results:
        if r.get('channel'):
            for e in (r.get('engines') or [r.get('engine')]):
                if e:
                    ch.setdefault(e, r['channel'])
    if 'google' in per_engine:
        from .engines.google import last_channel as _gch
        info = _gch()
        if info.get('channel'):
            ch['google'] = info['channel']          # 自报优先 (更权威)
            if info.get('reason'):
                reasons['google'] = info['reason']
    if ch:
        out['engine_channels'] = ch
        # news 通道 = 新闻检索而非全 Web 搜索, 覆盖范围可能明显小于预期
        degraded = [f"{e} 实际走 {c} 通道(新闻检索, 非全 Web 搜索)"
                    + (f": {reasons[e]}" if reasons.get(e) else '')
                    for e, c in ch.items() if c == 'news']
        if degraded:
            out['degraded'] = degraded
    from .query_ops import describe as _describe_ops, parse as _parse_ops
    if _parse_ops(args.query).has_operators:
        out['query_operators'] = {'used': _describe_ops(args.query),
                                  'stripped': {k: [f'{op}:{v}' for op, v in vs]
                                               for k, vs in unsupported.items()},
                                  'engine_query': qmap}
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
        spec = _engines().get(eng)
        fn = spec['fn'] if spec else None
        if not fn:
            continue
        ckey = f'{eng}|{query}|{args.max}|{args.market}'
        cached = None if args.no_cache else cache.get(cfg, 'search', ckey)
        if cached is not None:
            rs = cached
        else:
            eproxy = (cfg.get('engine_proxy') or {}).get(eng)
            hint = proxy_hint(eng)
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
    """跳转链批量解码成原始 URL

    解码器与匹配规则都来自 resolver 插件表 (data/plugins.json):
    每条按 match 特征认出某种跳转链, 交给对应解码器。排序无所谓,
    匹配到就解, 与结果来自哪个引擎无关。
    """
    from .plugins import resolve_match, table as _pt

    resolvers = _pt('resolver')
    timeout = cfg.get('timeout', 15)

    todo = []
    for i, r in enumerate(results):
        kind = resolve_match(r['url'], resolvers)
        if kind:
            todo.append((i, r, kind))
    if not todo:
        return

    def work(item):
        i, r, kind = item
        real = cache.get(cfg, 'resolve', r['url'])
        if not real:
            eproxy = (cfg.get('engine_proxy') or {}).get(kind)
            proxy = eproxy if eproxy is not None else cfg.get('proxy')
            real = resolvers[kind]['fn'](r['url'], proxy=proxy, timeout=timeout)
            # 只有"真的解出了另一个 URL"才写缓存: 解码失败时解码器会把原链原样
            # 返回, 若照单全收就会把跳转链当成解码结果缓存, 之后永久短路
            if real and real != r['url']:
                cache.put(cfg, 'resolve', r['url'], real)
        return i, real

    with cf.ThreadPoolExecutor(5) as ex:
        for i, real in ex.map(work, todo):
            if real and real != results[i]['url']:
                results[i]['url'] = real
                results[i]['resolved'] = True
            elif not real:
                results[i]['resolved'] = False
