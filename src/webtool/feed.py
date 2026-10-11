# -*- coding: utf-8 -*-
"""webtool feed: RSS/Atom 订阅源聚合 (热点追踪的另一半: 榜单看热度, feed 看时序)

用法:
  webtool feed list                     内置预设源清单 + 用法
  webtool feed                          拉默认预设源 (PRESET_FEEDS), 按源分组原序
  webtool feed sspai ithome             指定预设源
  webtool feed <任意RSS/Atom URL>       直接订阅任意 feed
  webtool feed ithome sspai -q "汽车"   语义筛选 (BM25 本地筛 + 按相关度重排)
  webtool feed --add NAME URL           用户自定义源 (存 ~/.webtool/feeds.json)

与 rank 的分工:
- rank: 热榜/趋势型源 (站点自己算好热度, 数据"此刻在热什么"), 短 TTL 缓存
- feed: 订阅型源 (按发布时间排序的时序流, 数据"最近发了什么"), 适合持续追踪

解析: 纯标准库 xml.etree (零依赖), 兼容 RSS 2.0 / Atom; 条目字段统一为
{rank, title, url, snippet, date, source}; 连通策略同 rank (直连→探活代理)。
"""
import json
import os
import re
import sys
import time
import urllib.parse
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed

from . import cache
from . import feedhealth
from .engines.sites import _fetch
from .rank import _proxy_ok


def _clean(s):
    """去 HTML 标签, 折叠空白 (与 engines.hotsites._clean 同逻辑)"""
    s = re.sub(r'<[^>]+>', '', s or '')
    return re.sub(r'\s+', ' ', s).strip()

PRESET_FEEDS = {
    'sspai':    {'url': 'https://sspai.com/feed',              'desc': '少数派文章'},
    'ithome':   {'url': 'https://www.ithome.com/rss/',          'desc': 'IT之家资讯 (60条)'},
    'ifanr':    {'url': 'https://www.ifanr.com/feed',           'desc': '爱范儿'},
    'ruanyifeng': {'url': 'https://www.ruanyifeng.com/blog/atom.xml', 'desc': '阮一峰科技爱好者周刊'},
    'cnode':    {'url': 'https://cnodejs.org/rss',              'desc': 'CNode 社区'},
    'github_blog': {'url': 'https://github.blog/feed/',         'desc': 'GitHub Blog'},
    'v2ex':     {'url': 'https://www.v2ex.com/index.xml',       'desc': 'V2EX 全站新帖'},
}
DEFAULT_FEED_SOURCES = ['sspai', 'ithome', 'ifanr', 'ruanyifeng', 'github_blog']

FEEDS_FILE = os.path.expanduser('~/.webtool/feeds.json')
FEED_STATE_FILE = os.path.expanduser('~/.webtool/feed_state.json')


def _load_user_feeds():
    """用户自定义源: ~/.webtool/feeds.json {name: {url, desc}}"""
    try:
        with open(FEEDS_FILE, 'r', encoding='utf-8') as f:
            d = json.load(f) or {}
        return {k: (v if isinstance(v, dict) else {'url': v}) for k, v in d.items()}
    except Exception:
        return {}


def _save_user_feeds(d):
    os.makedirs(os.path.dirname(FEEDS_FILE), exist_ok=True)
    with open(FEEDS_FILE, 'w', encoding='utf-8') as f:
        json.dump(d, f, ensure_ascii=False, indent=2)


# ============================================================ 解析 (纯标准库)

_NS = {
    'atom': 'http://www.w3.org/2005/Atom',
    'content': 'http://purl.org/rss/1.0/modules/content/',
}


def _strip_cdata(s):
    return re.sub(r'^<!\[CDATA\[|\]\]>$', '', (s or '').strip())


def _text_of(el, *paths):
    """按优先级取子元素 text (含 CDATA 清洗)"""
    for p in paths:
        x = el.find(p, _NS)
        if x is not None and (x.text or '').strip():
            return _strip_cdata(x.text)
    return ''


def parse_feed(txt, source_name=''):
    """RSS 2.0 / Atom 统一解析 → [{rank,title,url,snippet,date}]"""
    # 清理可能导致解析失败的垃圾 (xml 声明前杂质)
    i = txt.find('<?xml')
    if i > 0:
        txt = txt[i:]
    items = []
    try:
        root = ET.fromstring(txt.encode('utf-8'))
    except ET.ParseError:
        # 容错: 去 <script>/<style> 再试
        txt2 = re.sub(r'<(script|style)[^>]*>.*?</\1>', '', txt, flags=re.S | re.I)
        try:
            root = ET.fromstring(txt2.encode('utf-8'))
        except ET.ParseError:
            raise RuntimeError('feed 解析失败: 非 RSS/Atom XML')
    # ---- Atom ----
    if root.tag.endswith('feed'):
        for e in root.findall('atom:entry', _NS):
            title = _text_of(e, 'atom:title', 'title')
            link = ''
            for l in e.findall('atom:link', _NS):
                if not l.get('rel') or l.get('rel') == 'alternate':
                    link = l.get('href') or ''
                    break
            if not link:
                link = _text_of(e, 'atom:link', 'link')
            snippet = _clean(_text_of(e, 'atom:summary', 'atom:content', 'content:encoded', 'summary'))[:160]
            date = _text_of(e, 'atom:published', 'atom:updated', 'published', 'updated')
            if title:
                items.append({'title': title, 'url': link, 'snippet': snippet, 'date': date})
    # ---- RSS 2.0 / 0.9x ----
    else:
        for ch in root.iter():
            if ch.tag.rsplit('}', 1)[-1] == 'item':
                title = _text_of(ch, 'title')
                link = _text_of(ch, 'link', 'atom:link', 'guid')
                snippet = _clean(_text_of(ch, 'description', 'content:encoded', 'content'))[:160]
                date = _text_of(ch, 'pubDate', 'atom:published', 'dc:date')
                if title:
                    items.append({'title': title, 'url': link, 'snippet': snippet, 'date': date})
    for i, x in enumerate(items):
        x['rank'] = i + 1
        if source_name:
            x['source'] = source_name
    return items


# ============================================================ 拉取

def pull_one(name, url, n, proxy, timeout):
    """拉单个 feed → 条目列表 (原序=发布时序; 头走 transport 统一指纹)"""
    from .engines.sites import _headers
    headers = _headers(url, 'nav', {
        'Accept': 'application/rss+xml, application/atom+xml, '
                  'application/xml, text/xml, */*'})
    txt, st, _ = _fetch(url, proxy, timeout, headers)
    return parse_feed(txt, name)[:n]


def _resolve_proxy(cfg, no_proxy):
    """直连优先 → 失败且全局代理可用则代理重试 (探活复用 rank 的 _proxy_ok)"""
    def once(p):
        def _pull(item):
            nm, spec = item
            return nm, pull_one(nm, spec['url'], spec['_n'], p, cfg.get('timeout', 15))
        return _pull
    return once


def do_feed(args, cfg):
    t0 = time.time()
    # ---- feed --add NAME URL [desc] / --del NAME ----
    if getattr(args, 'add', None) and len(args.add) >= 2:
        user = _load_user_feeds()
        user[args.add[0]] = {'url': args.add[1],
                             'desc': args.add[2] if len(args.add) > 2 else ''}
        _save_user_feeds(user)
        print(f'feed 源已保存: {args.add[0]} -> {args.add[1]}  ({FEEDS_FILE})',
              file=sys.stderr)
        return 0
    if getattr(args, 'del_src', None):
        user = _load_user_feeds()
        if args.del_src not in user:
            if args.del_src in PRESET_FEEDS:
                print(f'"{args.del_src}" 是内置预设源, 不可删除 (自定义源才可删)',
                      file=sys.stderr)
            else:
                print(f'自定义源 "{args.del_src}" 不存在; 现有: '
                      f'{", ".join(sorted(user)) or "(无)"}', file=sys.stderr)
            return 2
        desc = user.pop(args.del_src)
        _save_user_feeds(user)
        print(f'feed 源已删除: {args.del_src} ({desc.get("url")})', file=sys.stderr)
        return 0
    # ---- feed --mark KEY [URL] NOTE: 人工登记坏源 ----
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
        user = _load_user_feeds()
        if not url and key in user:
            url = user[key].get('url')
        e = feedhealth.manual(key, url, note)
        print(f'已登记: {key} [{e.get("status")}] {note}', file=sys.stderr)
        return 0
    # ---- feed --retest KEY|all: 复查登记的坏源, 恢复即移除 ----
    if getattr(args, 'retest', None):
        rows = dict(feedhealth.entries())
        targets = rows if args.retest == 'all' else {
            k: v for k, v in rows.items() if k == args.retest}
        if args.retest != 'all' and not targets:
            print(f'登记表中无 "{args.retest}"; 现有: '
                  f'{", ".join(rows) or "(空)"}', file=sys.stderr)
            return 2
        gproxy = cfg.get('proxy')

        def _probe(k, v):
            try:
                items = pull_one(k, v['url'], 3, None, 12)
                return k, ('ok' if items else 'empty'), len(items), None
            except Exception as e1:
                try:
                    items = pull_one(k, v['url'], 3, gproxy, 12)
                    return k, ('ok' if items else 'empty'), len(items), None
                except Exception:
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
    # ---- feed health: 查看健康登记表 ----
    if len(args.sources) == 1 and args.sources[0] == 'health':
        print(feedhealth.render_text())
        return 0
    # ---- feed radar <关键词>: RSSHub Radar 规则库查可订阅路由 ----
    if len(args.sources) >= 1 and args.sources[0] == 'radar':
        from . import radar as _radar
        kw = args.sources[1] if len(args.sources) > 1 else ''
        if not kw:
            try:
                rules = _radar.load_rules(proxy=cfg.get('proxy'))
            except Exception as e:
                print(f'radar rules 载入失败: {str(e)[:160]}', file=sys.stderr)
                return 2
            sites, n = _radar.stats(rules)
            print(f'RSSHub Radar 规则库: {sites} 站点 / {n} 条可订阅路由\n')
            print('用法: webtool feed radar <关键词>  (域名/站名/路由标题模糊匹配)')
            print('示例: webtool feed radar 36kr | feed radar bilibili | feed radar 微博')
            return 0
        try:
            rules = _radar.load_rules(proxy=cfg.get('proxy'),
                                      refresh=getattr(args, 'radar_refresh', False))
        except Exception as e:
            print(f'radar rules 载入失败: {str(e)[:160]}', file=sys.stderr)
            return 2
        rows = _radar.search(rules, kw, limit=max(getattr(args, 'max', 10), 20))
        if not rows:
            print(f'radar 无 "{kw}" 命中; 试英文域名 (36kr/bilibili/weibo/ithome) 或站名',
                  file=sys.stderr)
            return 2
        for dom, site, title, target in rows:
            print(f'[{dom}] {site} | {title}')
            print(f'    {target}')
        print(f'\n-- 共 {len(rows)} 条; 实例前缀 + target 填实参即订阅 URL, 例:\n'
              f'   webtool feed --add rkw https://rsshub.rssforever.com'
              f'{rows[0][3].replace(":category", "all")}')
        return 0
    # ---- feed 无参/list: 清单+用法 (与 rank 同约定) ----
    user = _load_user_feeds()
    if (not args.sources) or \
            (len(args.sources) == 1 and args.sources[0] == 'list'):
        print(f'webtool feed 订阅源 ({len(PRESET_FEEDS)} 预设 + {len(user)} 自定义):\n')
        for k, v in PRESET_FEEDS.items():
            star = ' *' if k in DEFAULT_FEED_SOURCES else ''
            print(f'  {k:14s} {v["desc"]}{star}')
        for k, v in user.items():
            print(f'  {k:14s} {v.get("desc") or ""} (自定义) {v["url"]}')
        print('\n用法:')
        print('  webtool feed sspai ithome        指定源 (预设名或任意 RSS/Atom URL)')
        print('  webtool feed                     无参数 = 默认源(标 *), 按源分组原序')
        print('  webtool feed sspai -q "汽车"     语义筛选 (BM25 + 按相关度重排)')
        print('  webtool feed --add NAME URL      添加自定义源 (存 ~/.webtool/feeds.json)')
        print('  webtool feed --del NAME          删除自定义源 (预设源不可删)')
        print('  webtool feed NAME --new-only     增量: 只出上次之后的新条目')
        print('  webtool feed health              查看坏源登记表 (官网挂了的站)')
        print('  webtool feed --retest KEY|all    复查坏源, 恢复即移除登记')
        print('  webtool feed --mark KEY "备注"   人工登记坏源原因 (如改走 RSSHub)')
        print('  webtool feed radar <关键词>      查 RSSHub Radar 规则库 (1310 站点可订阅路由)')
        print('  通用: -n 每源条数 -f json/text/markdown -o 文件 --no-cache --no-proxy')
        print('\n* = 默认源; feed 与 rank 的分工: rank 看热度榜, feed 看时序新内容')
        return 0
    # ---- 解析源名 → url (支持直接喂 URL) ----
    user = _load_user_feeds()
    all_names = dict(PRESET_FEEDS)
    for k, v in user.items():
        all_names[k] = v
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
        gproxy = cfg.get('proxy')
        items, err = None, None
        try:
            items = pull_one(name, specs[name]['url'], n, None, cfg.get('timeout', 15))
            via = 'direct'
        except Exception as e1:
            if no_proxy_check(args, gproxy):
                return name, None, f'{str(e1)[:160]} (direct)'
            try:
                items = pull_one(name, specs[name]['url'], n, gproxy, cfg.get('timeout', 15))
                via = gproxy
            except Exception as e2:
                return name, None, f'{str(e1)[:100]}; proxy retry: {str(e2)[:100]}'
        cache.put(cfg, 'hot', ckey, items)
        return name, items, None

    def no_proxy_check(a, gproxy):
        return a.no_proxy or not gproxy

    results, errors = {}, {}
    with ThreadPoolExecutor(max_workers=min(len(names), 6)) as ex:
        futs = {ex.submit(pull, nm): nm for nm in names}
        for fu in as_completed(futs):
            nm, items, err = fu.result()
            if err:
                errors[nm] = err
                # 健康登记: 抓取失败即记录 (成功时自动消除)
                feedhealth.record(nm, specs[nm]['url'],
                                  feedhealth.classify_error(err))
            elif items:
                results[nm] = items
                feedhealth.mark_ok(nm)
            else:
                errors[nm] = 'no data'
                feedhealth.record(nm, specs[nm]['url'], 'empty')

    # ---- --new-only 增量: 对比 ~/.webtool/feed_state.json 上次已见 URL ----
    new_only = getattr(args, 'new_only', False)
    seen_state = {}
    if new_only:
        try:
            with open(FEED_STATE_FILE) as f:
                seen_state = json.load(f)
        except Exception:
            seen_state = {}
    if new_only:
        for nm in list(results):
            seen_urls = set(seen_state.get(nm) or [])
            fresh = [r for r in results[nm] if r.get('url') not in seen_urls]
            results[nm] = fresh
            if not fresh:
                del results[nm]          # 全旧: 从 ok 里剔除, 避免空组噪音
        # 更新已见状态 (合并最近 500 条 URL)
        for nm, items in results.items():
            urls = [r.get('url') for r in items if r.get('url')]
            old = list(seen_state.get(nm) or [])
            seen_state[nm] = (urls + old)[:500]
        try:
            with open(FEED_STATE_FILE, 'w') as f:
                json.dump(seen_state, f, ensure_ascii=False)
        except Exception:
            pass

    # ---- -q 语义筛选 (BM25 + 重排; 无 -q 完全原序) ----
    filtered_out = 0
    flat = []
    if q and results:
        from .merge import _semantic_scores
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
    from .hotrender import render_hot
    render_hot(out, args.format)
    return 0
