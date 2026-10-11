# -*- coding: utf-8 -*-
"""webtool rank: 榜单聚合 + 可选语义筛选 (榜单类命令的唯一入口)

用法:
  webtool rank list                 榜单清单 + 用法
  webtool rank zhihu weibo          指定榜单, 按源分组原序输出 (榜单位次=真实热度)
  webtool rank -q "刹车"            语义筛选: 纯榜源本地 BM25 筛 + 跨源按相关度重排
  webtool rank zhihu -q "AI" -t 0   -t 0 = 只重排不过滤; 无 -q = 原序不重排

与 `site` 的分工: rank 只管榜单型源 (热榜/趋势); site 是关键词站内搜索。
榜单源定义在 engines/hotsites.py (HOT_SITES), 支持搜索的源 (-q 透传站内过滤)
标 search: True, 不支持的标 False → rank 拉全榜后本地 BM25 语义筛选。

连通策略: 能直连直连; 直连失败且配置了全局代理 → 探活代理, 可用则代理重试。
"""
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from . import cache
from .engines.hotsites import HOT_SITES, DEFAULT_HOT_SOURCES

# 代理探活结果缓存 (进程内): {proxy_url: True/False}, 避免每源都探一遍
_proxy_alive = {}


def _proxy_ok(proxy, timeout=6):
    """探活: HEAD https://www.bing.com/generate_204 经代理可达即视为可用"""
    if not proxy:
        return False
    if proxy in _proxy_alive:
        return _proxy_alive[proxy]
    ok = False
    try:
        from .probe import head_probe
        ok = bool(head_probe(proxy, timeout))
    except Exception:
        ok = False
    _proxy_alive[proxy] = ok
    return ok


def _pull_once(name, n, q, proxy, timeout):
    """按代理策略拉一次榜: 无代理=直连, 有代理=走代理"""
    fn = HOT_SITES[name]['fn']
    return fn(q or '', n, proxy, timeout)


def _resolve(name, n, q, cfg, no_proxy):
    """直连优先 → 失败且全局代理可用则代理重试。返回 (items, error)"""
    timeout = cfg.get('timeout', 15)
    gproxy = cfg.get('proxy')
    try:
        items = _pull_once(name, n, q, None, timeout)
        if items:
            return items, None
        err1 = 'empty'
    except Exception as e:
        err1 = str(e)[:200]
    if no_proxy or not gproxy or not _proxy_ok(gproxy):
        return None, f'{err1} (direct)'
    try:
        items = _pull_once(name, n, q, gproxy, timeout)
        if items:
            return items, None
        return None, f'{err1}; proxy retry empty (via {gproxy})'
    except Exception as e:
        return None, f'{err1}; proxy retry: {str(e)[:120]} (via {gproxy})'


def _fmt_filters(d):
    parts = []
    if d.get('filtered_out'):
        parts.append(f"语义筛选剔除 {d['filtered_out']} 条 (--threshold 调阈值, 0=不过滤)")
    if not parts:
        parts = ['无过滤动作 (0 剔除)']
    return parts


def _print_sources():
    """rank list: 打印支持的热榜清单 + 用法示例"""
    print(f'webtool rank 榜单源 ({len(HOT_SITES)} 个, 默认 {len(DEFAULT_HOT_SOURCES)} 源):\n')
    dn = set(DEFAULT_HOT_SOURCES)
    for k, v in HOT_SITES.items():
        star = ' *' if k in dn else ''
        s = ' 支持-q站内' if v.get('search') else ''
        print(f'  {k:15s} {v["desc"]}{s}{star}')
    print('\n用法:')
    print('  webtool rank zhihu weibo        指定榜单 (空格分隔)')
    print('  webtool rank                    无参数 = 默认源(标 * ), 按源分组原序输出')
    print('  webtool rank -q "汽车"          语义筛选: 纯榜源本地筛 + 跨源按相关度重排')
    print('  webtool rank -q "汽车" -t 0     -t 0 = 只列清单不过滤不重排')
    print('  webtool rank github_trend -q rust   支持搜索的源直接站内查询')
    print('  通用: -n 每源条数 -f json/text/markdown --no-cache --no-proxy')
    print('\n* = 默认源; 带「支持-q站内」的源 -q 时透传站内过滤, 其余本地 BM25 筛选')


def do_rank(args, cfg):
    t0 = time.time()
    # rank / rank list: 显示榜单清单 + 用法
    if (not args.sources and not args.query) or \
            (len(args.sources) == 1 and args.sources[0] == 'list'):
        _print_sources()
        return 0
    sources = args.sources or []
    seen, unknown, names = set(), [], []
    for s in sources:
        if s not in HOT_SITES:
            unknown.append(s)
            continue
        if s not in seen:
            seen.add(s)
            names.append(s)
    if not names:
        names = list(DEFAULT_HOT_SOURCES)
    if unknown:
        print(f'unknown rank sources (skip): {", ".join(unknown)}; '
              f'可选: {", ".join(HOT_SITES)}; 无参数 = 默认 {len(DEFAULT_HOT_SOURCES)} 源',
              file=sys.stderr)
        return 2

    n = min(max(args.max, 3), 50)
    q = (args.query or '').strip()
    threshold = args.threshold

    def pull(name):
        """单源拉榜: 缓存 → 直连→代理自动降级; 返回 (items, error)"""
        ckey = f'rank|{name}|{n}|{q}'
        if not args.no_cache:
            c = cache.get(cfg, 'hot', ckey)
            if c is not None:
                return c, None
        spec = HOT_SITES[name]
        # query 分发: 支持搜索的源直接透传; 不支持的传空 (拉全榜), 后本地语义筛
        sq = q if (spec.get('search') and q) else ''
        items, err = _resolve(name, n, sq, cfg, args.no_proxy)
        if err:
            return None, err
        cache.put(cfg, 'hot', ckey, items)
        return items, None

    results, errors = {}, {}
    with ThreadPoolExecutor(max_workers=min(len(names), 6) or 1) as ex:
        futs = {ex.submit(pull, nm): nm for nm in names}
        for fu in as_completed(futs):
            nm = futs[fu]
            try:
                items, err = fu.result()
            except Exception as e:                     # 适配器内部未捕获异常兜底
                items, err = None, str(e)[:200]
            if err:
                errors[nm] = err
            elif items:
                results[nm] = items
            else:
                errors[nm] = 'no data'

    # ---------- 语义筛选/重排 ----------
    filtered_out = 0
    if q:
        # 1) 支持搜索的源已站内过滤; 不支持的源在本地做 BM25 阈值筛 (跨源统一)
        from .merge import _semantic_scores
        pool = []
        for nm in names:
            for r in results.get(nm) or []:
                r = dict(r)
                r['source'] = nm                     # 保留榜单来源标注
                pool.append(r)
        if threshold:                                # threshold > 0 才过滤
            scores = _semantic_scores(q, pool)
            kept = [r for i, r in enumerate(pool) if scores.get(i, 0) >= threshold]
            filtered_out = len(pool) - len(kept)
            if kept:
                pool = kept
            else:                                    # 全被筛掉: 回退全榜并提示
                filtered_out = 0
                print(f'warn: threshold {threshold} 筛空全榜, 回退全量',
                      file=sys.stderr)
        if threshold > 0:
            # 2) 跨源 BM25 重排 + 标注 sem_score (仅语义筛选模式)
            scores = _semantic_scores(q, pool)
            for i, r in enumerate(pool):
                r['sem_score'] = round(scores.get(i, 0.0), 3)
            pool.sort(key=lambda r: -r['sem_score'])
            for i, r in enumerate(pool):
                r['rank'] = i + 1
        else:
            # -t 0: 不过滤不重排, 按源原序 (榜单位次即真实热度位次)
            for i, r in enumerate(pool):
                r['rank'] = i + 1
        flat = pool
    else:
        flat = []

    out = {'cmd': 'rank', 'sources': names, 'requested': n,
           'query': q or None,
           'took_ms': int((time.time() - t0) * 1000),
           'ok': sorted(results), 'failed': sorted(errors),
           'sources_data': {k: results[k] for k in names if k in results},
           'errors': errors,
           'total': sum(len(v) for v in results.values())}
    if q:
        out['results'] = flat
        out['filtered_out'] = filtered_out
        out['total'] = len(flat)
    from .hotrender import render_rank
    render_rank(out, args.format, _fmt_filters(out))
    return 0
