"""stock data 域动作: 接口目录查询与裸调用 (data-*)"""
"""webtool stock 子命令: 动作分发 + 输出渲染

两座桥 (bridge/engine.py 脚本层 / bridge/srv.py 编排层) 在这里汇合成一个扁平的动作表。动作分三类:

    数据动作  quote pool check calendar flow news announcement financials
              analyze screen risk            —— 走 engine 脚本层
    透传动作  mcp <tool>                     —— 按名调用 24 个动作 (未单独暴露的那些)
    元动作   tools health                    —— 能力清单与两侧探活

输出与 webtool 其他数据命令一致: 数据动作按 args.format 自己渲染 (json 全字段 /
text 行内可读 / markdown 表格), 走 cli.app._run 的 emit 落盘通道。

口径纪律 (从 stock-master 继承, 现由 engine 维护):
  - 接口返回 0/空 不当正常值, 由各桥透传 status, 渲染时显式标注
  - 北向资金不可用必须显式 ⚠, 不填 0
  - 池/榜单类结果必带数据日 (date), 涨停池尤其 —— 接口对无效日期会静默回旧数据
"""
import re

from webtool.stock.bridge import docs as _docs
from webtool.stock.bridge import eco as _eco
from webtool.stock.bridge import _eco_net
from webtool.stock.bridge import rawapi as _raw


from webtool.stock.command._common import _DATA_DOMAINS
from webtool.stock.command._common import _args_dict
from webtool.stock.command._common import _http_client

def _act_api(args, cfg):
    """通用入口: 调数据源层任一方法 (24 个动作未覆盖的能力)"""
    return _raw.call(args.method, _args_dict(args))

def _act_api_list(args, cfg):
    """数据源层方法清单。--by function 给功能维度 (回答"要干什么"),
    默认按数据源分组 (回答"哪个站")。"""
    if (getattr(args, 'by', '') or 'source') == 'function':
        groups = _raw.methods_by_function()
        return {'count': len(_raw.methods()), 'by': 'function',
                'categories': {k: {'desc': v['desc'],
                                   'primary': v['primary'],
                                   'fallback': v['fallback']}
                               for k, v in groups.items()}}
    ms = _raw.methods_by_source()
    return {'count': sum(len(v) for v in ms.values()),
            'by': 'source',
            'by_source': {k: len(v) for k, v in ms.items()},
            'methods': ms}

def _act_api_search(args, cfg):
    """按功能类或关键词找接口。

    Agent 的真实问题不是"有哪些方法"而是"查财报该调哪个" —— 分类表解决
    功能维度, 关键词解决 docstring 里的口语说法 (利润表/资产负债表/十大股东)。
    """
    kw = ' '.join(list(args.codes or [])).strip() or (args.keyword or '').strip()
    if not kw:
        raise ValueError('api-search 需要关键词或功能类 '
                         '(webtool stock api-list --by function 看全部功能类)')
    cats = _raw.categories()
    # 先按类码/中文标签/别名精确命中 —— 给的是"财报""利润表"这类口语说法时
    # 直接列该类。必须优先于下面的模糊搜, 否则"财报"会因为公告资讯的 desc
    # 里含"财报日历"而先命中错的那一类。
    hit = _raw.by_alias(cats, kw)
    if hit is not None:
        # 精确命中也要带 keyword/by, 否则渲染层分不出是"类命中"还是"方法命中"
        return {'keyword': kw, 'by': 'category', 'count': 1,
                'categories': _raw.methods_by_function(hit['code'])}
    hits = {}
    for code, c in cats.items():
        if code == 'uncategorized':
            continue
        blob = ' '.join([code, c['label'], c['desc'], *c['alias'],
                         *c['primary'], *c['fallback']]).lower()
        if kw.lower() in blob:
            hits[c['label']] = {'code': code, 'desc': c['desc'],
                                'primary': c['primary'], 'fallback': c['fallback']}
    # 功能类没命中就落到方法级关键词 (docstring 里有口语说法)
    method_hits = []
    if not hits:
        for m in _raw.methods():
            d = _raw.method_doc(m) or {}
            blob = f'{m} {d.get("doc", "")}'.lower()
            if kw.lower() in blob:
                cat = _raw.category_of(m)
                method_hits.append({'method': m, 'category': cat,
                                    'sig': d.get('sig', ''), 'doc': d.get('doc', '')})
    if not hits and not method_hits:
        raise ValueError(f'没匹配 "{kw}"。可用功能类: '
                         + ', '.join(f'{c["label"]}({k})' for k, c in cats.items()
                                     if k != 'uncategorized'))
    out = {'keyword': kw, 'count': len(hits) or len(method_hits)}
    if hits:
        out['by'] = 'category'
        out['categories'] = hits
    else:
        out['by'] = 'method'
        out['methods'] = method_hits[:args.limit] if args.limit else method_hits
        out['truncated'] = bool(args.limit) and len(method_hits) > args.limit
    return out

def _data_search_all(kw, lib, limit):
    """在四类目录里同时搜, 按命中数排来源。任何一层坏了只记 err 不拖垮全局。"""
    out = {'keyword': kw, 'sources': {}}
    total = 0
    # 生态库: 接口名 + 中文 docstring
    try:
        hits = _eco.search(kw, lib=lib, limit=limit)
        n = sum(len(v) for v in hits.values())
        out['sources']['eco'] = {'count': n, 'hits': hits}
        total += n
    except Exception as e:                                  # noqa: BLE001
        out['sources']['eco'] = {'error': f'{type(e).__name__}: {e}'}
    # 数据源层 154 方法: 分类别名 + docstring
    try:
        cats = _raw.categories()
        hit = _raw.by_alias(cats, kw)
        if hit is not None:
            ms = list(hit['primary']) + list(hit['fallback'])
            out['sources']['api'] = {'count': len(ms), 'category': hit,
                                     'methods': ms}
            total += len(ms)
        else:
            idx = _raw.methods_by_source()
            found = {m: f"{src}" for src, ms in idx.items() for m in ms
                     if kw.lower() in m.lower()}
            if found:
                out['sources']['api'] = {'count': len(found), 'methods': found}
                total += len(found)
    except Exception as e:                                  # noqa: BLE001
        out['sources']['api'] = {'error': f'{type(e).__name__}: {e}'}
    # 东财配方 (离线)
    try:
        from webtool.stock.bridge import em as _em
        reps = _em.list_reports(kw, limit=limit)
        n = reps.get('count') or 0
        if n:
            out['sources']['em'] = {'count': n, 'reports': reps}
            total += n
    except Exception as e:                                  # noqa: BLE001
        out['sources']['em'] = {'error': f'{type(e).__name__}: {e}'}
    out['count'] = total
    return out

def _data_domain_names():
    return list(_DATA_DOMAINS)

def _act_data_find(args, cfg):
    """data find <关键词>: 四类目录一次搜 (eco/api/em/docs), 结果带来源

    域内搜索 (data 行情 find 茅台): eco 结果按该域正则过滤, 结果标注 domain。
    """
    kw = ' '.join(list(args.codes or [])).strip() or (args.keyword or '').strip()
    if not kw:
        raise ValueError('data find 需要关键词, 例: webtool stock data find 龙虎榜')
    out = _data_search_all(kw, args.lib, args.limit or 10)
    # 域内搜索: 过滤 eco 结果到本域
    dom = getattr(args, '_data_domain', None)
    if dom and dom in _DATA_DOMAINS and 'eco' in out.get('sources', {}):
        pat = _DATA_DOMAINS[dom][2]
        eco_src = out['sources']['eco']
        hits = eco_src.get('hits') or {}
        eco_src['hits'] = {lib: [f for f in fs if re.search(pat, f)]
                           for lib, fs in hits.items()}
        eco_src['count'] = sum(len(v) for v in eco_src['hits'].values())
        eco_src['domain'] = dom
        out['count'] = eco_src['count']
    # 逆向文档检索收尾补上 (独立于 _data_search_all, docs 接口是分册/全文两层)
    try:
        from webtool.stock.bridge import docs as _docs
        out['sources']['docs'] = {'count': len(_docs.books()),
                                  'hint': 'docs 全文检索: webtool stock docs-search '
                                          f'{kw}'}
    except Exception as e:                                  # noqa: BLE001
        out['sources']['docs'] = {'error': f'{type(e).__name__}: {e}'}
    return out

def _act_data_call(args, cfg):
    """data call <名称>: 按名路由到 api 方法 / eco 接口 / em 配方

    路由顺序: em 配方 (RPT_ 前缀或配方表命中) → 数据源层方法 (精确命中)
    → 生态库接口。--lib 强制生态库; --full 只对 eco 生效。
    """
    name = args.method or ((list(args.codes) or [''])[0] if args.codes else '')
    if not name:
        raise ValueError('data call 需要接口/方法名; 不知道叫什么先 '
                         'webtool stock data find <关键词>')
    kw = _args_dict(args)
    if (getattr(args, 'lib', None) or '') not in ('', 'akshare'):
        return _eco.call(args.lib, name, kw, full=args.full)
    # em 配方: RPT_ 前缀一眼定, 其余名字查配方表
    from webtool.stock.bridge import em as _em
    if name.upper().startswith('RPT_'):
        pages = int(kw.pop('pages', 1) or 1)
        r = _em.run(name, max_pages=pages, http=_http_client(args), **kw)
        if args.raw:
            return {'reportName': name, 'func': r['func'], 'rows': r['rows'],
                    'columns': list(r['df'].columns),
                    'records': r['df'].head(args.limit or 10).to_dict('records')}
        return r['df']
    # 数据源层方法精确命中 → api 语义
    if name in _raw.methods():
        return _raw.call(name, kw)
    # 其余落生态库 (报错信息里给出最近的候选, 引导用 data find)
    return _eco.call(args.lib or 'akshare', name, kw, full=args.full)

def _act_data_url(args, cfg):
    """data url <URL>: 裸 HTTP 直调, 合并原 http-get/post/rows

    --post 走 POST (--form 给表单); 默认 GET。返回默认转表格 (--raw 给 JSON)。
    """
    url = (list(args.codes or []) or [''])[0] if args.codes else args.url
    if not url:
        raise ValueError('data url 需要 URL; 用法: webtool stock data url <URL> [--post]')
    h = _http_client(args)
    kw = dict(params=_args_dict(args), referer=args.referer, encoding=args.encoding)
    if args.post:
        t = h.post(url, data=args.form or None, **kw)
    else:
        t = h.get(url, **kw)
    if args.method_only:
        return t
    # 非 JSON 响应 (腾讯行情这类 var xxx="a~b~c") 原样返回, 不硬转表格
    if not args.post and not t.lstrip()[:1] in '{[':
        return t
    df = h.rows(t, pick=args.pick, limit=args.limit)
    if args.raw:
        return {'shape': list(df.shape), 'columns': list(df.columns),
                'records': df.head(args.limit or 10).to_dict('records')}
    return df

def _data_domain_overview(dom, limit=15):
    """单域导航: 该域下 api / eco / em 各有哪些接口 (限量预览)"""
    desc, cat, pat = _DATA_DOMAINS[dom]
    out = {'domain': dom, 'desc': desc, 'sources': {}}
    # api 层: 按功能分类 (cat 是分类 code, 如 quote/financial)
    try:
        c = _raw.categories().get(cat)
        if c:
            ms = list(c['primary']) + list(c['fallback'])
            out['sources']['api'] = {'count': len(ms), 'methods': ms[:limit]}
    except Exception as e:                                  # noqa: BLE001
        out['sources']['api'] = {'error': f'{type(e).__name__}: {e}'}
    # eco 层: 按接口名正则 (akshare 为主); '其他' 是兜底域 = 全集减去已归类域
    try:
        fs = _eco.funcs('akshare')
        if dom == '其他':
            claimed = set()
            for d2, (_d, _c, p2) in _DATA_DOMAINS.items():
                if d2 != '其他':
                    claimed.update(f for f in fs if re.search(p2, f))
            hit = [f for f in fs if f not in claimed]
        else:
            hit = [f for f in fs if re.search(pat, f)]
        out['sources']['eco_akshare'] = {'count': len(hit),
                                         'funcs': hit[:limit]}
    except Exception as e:                                  # noqa: BLE001
        out['sources']['eco_akshare'] = {'error': f'{type(e).__name__}: {e}'}
    # em 配方: 复用全域搜
    try:
        from webtool.stock.bridge import em as _em
        reps = _em.list_reports(dom, limit=limit)
        n = reps.get('count') or 0
        if n:
            out['sources']['em'] = {'count': n, 'reports': reps}
    except Exception as e:                                  # noqa: BLE001
        out['sources']['em'] = {'error': f'{type(e).__name__}: {e}'}
    out['usage'] = {
        f'data {dom} find 关键词': '域内再搜',
        f'data {dom} call 接口名': '域内调用 (同 data call 路由)',
    }
    return out

def _act_data_list(args, cfg):
    """data list [域|eco|api|em]: 按域或按层列清单

    data list            → 12 个功能域导航 (每域多少接口)
    data list 行情        → 该域下 api/eco/em 明细
    data list api|eco|em → 按层 (旧行为)
    """
    what = (args.method or (list(args.codes) or [''])[0] or '').lower()
    if what in _DATA_DOMAINS:
        args.codes = list(args.codes)[1:]
        return _data_domain_overview(what, args.limit or 15)
    if not what:
        # 域总览: 每域 api+eco 接口数; '其他' 用差集 (兜底域不重复计数)
        eco_fs = _eco.funcs('akshare')
        claimed = set()
        rows = {}
        for dom, (desc, _cat, pat) in _DATA_DOMAINS.items():
            if dom == '其他':
                eco_n = len(eco_fs) - len(claimed)
            else:
                hit = set(f for f in eco_fs if re.search(pat, f))
                claimed |= hit
                eco_n = len(hit)
            rows[dom] = {'desc': desc, 'eco_akshare': eco_n}
        return {'domains': rows,
                'note': 'data list <域> 看明细; 也可跨域: data find 关键词'}
    what = what or 'eco'
    if what in ('api', 'source', 'sources'):
        ms = _raw.methods_by_source()
        return {'layer': 'api', 'count': sum(len(v) for v in ms.values()),
                'by_source': {k: len(v) for k, v in ms.items()}, 'methods': ms}
    if what == 'em':
        from webtool.stock.bridge import em as _em
        return _em.list_reports((args.keyword or ''), limit=args.limit)
    lib = args.lib or ('akshare' if what in ('eco', 'akshare') else what)
    if args.method:                      # 给了接口名 → describe
        out = _eco.describe(args.method, lib)
        out['count'] = len(_eco.funcs(out.get('lib') or lib))
        return out
    all_names = _eco.funcs(lib)
    names = all_names[:args.limit] if args.limit else all_names
    return {'layer': 'eco', 'library': lib, 'count': len(all_names),
            'funcs': names, 'truncated': len(names) < len(all_names)}

def _act_data(args, cfg):
    """data 主动作: 按第二个词分发 (find/call/url/list/health), 无词给导航

    webtool stock data                 → 导航
    webtool stock data find 龙虎榜      → 四类目录一次搜
    webtool stock data call stock_zh_a_hist --arg symbol=600519
    webtool stock data url <URL> [--post]
    webtool stock data list api|eco|em
    webtool stock data health
    """
    codes = list(args.codes) if args.codes else []
    sub = (codes[0] if codes else '').lower()
    subs = {'find': _act_data_find, 'call': _act_data_call, 'url': _act_data_url,
            'list': _act_data_list, 'health': _act_data_health}
    if sub in subs:
        args.codes = codes[1:]
        if sub == 'find' and not args.keyword:
            args.keyword = ' '.join(args.codes)
            args.codes = []
        if sub == 'list' and args.method is None and args.codes:
            args.method = args.codes[0]
            args.codes = args.codes[1:]
        return subs[sub](args, cfg)
    # 第二词是功能域 → 域内路由
    if codes and codes[0] in _DATA_DOMAINS:
        dom, rest = codes[0], codes[1:]
        sub2 = (rest[0] if rest else '').lower()
        args._data_domain = dom
        args.codes = rest[1:] if sub2 in ('find', 'call', 'url') else rest
        if sub2 == 'find':
            args.keyword = args.keyword or ' '.join(args.codes)
            args.codes = []
            return _act_data_find(args, cfg)
        if sub2 == 'call':
            return _act_data_call(args, cfg)
        if sub2 == 'url':
            return _act_data_url(args, cfg)
        # 无子动词 → 域导航
        return _data_domain_overview(dom, args.limit or 15)
    return _data_nav()

def _data_nav():
    """data 主动作: 域总览导航 (与 data list 无参同源, 差集兜底防重计)"""
    eco_fs = _eco.funcs('akshare')
    claimed = set()
    domains = {}
    for dom, (desc, _c, pat) in _DATA_DOMAINS.items():
        if dom == '其他':
            eco_n = len(eco_fs) - len(claimed)
        else:
            hit = set(f for f in eco_fs if re.search(pat, f))
            claimed |= hit
            eco_n = len(hit)
        domains[dom] = {'desc': desc, 'eco': eco_n}
    return {
        'usage': {
            'data list': '域总览 (每域接口数)',
            'data list <域>': '域内明细 (api 分类 + eco 接口 + em 配方)',
            'data <域> find <关键词>': '域内搜, 例: data 行情 find 茅台',
            'data find <关键词>': '跨域一次搜 eco/api/em/docs',
            'data call <名称>': '按名调 (em 配方 → api 方法 → eco 接口)',
            'data url <URL>': '裸 HTTP 直调, 反爬已内置',
            'data health': '数据面体检',
        },
        'domains': domains,
        'counts': {'eco_akshare': len(eco_fs), 'api': len(_raw.methods())},
        'note': '不知道接口叫什么 → data <域> 或 data find; '
                '知道名字 → data call; 都封装不了 → data url',
    }

def _act_data_health(args, cfg):
    """data health: 数据面体检 (数据源层 / 生态库 / 逆向文档)"""
    return {
        'api': {'ok': _raw.available(), 'methods': len(_raw.methods())},
        'eco': _eco.health(),
        'em_recipes': {'ok': bool(_docs.stats().get('books')), 'books': _docs.stats()},
        'route': {'sources': 'per-request (net.transport + RoutedCffiSession)',
                  'eco': {lib: _eco_net.probe(lib)
                          for lib in ('akshare', 'tushare', 'baostock', 'efinance')}},
    }

