"""多引擎搜索调度"""
import concurrent.futures
import sys
import time

from webtool.core import cache
from webtool.core import config_data
from webtool.core.plugins import table as _plugin_table
from webtool.filters.blocklist import filter_blocklist, is_blocked


def _engines():
    """引擎表 (name -> spec); 每次现取插件表, 清单改动即时生效"""
    return _plugin_table('engine')


def presets():
    """引擎预设表 (name -> {desc, engines}); 与引擎表同文件不同段。

    走 config_data 而不是插件注册表 —— preset 是纯数据配置, 没有 module/params
    可执行字段, 注册表那套 fn 解析用不上。同文件意味着用户覆盖
    ~/.webtool/plugins.json 时引擎与预设一起生效。
    """
    return config_data.load('presets', 'plugins.json')


def resolve_engines(args, cfg):
    """引擎优先级: --engine > --preset > cfg.default_engines > 默认开启的引擎。

    返回 (逗号串, 用的 preset 名或 None)。preset 名不存在直接退 2 —— 静默
    回退到默认组合会让用户以为跑了 A 组其实跑了 B 组。
    """
    explicit = (getattr(args, 'engine', '') or '').strip()
    if explicit:
        return ','.join(e.strip() for e in explicit.split(',') if e.strip()), None
    name = (getattr(args, 'preset', '') or '').strip()
    if name:
        spec = presets().get(name)
        if not spec:
            print(f'error: 未知 preset {name!r}, 可用: '
                  f'{", ".join(presets()) or "(无)"}', file=sys.stderr)
            raise SystemExit(2)
        engs = spec.get('engines') or []
        return ','.join(engs), name
    return cfg.get('default_engines') or default_engines(), None



def default_engines():
    """默认引擎组合 = 清单里 enabled_by_default 为真的引擎"""
    on = [n for n, s in _engines().items() if s.get('enabled_by_default')]
    return ','.join(on) if on else 'bing,sogou,baidu'


def parse_blocklist(spec):
    """--blocklist 参数 → (off, block, allow)

    语法: 逗号分隔域名; 前缀 ! 表白名单例外 (优先于黑名单); 值为 off 时
    完全关闭黑名单。替代原先的 --block/--allow/--no-blocklist 三个开关。
    """
    spec = (spec or '').strip()
    # 只在整串恰为 off 时关闭 —— 逐项小写化会让 "a.com,OFF" 里的 off
    # 变成一个黑名单域名。
    if spec.lower() in ('off', '0', 'false', 'none'):
        return True, (), ()
    blk, alw = [], []
    for part in spec.split(','):
        d = part.strip().lower()
        if not d:
            continue
        (alw if d.startswith('!') else blk).append(d.lstrip('!'))
    return False, tuple(blk), tuple(alw)


def do_search(args, cfg):
    """默认入口: 广告恒过滤 (无 --keep-ad 开关)"""
    return _do_search(args, cfg, filter_ad=True)




def _do_search(args, cfg, filter_ad=True):
    t0 = time.time()
    # 配置文件默认值 ← 命令行覆盖 (config set 的持久配置是底线, CLI 参数可临时改)
    # 只有 blocklist / market / timeout 三项读 config; 去重、BM25、广告过滤
    # 行为固定, 没有开关。
    _bl_cfg = cfg.get('blocklist') or ''
    if not args.blocklist and _bl_cfg:
        args.blocklist = _bl_cfg
    # market 由 config 提供 (config set market en-US), 不占命令行选项 ——
    # 它只对 bing 生效, 而 bing 端点恒为 cn.bing.com, setmkt 影响有限。
    market = cfg.get('market') or 'zh-CN'
    _eng_spec, _preset_used = resolve_engines(args, cfg)
    engines = [e.strip() for e in _eng_spec.split(',') if e.strip()]
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
    from webtool.pipeline.query_ops import apply as _apply_ops
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

    # 线路只由规则表决定 (netx 是唯一归一点): 这里只传用户的显式选择 ——
    # --no-proxy 就是强制直连, 其余一律 'auto' 交规则表。引擎不自报线路, 也
    # 不在这里被静默跳过。三级 (首轮抓取/补量/跳转链解码) 共用同一条。
    proxy = 'direct' if args.no_proxy else 'auto'

    for eng in engines:
        spec = _engines().get(eng)
        fn = spec['fn'] if spec else None
        if not fn:
            errors.append({'engine': eng, 'error': f'unknown engine, available: {",".join(_engines())}'})
            continue
        ckey = f'{eng}|{qmap[eng]}|{_pull}|{market}'
        cached = None if args.no_cache else cache.get(cfg, 'search', ckey)
        if cached is not None:
            rs = cached
            per_engine[eng] = 'cache'
        else:
            try:
                rs = fn(qmap[eng], max_results=_pull, proxy=proxy,
                        timeout=cfg.get('timeout', 15), market=market)
                n_ad = sum(1 for r in rs if r.get('is_ad'))
                if filter_ad:
                    rs = [r for r in rs if not r.get('is_ad')]
                    ad_filtered += n_ad
                else:
                    from webtool.filters.adfilter import mark_ads
                    mark_ads(rs)
                cache.put(cfg, 'search', ckey, rs)
                per_engine[eng] = 'fresh'
            except Exception as e:
                errors.append({'engine': eng, 'error': str(e)[:200]})
                continue
        results.extend([dict(r, engine=eng) for r in rs])

    # 跳转链解码: 无条件执行 — 搜狗 link / baidu link / gnews articles 一律
    # 还原为原始 URL (带并发+缓存+熔断)。解码必须在黑名单/补量之前完成:
    # ①link 包装链的真实域名只有解码后才知道, 黑名单按真域判定才不漏
    # ②补量的粗去重按真 URL, 不重复计数。不解码则 URL 全是 /link?url=,
    # 去重与黑名单均失效, 故不提供开关。
    _resolve_sogou_links(results, cfg, proxy)

    # 黑名单先行 (按真域拦截), 再 merge 去重排序:
    # ① 排序只算有资格留下的条目 (不白算被拦的)
    # ② quality 批内断层阈值 (cut=max(0.12, top*0.35)) 基于真实保留批 → 标签更真实
    # 注: BM25 的 IDF 基于传入批自身, 所以 sem 随黑名单配置漂移, 跨配置不可比。
    from webtool.pipeline.merge import merge as _merge
    from webtool.core.plugins import table as _pt
    # 过滤器走插件表, 顺序即优先级; blocklist 先行硬过滤。
    # 硬过滤放在算分之前: 黑名单站不该占 top n 名额, 也没必要参与去重与 BM25
    # 统计 (只会稀释 IDF 并让权重分布失真)。
    n_blocked = 0
    _off, _blk, _alw = parse_blocklist(getattr(args, 'blocklist', ''))
    for fname, spec in _pt('filter').items():
        if fname == 'blocklist':
            if not _off:
                kept, nb = filter_blocklist(results,
                                            extra_block=_blk, extra_allow=_alw)
                n_blocked += nb
                results = kept
        else:
            results = spec['fn'](results, {'args': args, 'cfg': cfg})
    stats = {'blocked': n_blocked}
    results = _merge(results, args.query,
                     use_semantic=True, dedupe=True,
                     apply_blocklist=False, stats=stats,
                     max_n=getattr(args, 'max', None))
    # dedup_removed 只算去重掉的; merge 里的剔除另由 stats 分项计数,
    # 混在一起会把 "黑名单过滤" 误报成 "重复合并"。
    dedup_removed = stats.get('dedup_removed', 0)

    # 自动补量: 过滤后不足 requested 且有翻页能力 → 翻页补拉重过滤
    # 触发条件: 总数 < args.max (去重与黑名单恒开, 无开关可关)
    # (补拉翻页对反爬引擎是额外风险, 上限 2 页/引擎 + 页间随机延迟)
    topup_fetched = 0
    _want = args.max
    if len(results) < _want:
        from webtool.pipeline.topup import top_up
        seen_urls = {r.get('url') for r in results}
        for eng in engines:
            spec = _engines().get(eng)
            fn = spec['fn'] if spec else None
            if not fn or len(results) >= _want:
                break
            extra, fetched = top_up(
                eng, fn, qmap[eng], _want, min(_want, len(results)),
                proxy, cfg.get('timeout', 15), market,
                filter_ad=filter_ad,
                is_blocked_fn=(None if _off
                               else lambda u, _b=(), _a=(): is_blocked(
                                   u, extra_block=_b, extra_allow=_a)))
            topup_fetched += fetched
            # 补来的先解码: 引擎翻页给的是 link 包装链 (baidu/sogou),
            # 不解码则黑名单按包装域误判、粗去重按包装 URL 重复计数
            if extra:
                _resolve_sogou_links(extra, cfg, proxy)
            # 补来的进同一合并管线 (dedupe 会在下一轮统一做, 这里先粗去重)
            for r in extra:
                if r.get('url') not in seen_urls:
                    seen_urls.add(r.get('url'))
                    results.append(dict(r, engine=eng))
        if topup_fetched:
            # 补量后重过滤+重排序: 补来的已在 top_up 内过广告+黑名单(按真域,
            # 补前已解码), 这里再整体 merge 去重排序即可
            results = _merge(results, args.query,
                             use_semantic=True, dedupe=True,
                             apply_blocklist=False, stats=stats,
                             max_n=getattr(args, 'max', None))
            dedup_removed += stats.get('dedup_removed', 0)

    n_blocked = stats.get('blocked', 0)
    n_floor = stats.get('floor_dropped', 0)

    # 最终截断: 排序后取质量最高的 n 条 (多引擎大池 → top n, 硬上限语义)
    if len(results) > args.max:
        results = results[:args.max]

    # transformer 插件: 解码完成后逐条改写 (补字段/规范化/重写 url), 顺序即优先级
    from webtool.core.plugins import table as _pt
    for tname, tspec in _pt('transformer').items():
        results = tspec['fn'](results, {'args': args, 'cfg': cfg})

    out = {'query': args.query, 'took_ms': int((time.time() - t0) * 1000),
           'cache': per_engine, 'total': len(results), 'results': results,
           'dedup_removed': dedup_removed, 'blocked_by_blocklist': n_blocked,
           'dropped_by_floor': n_floor,
           'weight_floor': stats.get('weight_floor', 0),
           'sorted_by': 'weight'}
    # 实际跑了哪组引擎要可观测: --preset 时不写出来, 消费方无法从结果反推
    # "这批用的是 zh 组还是我临时 --engine 拼的", 出问题也没法复现。
    if _preset_used:
        out['preset'] = _preset_used
        out['engines_used'] = engines
    if topup_fetched:
        out['topup'] = {'fetched': topup_fetched,
                        'note': '翻页补拉(最多2页/引擎)'}
        out['requested'] = _want

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
        from webtool.engines.google import last_channel as _gch
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
    from webtool.pipeline.query_ops import describe as _describe_ops, parse as _parse_ops
    if _parse_ops(args.query).has_operators:
        out['query_operators'] = {'used': _describe_ops(args.query),
                                  'stripped': {k: [f'{op}:{v}' for op, v in vs]
                                               for k, vs in unsupported.items()},
                                  'engine_query': qmap}
    if errors:
        out['errors'] = errors
    from webtool.render.render import render
    render(out, args.format, 'search')
    return 0



def _resolve_sogou_links(results, cfg, proxy='auto'):
    """跳转链批量解码成原始 URL

    解码器与匹配规则都来自 resolver 插件表 (data/plugins.json):
    每条按 match 特征认出某种跳转链, 交给对应解码器。排序无所谓,
    匹配到就解, 与结果来自哪个引擎无关。
    """
    from webtool.core.plugins import resolve_match, table as _pt

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
            # 线路沿用触发这次抓取的那条 (规则表判的), 解码器不另判一套
            real = resolvers[kind]['fn'](r['url'], proxy=proxy, timeout=timeout)
            # 只有"真的解出了另一个 URL"才写缓存: 解码失败时解码器会把原链原样
            # 返回, 若照单全收就会把跳转链当成解码结果缓存, 之后永久短路
            if real and real != r['url']:
                cache.put(cfg, 'resolve', r['url'], real)
        return i, real

    with concurrent.futures.ThreadPoolExecutor(5) as ex:
        for i, real in ex.map(work, todo):
            if real and real != results[i]['url']:
                results[i]['url'] = real
                results[i]['resolved'] = True
            elif not real:
                results[i]['resolved'] = False
