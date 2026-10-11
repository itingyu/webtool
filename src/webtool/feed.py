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

# 随包分发的精选源种子 (~/.webtool/feeds.json 不存在时自动落盘)
SEED_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         'data', 'feeds.seed.json')


def _load_seed_feeds():
    """随包精选源: data/feeds.seed.json {name: {url, desc}}"""
    try:
        with open(SEED_FILE, 'r', encoding='utf-8') as f:
            d = json.load(f) or {}
    except Exception:
        return {}
    return {k: (v if isinstance(v, dict) else {'url': v}) for k, v in d.items()}


def _seed_user_feeds(user):
    """把 seed 里用户还没有的源并入 ~/.webtool/feeds.json。

    只增不覆盖: 用户 --add/--del 过的同名项以用户版本为准, seed 更新也不会
    抹掉本地改动。写盘失败一律静默 —— 种子只是便利, 挂了不该让命令报错。
    """
    seed = _load_seed_feeds()
    added = [k for k in seed if k not in user]
    if not added:
        return user
    merged = dict(seed)
    merged.update(user)          # 用户同名项优先
    try:
        _save_user_feeds(merged)
    except Exception:
        return user
    return merged


def _load_user_feeds():
    """用户自定义源: ~/.webtool/feeds.json {name: {url, desc}}"""
    try:
        with open(FEEDS_FILE, 'r', encoding='utf-8') as f:
            d = json.load(f) or {}
        user = {k: (v if isinstance(v, dict) else {'url': v}) for k, v in d.items()}
    except Exception:
        user = {}
    return _seed_user_feeds(user)


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


def _instance_candidates(preferred, explicit, cfg):
    """拉数用的实例候选顺序: 显式指定 > 当前最快可用 > 其余可用。

    探活只验了一条路由, 不代表该实例支持所有路由 (实测 hub.slanker 跑
    /36kr/newsflashes 正常但 /36kr/hot-list 503), 所以要多备几个。
    """
    from . import radar as _radar
    alive = [it['instance'].rstrip('/') for it in
             _radar.instances(proxy=cfg.get('proxy')) if it['ok']]
    out = []
    for x in (explicit.rstrip('/') if explicit else None, preferred, *alive):
        if x and x not in out:
            out.append(x)
    return out


def _out(*a, **kw):
    """路由卡片的说明性输出走 stderr。

    cli 对 feed 走 redirect_stdout + emit, rc 非 0 时 emit 被跳过 —— 卡片若走
    stdout 就会在出错时整段消失。真正的数据输出仍由 render_hot 写 stdout。
    """
    kw.setdefault('file', sys.stderr)
    print(*a, **kw)


def _pick_card(cards, pick):
    """按 --pick 选路由: 纯数字=列表序号(1起), 其它=模板/站名/路由名子串匹配"""
    if not pick:
        if len(cards) == 1:
            return 0, '唯一命中'
        # 多条命中且没指定: 取 heat 最高的, 并说明其余怎么换
        best = max(range(len(cards)), key=lambda i: cards[i]['heat'])
        others = [str(i + 1) for i in range(len(cards)) if i != best]
        return best, (f'未指定 --pick, 自动选 #{best + 1} (heat 最高); '
                      f'换别的用 --pick <{" / ".join(others)}>')
    s = str(pick).strip()
    if s.isdigit():
        i = int(s) - 1
        if not (0 <= i < len(cards)):
            raise SystemExit(f'--pick {s} 越界 (共 {len(cards)} 条)')
        return i, f'--pick {s}'
    hits = [i for i, c in enumerate(cards)
            if s.lower() in c['template'].lower()
            or s.lower() in (c['name'] or '').lower()]
    if not hits:
        raise SystemExit(f'--pick "{s}" 没匹配到任何路由')
    if len(hits) > 1:
        raise SystemExit(f'--pick "{s}" 命中多条 (#{" / ".join(str(i + 1) for i in hits)}), '
                         f'给序号更明确')
    return hits[0], f'--pick {s}'


def _print_route_cards(cards, kw, args, cfg):
    """渲染 feed radar 的路由卡片。

    两种模式:
      纯搜索 (无 --param/--example/--top/--pick/--add): 只列卡片, 模板原样,
        带序号, 提示下一步怎么填参。
      填参 (有上述任一): --pick 选定**一条**路由 → 卡片模板照原样打印 →
        实参只灌进那一条 → 给出订阅 URL → 直接把该 URL 的数据拉出来渲染。
        参数只作用于选中项, 不会改写模板, 也不影响其它候选路由。
    """
    from . import radar as _radar

    params = {}
    for kv in (getattr(args, 'param', None) or []):
        if '=' not in kv:
            _out(f'--param 需要 K=V 形式, 收到 "{kv}"', file=sys.stderr)
            raise SystemExit(2)
        k, v = kv.split('=', 1)
        params[k.strip()] = v.strip()

    use_example = getattr(args, 'example', False)
    top_idx = getattr(args, 'top', None)
    adding = bool(getattr(args, 'add', None))
    pick = getattr(args, 'pick', None)
    acting = bool(params) or use_example or top_idx is not None or adding or pick

    # ---- 纯搜索: 只列卡片 ----
    if not acting:
        base = _radar.best_instance(proxy=cfg.get('proxy'))
        _out(f'"{kw}" 命中 {len(cards)} 条路由  (按 heat 排序, --cat 可过滤分类)')
        _out(f'实例 {base}  (webtool feed instances 可看全部)\n')
        # 顺带探一下这些站有没有官方 feed: 官方优先, RSSHub 只在官方给不了
        # 目标栏目时才值得付实例可用性的代价 (探测有 7 天缓存)
        offs = _radar.official_feeds([c['domain'] for c in cards],
                                     proxy=cfg.get('proxy'))
        cov = _radar.official_coverage(offs.get(cards[0]['domain']), cards,
                                       from_url=getattr(args, 'from_url', None)) \
            if cards else {}
        for i, c in enumerate(cards, 1):
            _print_card(c, idx=i, base=base, official=offs.get(c['domain']),
                        coverage=cov.get(c['template']))
            need = [nm for nm, o, _ in _radar.parse_params(c['template']) if not o]
            tail = f' --param {need[0]}=...' if need else ' (无需填参)'
            _out(f'  取数  --pick {i}{tail}')
        _out('\n-- --pick <序号|模板子串> 选定一条后填参取数;'
              ' --example / --top N 可直接借现成路径')
        return

    # ---- 填参: 选定一条 ----
    idx, why = _pick_card(cards, pick)
    c = cards[idx]
    base = (getattr(args, 'instance', None)
            or _radar.best_instance(proxy=cfg.get('proxy'))).rstrip('/')
    n = max(getattr(args, 'max', 10) or 10, 3)

    _out(f'"{kw}" 命中 {len(cards)} 条路由 → 选 #{idx + 1}  ({why})')
    _out(f'实例 {base}\n')
    _print_card(c, idx=idx + 1, base=base)

    # 实参: --from-url 反推值 < --param 显式值; 模板本身不动
    p2 = dict(c.get('guessed') or {})
    p2.update(params)
    if top_idx is not None:
        tfs = c['top_feeds']
        if not (1 <= top_idx <= len(tfs)):
            _out(f'\n⚠ --top {top_idx} 越界 (该路由只有 {len(tfs)} 条真实样例)',
                  file=sys.stderr)
            raise SystemExit(2)
        filled, src = tfs[top_idx - 1]['path'], f'topFeeds #{top_idx}'
    elif use_example and c['example']:
        filled, src = c['example'], '官方 example'
    else:
        try:
            filled = _radar.fill_path(c['template'], p2, strict=True)
            src = '参数'
        except _radar.MissingParams as e:
            miss = ' '.join(nm for nm, _ in e.missing)
            _out(f'\n⚠ 还缺必填参数: {miss}', file=sys.stderr)
            _out(f'  补上: --param {miss.split()[0]}=... '
                  f'  或借现成路径: --example / --top N', file=sys.stderr)
            return 2

    url = base + '/' + filled.lstrip('/')   # topFeeds 的 url 不保证带前导 /
    _out(f'  实参  {url}   ({src})\n')

    if adding:
        name = getattr(args, 'add')[0]
        user = _load_user_feeds()
        user[name] = {'url': url, 'desc': f"{c['site']} · {c['name']} (RSSHub)"}
        _save_user_feeds(user)
        _out(f'✓ 已落 ~/.webtool/feeds.json: {name}\n')

    # ---- 直接把填好参的数据拉出来 (参数只是用来取数, 不改模板) ----
    # 公共实例是逐路由挑活的 (探活只验 /36kr/newsflashes, 别的路由可能 503),
    # 所以这里不只试一个实例: 依次换未试过的可用实例, 直到出数据
    # 路由名常是一长串 ("资讯, 快讯, 用户文章, ..."), 拿来当源名没法看
    label = f"{c['site']}·{c['name']}".split(',')[0].split('、')[0].strip()
    src_name = re.sub(r'[^\w.\u4e00-\u9fff-]+', '_', label)[:28] or 'radar'
    tried, last_err = [], None
    for cand in _instance_candidates(base, getattr(args, 'instance', None), cfg):
        tried.append(cand)
        for px in ([None] + ([cfg.get('proxy')] if cfg.get('proxy') else [])):
            try:
                items = pull_one(src_name, url, n, px, cfg.get('timeout', 20))
            except Exception as e:
                last_err = str(e)[:120]
                continue
            if items:
                if cand != base:
                    _out(f'  (主实例 {base} 拉不到, 换 {cand} 成功)', file=sys.stderr)
                break
            last_err = '可达但 0 条'
        else:
            continue
        break
    else:
        _out(f'拉取失败 ({last_err or "未知"}); 已试 {len(tried)} 个实例: '
             f'{", ".join(tried)}', file=sys.stderr)
        _out('  用 --instance https://xxx 指定其他公共实例, 或换路由 --pick N',
             file=sys.stderr)
        return 1
    if not items:
        _out(f'{src_name}: 可达但 0 条 (实例可能不支持该路由, 试 --instance 换)',
              file=sys.stderr)
        return 1
    out = {'cmd': 'feed', 'sources': [src_name], 'requested': n, 'took_ms': 0,
           'ok': [src_name], 'failed': [],
           'sources_data': {src_name: items}, 'errors': {}, 'filtered_out': 0,
           'total': len(items), 'route': {'template': c['template'],
                                          'url': url, 'params': p2, 'via': src}}
    from .hotrender import render_hot
    render_hot(out, args.format)
    return 0


def _print_card(c, idx=None, base=None, official=None, coverage=None):
    """单条路由卡片。模板行永远是原始模板 —— 填参不改写它。

    base 非空时附 URL 行: 模板形态 (占位符原样, 看得出还要填什么) + example
    形态 (可直接用), 各一行。
    """
    from . import radar as _radar
    feat = c.get('features') or {}
    warn = []
    if feat.get('antiCrawler'):
        warn.append('反爬')
    if feat.get('requirePuppeteer'):
        warn.append('需 Puppeteer')
    if feat.get('requireConfig'):
        warn.append('需配置')
    head = f"#{idx} " if idx else ''
    _out(f"{head}{c['site']} · {c['name'] or '(未命名)'}"
          f"  heat={c['heat']}  {'⚠ ' + '/'.join(warn) if warn else ''}")
    _out(f"  模板  {c['template']}")
    if c['params']:
        # parameters 的键是裸名, 可选性只能从模板解析 (path 里 ':name?' 才算选填)
        opt_map = {n: o for n, o, _ in _radar.parse_params(c['template'])}
        for pk, pv in c['params'].items():
            name = pk.split('{')[0].rstrip('?')
            desc = pv.get('description') if isinstance(pv, dict) else str(pv)
            default = pv.get('default') if isinstance(pv, dict) else None
            tail = f" (默认 {default})" if default else ''
            _out(f"  参数  {name}{'(选填)' if opt_map.get(name) else '(必填)'}"
                  f" — {(desc or '').strip()[:66]}{tail}")
    if c['example']:
        _out(f"  示例  {c['example']}")
    for i, tf in enumerate(c['top_feeds'][:3], 1):
        _out(f"  样例{i} {tf['title'][:38]:40s} {tf['site_url'][:52]}")
    if c.get('guessed'):
        _out('  反推  ' + ', '.join(f'{k}={v}' for k, v in c['guessed'].items()))
    if official:
        # 官网 feed 与 RSSHub 路由不是替代关系, 关键是"官网给不给得了这个栏目":
        # 官网稳、无限流、不依赖实例, 但只含它自己的栏目。判据 = 官网 feed 条目
        # 链接的栏目分布 vs 该路由的目标栏目 (36氪官网 feed 含 newsflashes 20 条,
        # 所以快讯不必借 RSSHub; 反之 /p 栏目它就不含)。
        url, items, buckets = official
        secs = ' / '.join(f'{k} {v}' for k, v in
                          sorted(buckets.items(), key=lambda kv: -kv[1])[:3])
        _out(f"  官网  {url}  ({items} 条 · {secs})")
        if coverage is not None:
            hit, cnt = coverage
            if hit == '(root)':
                _out(f"        ~ 官网 feed 是全站流 ({cnt} 条), 含该栏目但没有它自己的排序")
            elif hit:
                _out(f"        ✓ 官网 feed 含该栏目 /{hit} ({cnt} 条) —— 走官网即可, 不用借实例")
            else:
                _out(f"        ✗ 官网 feed 不含该栏目 —— 需 RSSHub 路由 (借实例, 可能 503)")
    if base:
        b = base.rstrip('/')
        _out(f"  URL   {b}{c['template']}")
        if c['example']:
            _out(f"  直连  {b}/{c['example'].lstrip('/')}")
    _out()


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
    # ---- feed instances: 公共实例探活 ----
    if len(args.sources) == 1 and args.sources[0] == 'instances':
        from . import radar as _radar
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
    # ---- feed radar [--from-url URL | <关键词>]: 查 RSSHub 路由库, 填参出订阅 URL ----
    if len(args.sources) >= 1 and args.sources[0] == 'radar':
        from . import radar as _radar
        kw = args.sources[1] if len(args.sources) > 1 else ''
        from_url = getattr(args, 'from_url', None)
        try:
            routes = _radar.load_routes(proxy=cfg.get('proxy'),
                                        refresh=getattr(args, 'radar_refresh', False))
        except Exception as e:
            print(f'路由库载入失败: {str(e)[:200]}\n'
                  f'  (docs.rsshub.app 直连超时, 需配代理: webtool proxy set http://127.0.0.1:2080)',
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
        return _print_route_cards(cards, kw, args, cfg)
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
        print('  webtool feed radar <关键词>      查 RSSHub 路由库 (2069 站 / 3947 路由, 带参数说明)')
        print('  webtool feed instances             探活公共实例 (哪几个今天还活着)')
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
