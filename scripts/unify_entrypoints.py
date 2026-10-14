"""把 api / eco / http / em / docs 五组通用入口归一到 `data` 动作下

用户方向: "都融合到取数据里" —— 通用入口不再各自为政, 统一走
`webtool stock data <什么> ...`。原动作名保留为兼容别名 (隐藏不宣传)。

目标用法 (写进 USAGE):
  data find <关键词>              统一搜索: 一次命中 eco 接口 / api 方法 /
                                 em 配方 / docs 逆向条目, 带来源标注
  data call <名称> [--arg k=v]    统一调用: 按名称自动路由 api/eco/em,
                                 --lib 可强制生态库, --full 要全量
  data url <URL> [--post] ...     裸 HTTP 直调 (合并 http-get/post/rows)
  data list [eco|api|em]          清单 (eco 默认 akshare; --by function 同旧)
  data health                     数据面体检 (合并 api/eco/em/docs 健康)

本脚本只做代码改写: command.py 的动作表 + USAGE + cli/app.py 的 typer 参数。
改完跑 tests/test_smoke.py 验证。
"""
import pathlib
import re

ROOT = pathlib.Path('/var/minis/shared/code/webtool')
CMD = ROOT / 'src/webtool/stock/command.py'
APP = ROOT / 'src/webtool/cli/app.py'

# ---------- 1. command.py: 新增 _act_data_* ----------
DATA_ACTS = '''

# ---------- data: 通用取数入口 (融合原 api/eco/http/em/docs) ----------

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
    # 数据源层 153 方法: 分类别名 + docstring
    try:
        cats = _raw.categories()
        hit = _raw.by_alias(cats, kw)
        if hit is not None:
            grp = _raw.methods_by_function(hit['code'])
            out['sources']['api'] = {'count': grp['count'], 'category': hit,
                                     'methods': grp['methods']}
            total += grp['count']
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


def _act_data_find(args, cfg):
    """data find <关键词>: 四类目录一次搜 (eco/api/em/docs), 结果带来源"""
    kw = ' '.join(list(args.codes or [])).strip() or (args.keyword or '').strip()
    if not kw:
        raise ValueError('data find 需要关键词, 例: webtool stock data find 龙虎榜')
    out = _data_search_all(kw, args.lib, args.limit or 10)
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
    df = h.rows(t, pick=args.pick, limit=args.limit)
    if args.raw:
        return {'shape': list(df.shape), 'columns': list(df.columns),
                'records': df.head(args.limit or 10).to_dict('records')}
    return df


def _act_data_list(args, cfg):
    """data list [eco|api|em]: 各层清单 (默认 eco/akshare)"""
    what = (args.method or (list(args.codes) or ['eco'])[0] or 'eco').lower()
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


def _act_data_health(args, cfg):
    """data health: 数据面体检 (数据源层 / 生态库 / 逆向文档)"""
    from webtool.stock.bridge import docs as _docs
    return {
        'api': {'ok': _raw.available(), 'methods': len(_raw.methods())},
        'eco': _eco.health(),
        'em_recipes': {'ok': bool(_docs.stats().get('books')), 'books': _docs.stats()},
        'route': {'sources': 'per-request (RoutedAdapter + RoutedCffiSession)',
                  'eco': {lib: _eco_net.probe(lib)
                          for lib in ('akshare', 'tushare', 'baostock', 'efinance')}},
    }
'''

s = CMD.read_text(encoding='utf-8')

# 插在 _act_eco_health 之后
anchor = s.index('def _act_eco_health(args, cfg):')
end = s.index('\ndef ', anchor + 10)
s = s[:end] + DATA_ACTS + s[end:]

# ---------- 2. 动作表: data + 兼容别名 ----------
old_tbl = """    'mcp': _act_mcp, 'tools': _act_tools, 'health': _act_health,
    'api': _act_api, 'api-list': _act_api_list, 'api-search': _act_api_search,
    'holder': _act_holder, 'forecast': _act_forecast,
    'eco': _act_eco, 'eco-search': _act_eco_search,
    'eco-list': _act_eco_list, 'eco-health': _act_eco_health,
    'http-get': _act_http_get, 'http-post': _act_http_post,
    'http-rows': _act_http_rows, 'em-report': _act_em_report,
    'em-ctype': _act_em_ctype,
    'em-reports': _act_em_reports, 'em-run': _act_em_run,
    'docs-books': _act_docs_books, 'docs-stats': _act_docs_stats,
    'docs-search': _act_docs_search, 'docs-book': _act_docs_book,
    'docs-section': _act_docs_section, 'docs-report': _act_docs_report,
    'docs-endpoint': _act_docs_endpoint,
}"""
new_tbl = """    'mcp': _act_mcp, 'tools': _act_tools, 'health': _act_health,
    'holder': _act_holder, 'forecast': _act_forecast,

    # 通用取数入口 (融合原 api/eco/http/em/docs 五组)
    'data': _act_data, 'data-find': _act_data_find, 'data-call': _act_data_call,
    'data-url': _act_data_url, 'data-list': _act_data_list,
    'data-health': _act_data_health,

    # 兼容别名 → data 子动作 (隐藏不宣传, 下一大版本删)
    'api': lambda a, c: _act_data_list(a, c) if _looks_like_list(a) else _old_api(a),
    'api-list': _act_api_list, 'api-search': _act_api_search,
    'eco': _act_eco, 'eco-search': _act_eco_search,
    'eco-list': _act_eco_list, 'eco-health': _act_eco_health,
    'http-get': _act_http_get, 'http-post': _act_http_post,
    'http-rows': _act_http_rows, 'em-report': _act_em_report,
    'em-ctype': _act_em_ctype,
    'em-reports': _act_em_reports, 'em-run': _act_em_run,
    'docs-books': _act_docs_books, 'docs-stats': _act_docs_stats,
    'docs-search': _act_docs_search, 'docs-book': _act_docs_book,
    'docs-section': _act_docs_section, 'docs-report': _act_docs_report,
    'docs-endpoint': _act_docs_endpoint,
}

def _looks_like_list(args):
    return (args.method or '') in ('api', 'sources') and not (args.codes or [])


def _old_api(args):
    \"\"\"旧 `api <方法名>` 语义: codes 位置参数给方法名\"\"\"
    name = (list(args.codes) or [''])[0]
    args.codes = []
    args.method = name
    return _act_data_call(args, None)"""
assert old_tbl in s
s = s.replace(old_tbl, new_tbl)

CMD.write_text(s, encoding='utf-8')
print('command.py: 动作与实现已写入')
