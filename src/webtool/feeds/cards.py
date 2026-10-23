"""feed radar 路由卡片渲染 (交互式输出走 stderr)

纯搜索只列卡片, 填参模式按 --pick 选定一条后灌参出订阅 URL。走 stderr 是
因为 cli 对 feed 用 redirect_stdout + emit, rc 非 0 时 emit 被跳过, 卡片若
走 stdout 会在出错时整段消失。
"""

import re
import sys

from webtool.feeds.fetch import (_crosscheck, _out, _pick_card, _sec_of,
                                  instance_candidates, pull_one)
from webtool.feeds.sources import load_user_feeds, save_user_feeds


def print_route_cards(cards, kw, args, cfg):
    """渲染 feed radar 的路由卡片。

    纯搜索 (无 --param/--example/--sample-row/--pick/--add) 只列卡片并提示下一步;
    填参模式用 --pick 选定一条, 实参只灌进那一条, 输出订阅 URL 并直接拉数
    渲染。参数只作用于选中项, 不改写模板, 不影响其它候选路由。
    """
    from webtool import radar as _radar

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

    # 纯搜索: 只列卡片
    if not acting:
        base = _radar.best_instance(proxy=cfg.get('proxy'))
        if kw:
            _out(f'"{kw}" 命中 {len(cards)} 条路由  (按 heat 排序, --cat 可过滤分类)')
        else:
            _out(f'分类 {args.cat} 共 {len(cards)} 条路由  (按 heat 排序)')
        _out(f'实例 {base}  (webtool feed instances 可看全部)\n')
        # 顺带探官网 feed: 官方优先, RSSHub 只在官方给不了目标栏目时才值得
        # 付实例可用性的代价 (探测有 7 天缓存)
        offs = _radar.official_feeds([c['domain'] for c in cards],
                                     proxy=cfg.get('proxy'))
        cov = _radar.official_coverage(offs.get(cards[0]['domain']), cards,
                                       from_url=getattr(args, 'from_url', None)) \
            if cards else {}
        for i, c in enumerate(cards, 1):
            _print_card(c, idx=i, base=base, official=offs.get(c['domain']),
                        coverage=cov.get(c['template']),
                        section_url=_radar.official_section_url(c))
            need = [nm for nm, o, _ in _radar.parse_params(c['template']) if not o]
            tail = f' --param {need[0]}=...' if need else ' (无需填参)'
            _out(f'  取数  --pick {i}{tail}')
        _out('\n-- --pick <序号|模板子串> 选定一条后填参取数;'
              ' --example / --sample-row N 可直接借现成路径')
        return

    # 填参: 选定一条
    idx, why = _pick_card(cards, pick)
    c = cards[idx]
    base = (getattr(args, 'instance', None)
            or _radar.best_instance(proxy=cfg.get('proxy'))).rstrip('/')
    n = max(getattr(args, 'max', 10) or 10, 3)

    _out(f'"{kw}" 命中 {len(cards)} 条路由 → 选 #{idx + 1}  ({why})')
    _out(f'实例 {base}\n')
    _print_card(c, idx=idx + 1, base=base)

    # 实参优先级: --from-url 反推值 < --param 显式值; 模板本身不动
    p2 = dict(c.get('guessed') or {})
    p2.update(params)
    if top_idx is not None:
        tfs = c['top_feeds']
        if not (1 <= top_idx <= len(tfs)):
            _out(f'\n⚠ --sample-row {top_idx} 越界 (该路由只有 {len(tfs)} 条真实样例)',
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
                  f'  或借现成路径: --example / --sample-row N', file=sys.stderr)
            return 2

    url = base + '/' + filled.lstrip('/')   # topFeeds 的 url 不保证带前导 /
    _out(f'  实参  {url}   ({src})\n')

    # 交叉校验: 官网 feed 与 RSSHub 路由都拉一遍, 比能否给出该栏目
    fetch_url, fetch_note, xc = url, '', None
    off = _radar.official_feeds([c['domain']],
                                proxy=cfg.get('proxy')).get(c['domain'])
    if off and not getattr(args, 'no_xcheck', False):
        sec_url = _radar.official_section_url(c, filled)
        section = _sec_of(sec_url) if sec_url else ''
        if not section:
            section = filled.strip('/').split('/')[-1]
        xc = _crosscheck(off, url, section, n, cfg,
                         instances=instance_candidates(
                             base, getattr(args, 'instance', None), cfg))
        if sec_url:
            _out(f"  官网  {sec_url}   (栏目页, 非 feed)")
        # 两边并发, 墙钟约等于单边耗时; 串行轮换实例会叠加超时
        _out(f"  feed    {off[0]}")
        _out(f"          {xc['official_items']} 条"
             + (f" (其中 /{section} {xc['official_hit']} 条)" if section else "")
             + f"  ·  {xc['official_ms']}ms")
        _out(f"  RSSHub  {xc['rss_instance'] or '全部实例都没出'}")
        _out(f"          {xc['rss_items']} 条  ·  {xc['rss_ms']}ms"
             f"   (并发 {xc['instances_tried']} 个实例, 墙钟 {xc['wall_ms']}ms)")
        _out(f"  校验    重叠 {xc['overlap']} 条 (一致率 {xc['consistency']:.0%})")
        _out(f"          {xc['verdict']}")
        if xc['use_official']:
            fetch_url, fetch_note = off[0], '官网 feed'
        _out()
    elif off:
        _out(f"  官网  {_radar.official_section_url(c, filled)}   (栏目页, 非 feed)")
        _out(f"  feed  {off[0]}  ({off[1]} 条)  --no-xcheck 跳过校验, "
             f'固定走 RSSHub 路由\n')

    if adding and fetch_note == '官网 feed':
        # 校验后决定用官网, 落地也存官网地址 (免得下次又被实例可用性卡住)
        name = getattr(args, 'add')[0]
        user = load_user_feeds()
        user[name] = {'url': fetch_url,
                      'desc': f"{c['site']} · {c['name']} (官方 feed)"}
        save_user_feeds(user)
        _out(f'✓ 已落 ~/.webtool/feeds.json: {name} → 官网 feed\n')
    elif adding:
        name = getattr(args, 'add')[0]
        user = load_user_feeds()
        user[name] = {'url': url, 'desc': f"{c['site']} · {c['name']} (RSSHub)"}
        save_user_feeds(user)
        _out(f'✓ 已落 ~/.webtool/feeds.json: {name}\n')

    # 直接把填好参的数据拉出来 (参数只用来取数, 不改模板)
    # 公共实例逐路由可用性不同, 所以依次换未试过的可用实例直到出数据;
    # 路由名常是一长串, 取首段清洗后当源名
    label = f"{c['site']}·{c['name']}".split(',')[0].split('、')[0].strip()
    src_name = re.sub(r'[^\w.\u4e00-\u9fff-]+', '_', label)[:28] or 'radar'
    route = {'template': c['template'], 'url': url, 'params': p2, 'via': src,
             'fetched_from': fetch_url, 'source': fetch_note or 'RSSHub',
             'crosscheck': xc, 'title': c['name'], 'site': c['site']}

    # 校验已把选中源拉下来, 复用, 不为取数再打一遍网络
    reuse = ((xc or {}).get('official_items_data')
             if (xc or {}).get('use_official')
             else (xc or {}).get('rss_items_data'))
    if reuse:
        _out(f"  取数    {fetch_note or 'RSSHub'} → {fetch_url}")
        _out(f"          复用校验结果 {len(reuse)} 条 (零额外请求);"
             f"要条目加 --items\n")
        if not getattr(args, 'items', False):
            return 0
        items = reuse[:max(getattr(args, 'max', 10) or 10, 1)]
        from webtool.render.hotrender import render_hot
        render_hot({'cmd': 'feed', 'sources': [src_name],
                    'requested': len(items), 'took_ms': (xc or {}).get('wall_ms', 0),
                    'ok': [src_name], 'failed': [], 'sources_data': {src_name: items},
                    'errors': {}, 'filtered_out': 0, 'total': len(items),
                    'route': route}, args.format)
        return 0

    if fetch_note:
        _out(f'-- 取数源: {fetch_note} {fetch_url}\n')
    tried, last_err, items = [], None, None
    cands = ([None] if fetch_note else
             instance_candidates(base, getattr(args, 'instance', None), cfg))
    # 线路一次定死: 失败只换实例, 不换线路 —— 两个维度混在一起会让"哪个实例
    # 能用"取决于它先在哪条线挂。
    # 必须写 'direct' 而不是 None: None 与 'auto' 同义 (都交规则表),
    # 写成 None 会让 --no-proxy 反而退回"跟配置走"
    px = ('direct' if getattr(args, 'no_proxy', False)
          else cfg.get('proxy') or 'auto')
    for cand in cands:
        if cand:
            tried.append(cand)
        try:
            items = pull_one(src_name, fetch_url, n, px,
                             cfg.get('timeout', 20))
        except Exception as e:
            last_err = str(e)[:120]
            continue
        if items:
            if cand and cand != base:
                _out(f'  (主实例 {base} 拉不到, 换 {cand} 成功)', file=sys.stderr)
            break
        last_err = '可达但 0 条'
    else:
        _out(f'拉取失败 ({last_err or "未知"})'
             + (f'; 已试 {len(tried)} 个实例: {", ".join(tried)}' if tried else ''),
             file=sys.stderr)
        if not fetch_note:
            _out('  用 --instance https://xxx 指定其他公共实例, 或换路由 --pick N',
                 file=sys.stderr)
        return 1
    if not items:
        _out(f'{src_name}: {fetch_note or base} 可达但 0 条'
             + ('' if fetch_note else ' (实例可能不支持该路由, 试 --instance 换)'),
              file=sys.stderr)
        return 1
    out = {'cmd': 'feed', 'sources': [src_name], 'requested': n, 'took_ms': 0,
           'ok': [src_name], 'failed': [],
           'sources_data': {src_name: items}, 'errors': {}, 'filtered_out': 0,
           'total': len(items), 'route': {'template': c['template'],
                                          'url': url, 'params': p2, 'via': src,
                                          'fetched_from': fetch_url,
                                          'source': fetch_note or 'RSSHub',
                                          'crosscheck': xc}}
    from webtool.render.hotrender import render_hot
    render_hot(out, args.format)
    return 0


def _print_card(c, idx=None, base=None, official=None, coverage=None,
                section_url=None):
    """单条路由卡片。模板行永远是原始模板 —— 填参不改写它。

    base 非空时附 URL 行: 模板形态 (占位符原样, 看得出还要填什么) + example
    形态 (可直接用), 各一行。
    """
    from webtool import radar as _radar
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
    if section_url:
        # 官网栏目页: 把 RSSHub 路径里的 "实例/<namespace>/" 换成官网域名,
        # 后段原样保留 (/36kr/newsflashes → https://www.36kr.com/newsflashes)。
        # 这是 HTML 栏目页不是 feed, 两者别混, feed 另起一行标 feed。
        _out(f"  官网  {section_url}   (栏目页, 非 feed)")
    if official:
        # 官方 feed 存在不等于覆盖该栏目, 判据是条目链接的栏目分布
        url, items, buckets = official
        secs = ' / '.join(f'{k} {v}' for k, v in
                          sorted(buckets.items(), key=lambda kv: -kv[1])[:3])
        _out(f"  feed  {url}  ({items} 条 · {secs})")
        if coverage is not None:
            hit, cnt = coverage
            if hit == '(root)':
                _out(f"        ~ 官网 feed 是全站流 ({cnt} 条), 含该栏目但没有它自己的排序")
            elif hit:
                _out(f"        ✓ 官网 feed 含该栏目 /{hit} ({cnt} 条) —— 走官网即可, 不用借实例")
            else:
                _out("        ✗ 官网 feed 不含该栏目 —— 需 RSSHub 路由 (借实例, 可能 503)")
    if base:
        b = base.rstrip('/')
        _out(f"  URL   {b}{c['template']}")
        if c['example']:
            _out(f"  直连  {b}/{c['example'].lstrip('/')}")
    _out()
