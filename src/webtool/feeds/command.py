"""feed 子命令: 源增删、路由查询、实例探活、健康登记表、多源聚合

本模块只做编排 —— 清单在 feeds.sources, 解析在 feeds.parse, 取数在
feeds.fetch, 路由卡片在 feeds.cards; 数据层出的结论 (重叠率/健康状态)
这里只负责选择分支与呈现。
"""
import re
import sys
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed

from webtool.core import cache
from webtool.core import jsonfmt
import webtool.feeds.feedhealth as feedhealth
from webtool.feeds.sources import (FEEDS_FILE, FEED_STATE_FILE,
                                   load_seed_feeds, load_user_feeds,
                                   save_user_feeds)
from webtool.net import proxyhelper
from webtool.feeds.fetch import pull_one
from webtool.feeds.cards import print_route_cards

def do_feed(args, cfg):
    t0 = time.time()
    # feed --add NAME URL [desc] / --del NAME
    if getattr(args, 'add', None) and len(args.add) >= 2:
        user = load_user_feeds()
        user[args.add[0]] = {'url': args.add[1],
                             'desc': args.add[2] if len(args.add) > 2 else ''}
        save_user_feeds(user)
        print(f'feed 源已保存: {args.add[0]} -> {args.add[1]}  ({FEEDS_FILE})',
              file=sys.stderr)
        return 0
    if getattr(args, 'del_src', None):
        user = load_user_feeds()
        if args.del_src not in user:
            if args.del_src in load_seed_feeds():
                print(f'"{args.del_src}" 是内置预设源, 不可删除 (自定义源才可删; '
                      f'不想订阅可在 feeds.json 里把 "default" 置 false 或整条删掉后用 WEBTOOL_NO_SEED=1)',
                      file=sys.stderr)
            else:
                print(f'自定义源 "{args.del_src}" 不存在; 现有: '
                      f'{", ".join(sorted(user)) or "(无)"}', file=sys.stderr)
            return 2
        desc = user.pop(args.del_src)
        save_user_feeds(user)
        print(f'feed 源已删除: {args.del_src} ({desc.get("url")})', file=sys.stderr)
        return 0
    # feed --mark KEY [URL] NOTE: 人工登记坏源
    if getattr(args, 'mark', None):
        mark = args.mark
        if len(mark) >= 2 and not mark[1].startswith('http'):
            key, url, note = mark[0], '', mark[1]
            if len(mark) >= 3:
                note = ' '.join(mark[1:])
        elif len(mark) >= 3:
            key, url, note = mark[0], mark[1], ' '.join(mark[2:])
        else:
            key, url, note = mark[0], '', ''
        user = load_user_feeds()
        if not url and key in user:
            url = user[key].get('url')
        e = feedhealth.manual(key, url, note)
        print(f'已登记: {key} [{e.get("status")}] {note}', file=sys.stderr)
        return 0
    # feed --retest KEY|all: 复查登记的坏源, 恢复即移除
    if getattr(args, 'retest', None):
        rows = dict(feedhealth.entries())
        targets = rows if args.retest == 'all' else {
            k: v for k, v in rows.items() if k == args.retest}
        if args.retest != 'all' and not targets:
            print(f'登记表中无 "{args.retest}"; 现有: '
                  f'{", ".join(rows) or "(空)"}', file=sys.stderr)
            return 2
        # 单线路: 曾经是"直连探一次, 抛异常再换代理探一次"。代理配好了还先去
        # 撞一次直连墙, 慢一倍, 而且"源恢复没恢复"取决于先在哪条线挂。线路由
        # 路由表一次决定。
        gproxy = cfg.get('proxy') or 'auto'

        def _probe(k, v):
            try:
                items = pull_one(k, v['url'], 3, gproxy, 12)
                return k, ('ok' if items else 'empty'), len(items), None
            except Exception as e1:
                return k, feedhealth.classify_error(str(e1)[:120]), 0, None

        with ThreadPoolExecutor(max_workers=min(len(targets), 6)) as ex:
            futs = [ex.submit(_probe, k, v) for k, v in targets.items()]
            for fu in as_completed(futs):
                k, st, cnt, _ = fu.result()
                if st == 'ok':
                    feedhealth.mark_ok(k)
                    print(f'✓ {k}: 已恢复 ({cnt} 条) → 从登记表移除')
                elif st == 'empty':
                    feedhealth.record(k, targets[k]['url'], 'empty')
                    print(f'· {k}: 可达但 0 条 (保留登记)')
                else:
                    feedhealth.record(k, targets[k]['url'], st)
                    print(f'✗ {k}: 仍坏 [{st}] (保留登记)')
        return 0
    # feed health: 查看健康登记表
    if len(args.sources) == 1 and args.sources[0] == 'health':
        print(feedhealth.render_text())
        return 0
    # feed instances: 公共实例探活
    if len(args.sources) == 1 and args.sources[0] == 'instances':
        from webtool import radar as _radar
        print('公共实例探活 (探测路由 %s, 缓存 1h):\n'
              % _radar._PROBE_ROUTE)
        for it in _radar.instances(proxy=cfg.get('proxy'),
                                   refresh=getattr(args, 'radar_refresh', False)):
            mark = '✓' if it['ok'] else '✗'
            detail = (f"{it['items']} 条 {it['ms']}ms" if it['ok']
                      else (it['err'] or 'unreachable'))
            print(f"  {mark} {it['instance']:34s} {detail}")
        print('\n--instance https://xxx 可指定; 默认自动挑响应最快的可用实例')
        return 0
    # feed radar [--from-url URL | <关键词>]: 查 RSSHub 路由库, 填参出订阅 URL
    if len(args.sources) >= 1 and args.sources[0] == 'radar':
        from webtool import radar as _radar
        kw = args.sources[1] if len(args.sources) > 1 else ''
        from_url = getattr(args, 'from_url', None)
        try:
            routes = _radar.load_routes(proxy=cfg.get('proxy'),
                                        refresh=getattr(args, 'radar_refresh', False))
        except Exception as e:
            print(f'路由库载入失败: {str(e)[:200]}\n'
                  '  (docs.rsshub.app 直连超时, 需配代理: webtool proxy set <代理地址>)',
                  file=sys.stderr)
            return 2
        if from_url:
            cards = _radar.from_url(routes, from_url)
            if not cards:
                # radar.source 没覆盖这个页面 (只有部分路由声明了反推规则),
                # 退回按域名/站名搜, 至少给出该站有哪些路由
                dom = re.sub(r'^https?://', '', from_url).split('/')[0]
                dom = dom[4:] if dom.startswith('www.') else dom   # 去掉 www. 再匹配
                cards = _radar.search_routes(routes, dom, limit=10)
                if not cards:
                    print(f'无路由能反推 {from_url}, 也没有 {dom} 相关路由; '
                          f'试 webtool feed radar <站名或域名>', file=sys.stderr)
                    return 2
                print(f'⚠ {from_url} 没有 radar 反推规则, 改为按域名 "{dom}" 搜索\n')
            kw = from_url
        elif not kw and not getattr(args, 'cat', None):
            sites, n_routes, n_free = _radar.routes_stats(routes)
            print(f'RSSHub 官方路由库: {sites} 站点 / {n_routes} 路由 '
                  f'({n_free} 条无需填参)\n')
            print('用法:')
            print('  webtool feed radar 36kr                    搜路由 (站名/域名/路由/参数/分类)')
            print('  webtool feed radar 36kr --pick 2           选定第 2 条 (或 --pick <模板子串>)')
            print('  webtool feed radar 36kr --pick 2 --param category=newsflashes   填参并直接拉数据')
            print('  webtool feed radar 36kr --pick 2 --example 用官方示例路径取数 (免填参)')
            print('  webtool feed radar 36kr --pick 2 --top 2   用第 2 条真实样例取数 (免填参)')
            print('  webtool feed radar --from-url https://space.bilibili.com/946974  反推路由')
            print('  webtool feed radar 36kr --pick 2 --example --add r36kr   落地成订阅源')
            print('  webtool feed instances                      看公共实例今天哪些活着')
            print('  webtool feed radar --cat finance           按分类过滤')
            print('\n填参只作用于 --pick 选中的那一条, 模板保持原样, 数据直接输出 (-f/-n 通用)')
            return 0
        else:
            cards = _radar.search_routes(
                routes, kw, limit=max(getattr(args, 'max', 10) or 10, 10),
                cat=getattr(args, 'cat', None))
            if not cards:
                print(f'路由库无 "{kw}" 命中; 试英文域名 (36kr/bilibili/weibo/ithome)、'
                      f'站名, 或 --cat <分类>', file=sys.stderr)
                return 2
        return print_route_cards(cards, kw, args, cfg)
    # feed 无参/list: 清单+用法 (与 rank 同约定)
    user = load_user_feeds()
    if (not args.sources) or \
            (len(args.sources) == 1 and args.sources[0] == 'list'):
        seed = load_seed_feeds()
        defaults = {k for k, v in seed.items() if v.get('default')}
        # 给了 -f (含 json) 就走 render 层统一分发, 清单是可机读数据不是给人看的表格
        if getattr(args, 'format', None):
            rows = [{'name': k, 'url': v.get('url', ''), 'desc': v.get('desc') or '',
                     'origin': 'seed', 'default': k in defaults}
                    for k, v in seed.items()]
            rows += [{'name': k, 'url': v.get('url', ''), 'desc': v.get('desc') or '',
                      'origin': 'custom', 'default': False}
                     for k, v in user.items() if k not in seed]
            from webtool.render.hotrender import render_feed_list
            render_feed_list({'results': rows, 'seed_count': len(seed),
                              'user_count': len(user)}, args.format)
            return 0
        print(f'webtool feed 订阅源 ({len(seed)} 预设 + {len(user)} 自定义):\n')
        for k, v in seed.items():
            star = ' *' if k in defaults else ''
            print(f'  {k:14s} {v.get("desc") or ""}{star}')
        for k, v in user.items():
            if k in seed:
                continue
            print(f'  {k:14s} {v.get("desc") or ""} (自定义) {v["url"]}')
        print('\n用法:')
        print('  webtool feed sspai ithome        指定源 (预设名或任意 RSS/Atom URL)')
        print('  webtool feed                     无参数 = 默认源(标 *), 按源分组原序')
        print('  webtool feed sspai -q "汽车"     语义筛选 (BM25 + 按相关度重排)')
        print('  webtool feed --add NAME --add URL [--add 描述]   添加自定义源 (存 ~/.webtool/feeds.json)')
        print('  webtool feed --del NAME          删除自定义源 (预设源不可删)')
        print('  webtool feed NAME --new-only     增量: 只出上次之后的新条目')
        print('  webtool feed health              查看坏源登记表 (官网挂了的站)')
        print('  webtool feed --retest KEY|all    复查坏源, 恢复即移除登记')
        print('  webtool feed --mark KEY "备注"   人工登记坏源原因 (如改走 RSSHub)')
        print('  webtool feed radar <关键词>      查 RSSHub 路由库 (2069 站 / 3947 路由, 带参数说明)')
        print('  webtool feed instances             探活公共实例 (哪几个今天还活着)')
        print('  通用: -n 每源条数 -f json/text/markdown -o 文件 --no-cache --no-proxy')
        print('\n* = 默认源; feed 与 rank 的分工: rank 看热度榜, feed 看时序新内容')
        return 0
    # 解析源名 → url (支持直接喂 URL)
    user = load_user_feeds()
    all_names = dict(user)
    if not args.sources:
        # 无参数 = 默认源: 用户文件里 default:true 的; 一个都没有则回退 seed 元数据
        args.sources = [k for k, v in user.items() if isinstance(v, dict) and v.get('default')]
        if not args.sources:
            args.sources = [k for k, v in load_seed_feeds().items() if v.get('default')]
    names, specs, unknown = [], {}, []
    for s in args.sources:
        if s in all_names:
            nm = s
            url = all_names[s].get('url') or all_names[s].get('url') or all_names[s]
        elif s.startswith('http://') or s.startswith('https://'):
            nm = 'feed:' + urllib.parse.urlparse(s).netloc
            url = s
        else:
            unknown.append(s)
            continue
        if nm not in specs:
            names.append(nm)
            specs[nm] = {'url': url, 'desc': all_names[s].get('desc') if s in all_names else ''}
    if unknown:
        print(f'unknown feed sources (skip): {", ".join(unknown)}; '
              f'可选: {", ".join(sorted(all_names))} 或任意 RSS/Atom URL', file=sys.stderr)
    if not names:
        print('无可用 feed 源; `webtool feed list` 查看清单, 或直接传 RSS/Atom URL',
              file=sys.stderr)
        return 2

    n = min(max(args.max, 3), 100)
    q = (getattr(args, 'query', None) or '').strip()
    threshold = getattr(args, 'threshold', 0.15) if q else 0.0

    def pull(name):
        ckey = f'feed|{name}|{n}|{q}'
        if not args.no_cache:
            c = cache.get(cfg, 'hot', ckey)
            if c is not None:
                return name, c, None
        # 单线路: 曾经"直连失败 → 换代理重试", 那让这条命令走哪条线取决于它先在
        # 哪失败。改为由 proxyhelper/路由表一次决定, 失败直接报错。
        px = proxyhelper.resolve(None if args.no_proxy else cfg.get('proxy'),
                                 specs[name]['url'])
        try:
            items = pull_one(name, specs[name]['url'], n, px, cfg.get('timeout', 15))
        except Exception as e:
            return name, None, str(e)[:160]
        cache.put(cfg, 'hot', ckey, items)
        return name, items, None

    results, errors = {}, {}
    with ThreadPoolExecutor(max_workers=min(len(names), 6)) as ex:
        futs = {ex.submit(pull, nm): nm for nm in names}
        for fu in as_completed(futs):
            nm, items, err = fu.result()
            if err:
                errors[nm] = err
                # 健康登记: 失败记录, 成功自动消除
                feedhealth.record(nm, specs[nm]['url'],
                                  feedhealth.classify_error(err))
            elif items:
                results[nm] = items
                feedhealth.mark_ok(nm)
            else:
                errors[nm] = 'no data'
                feedhealth.record(nm, specs[nm]['url'], 'empty')

    # --new-only 增量: 对比 ~/.webtool/feed_state.json 上次已见 URL
    new_only = getattr(args, 'new_only', False)
    seen_state = jsonfmt.read(FEED_STATE_FILE) if new_only else {}
    if new_only:
        for nm in list(results):
            seen_urls = set(seen_state.get(nm) or [])
            fresh = [r for r in results[nm] if r.get('url') not in seen_urls]
            results[nm] = fresh
            if not fresh:
                del results[nm]          # 全旧: 从 ok 里剔除
        # 已见状态保留最近 500 条 URL
        for nm, items in results.items():
            urls = [r.get('url') for r in items if r.get('url')]
            old = list(seen_state.get(nm) or [])
            seen_state[nm] = (urls + old)[:500]
        jsonfmt.write(FEED_STATE_FILE, seen_state)

    # -q 语义筛选 (BM25 + 重排; 无 -q 完全原序)
    filtered_out = 0
    flat = []
    if q and results:
        from webtool.pipeline.merge import _semantic_scores
        pool = []
        for nm in names:
            for r in results.get(nm) or []:
                r = dict(r)
                r['source'] = nm
                pool.append(r)
        scores = _semantic_scores(q, pool)
        if threshold > 0:
            kept = [r for i, r in enumerate(pool) if scores.get(i, 0) >= threshold]
            filtered_out = len(pool) - len(kept)
            if not kept:
                print(f'warn: threshold {threshold} 筛空全 feed, 回退全量', file=sys.stderr)
            else:
                pool = kept
        for i, r in enumerate(pool):
            r['sem_score'] = round(scores.get(i, 0.0), 3)
        pool.sort(key=lambda r: -r['sem_score'])
        for i, r in enumerate(pool):
            r['rank'] = i + 1
        flat = pool

    out = {'cmd': 'feed', 'sources': names, 'requested': n,
           'query': q or None, 'threshold': threshold if q else None,
           'took_ms': int((time.time() - t0) * 1000),
           'ok': sorted(results), 'failed': sorted(errors),
           'sources_data': {k: results[k] for k in names if k in results},
           'errors': errors, 'filtered_out': filtered_out,
           'total': sum(len(v) for v in results.values())}
    if flat:
        out['results'] = flat
    from webtool.render.hotrender import render_hot
    render_hot(out, args.format)
    return 0