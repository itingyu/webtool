"""stock 桥接类动作: 裸 HTTP / 东财研报 / 文档 / MCP 透传 / 健康探活"""
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
import time

from webtool.stock.bridge import docs as _docs
from webtool.stock.bridge import eco as _eco
from webtool.stock.bridge import _eco_net
from webtool.stock.bridge import engine as _engine
from webtool.stock.bridge import rawapi as _raw
from webtool.stock.bridge import srv as _srv


from webtool.stock.command._actions_data import _act_data_call
from webtool.stock.command._common import _args_dict
from webtool.stock.command._common import _coerce
from webtool.stock.command._common import _http_client

def _act_eco(args, cfg):
    """生态库通用入口: akshare(1137) / tushare(134) / baostock(38) / efinance(9)

    与 api 动作的区别: 这几个库返回 DataFrame, 这里只做形状摘要 + 前几行预览,
    要全量用 --full。
    """
    if not args.method:
        raise ValueError('eco 需要 --method 指定接口名 '
                         '(webtool stock eco-search <关键词> 搜, eco-list 看全部)')
    return _eco.call(args.lib, args.method, _args_dict(args), full=args.full)

def _act_eco_search(args, cfg):
    # 关键词走位置参数 (例: webtool stock eco-search 龙虎榜), 与 api/eco 的
    # --method 是两件事 —— 后者指定要调的接口, 这里指定要搜什么
    kw = (list(args.codes or []) or [''])[0]
    try:
        hits = _eco.search(kw, lib=args.lib, limit=args.limit)
    except _eco.EcoError as e:
        raise ValueError(str(e)) from e
    return {'keyword': kw, 'count': sum(len(v) for v in hits.values()), 'libraries': hits}

def _act_eco_list(args, cfg):
    lib = args.lib or 'akshare'
    if args.method:
        out = _eco.describe(args.method, lib)
        out['count'] = len(_eco.funcs(out.get('lib') or lib))
        return out
    # funcs() 一次就是全库 dir() 扫描 (akshare 1000+ 属性), 取一次存局部变量复用,
    # 别为算 count/truncated 再扫两遍
    all_names = _eco.funcs(lib)
    total = len(all_names)
    names = all_names[:args.limit] if args.limit else all_names
    return {'library': lib, 'count': total,
            'funcs': names, 'truncated': len(names) < total}

def _act_http_get(args, cfg):
    """裸 GET —— 逆向出的 900+ 接口直接打"""
    url = (list(args.codes or []) or [''])[0] if args.codes else args.url
    if not url:
        raise ValueError('http-get 需要 URL 位置参数')
    return _http_client(args).get(url, params=_args_dict(args),
                                 referer=args.referer, encoding=args.encoding)

def _act_http_post(args, cfg):
    """裸 POST"""
    url = (list(args.codes or []) or [''])[0] if args.codes else args.url
    if not url:
        raise ValueError('http-post 需要 URL 位置参数')
    return _http_client(args).post(url, params=_args_dict(args),
                                  data=args.form or None,
                                  referer=args.referer, encoding=args.encoding)

def _act_http_rows(args, cfg):
    """裸调用 + 转表格 (--pick 取嵌套路径, 如 data.0.quote)"""
    url = (list(args.codes or []) or [''])[0] if args.codes else args.url
    if not url:
        raise ValueError('http-rows 需要 URL 位置参数')
    h = _http_client(args)
    t = (h.post(url, params=_args_dict(args), data=args.form or None,
                referer=args.referer, encoding=args.encoding)
         if args.method == 'POST'
         else h.get(url, params=_args_dict(args), referer=args.referer,
                    encoding=args.encoding))
    df = h.rows(t, pick=args.pick, limit=args.limit)
    if args.raw:
        return {'shape': list(df.shape), 'columns': list(df.columns),
                'records': df.head(args.limit or 10).to_dict('records')}
    return df

def _act_em_report(args, cfg):
    """东财 datacenter 取数 (自动带 token, 排序列名从 docs-report 查)"""
    rn = (list(args.codes or []) or [''])[0] if args.codes else args.method
    if not rn:
        raise ValueError('em-report 需要 reportName (如 RPT_LICO_FN_CPD)')
    kw = _args_dict(args)
    h = _http_client(args)
    t = h.em_datacenter(rn, filter_expr=kw.pop('filter', None) or kw.pop('f', None),
                        columns=kw.pop('columns', 'ALL'),
                        sort=kw.pop('sort', None),
                        sort_types=kw.pop('sort_types', None),
                        page_size=int(kw.pop('page_size', 50) or 50),
                        page=int(kw.pop('page', 1) or 1))
    if args.raw:
        recs = h.records(t)
        return {'count': len(recs), 'pages': h.pages(t),
                'columns': list(recs[0].keys()) if recs else [],
                'records': recs[:args.limit or 10]}
    return h.rows(t, limit=args.limit)

def _act_em_reports(args, cfg):
    """列出/搜索东财 reportName 配方 (不联网, 读 data/reverse/em_recipes.json)"""
    from webtool.stock.bridge import em
    kw = (list(args.codes or []) or [''])[0] if args.codes else args.method
    # 条数只认 -n/--limit。旧写法对 str 调 .pop('limit'), 关键词里含 "limit"
    # 子串 (如 limit-up) 直接 AttributeError
    return em.list_reports(kw or '', limit=args.limit)

def _act_em_run(args, cfg):
    """按配方取数: 入参名沿用 akshare, filter/sort/columns/分页全自动"""
    from webtool.stock.bridge import em
    rn = (list(args.codes or []) or [''])[0] if args.codes else args.method
    if not rn:
        raise ValueError('em-run 需要 reportName, 如 RPT_DAILYBILLBOARD_DETAILSNEW\n'
                         'webtool stock em-reports 龙虎榜 看可用的 reportName')
    kw = _args_dict(args)
    pages = int(kw.pop('pages', 1) or 1)
    # 传 Http 实例本身 (em.run 只用 .get/.json), 不传 h._http —— Http 上没有
    # 这个属性, 旧写法 hasattr 恒 False → em.run 内部另建默认 Http(timeout=20),
    # --http-timeout 被静默丢弃
    r = em.run(rn, max_pages=pages, http=_http_client(args), **kw)
    if args.raw:
        return {'reportName': rn, 'func': r['func'], 'rows': r['rows'],
                'filter_sent': r['filter_sent'],
                'columns': list(r['df'].columns),
                'records': r['df'].head(args.limit or 10).to_dict('records')}
    return r['df']

def _act_em_ctype(args, cfg):
    """探测东财 companyType (F10 必需, 不探测就返占位符)"""
    sym = (list(args.codes or []) or [''])[0] if args.codes else 'SH600519'
    return {'symbol': sym, 'companyType': _http_client(args).em_f10_company_type(sym)}

def _act_docs_books(args, cfg):
    """逆向文档分册清单"""
    return _docs.books()

def _act_docs_stats(args, cfg):
    """逆向文档总量统计"""
    return _docs.stats()

def _act_docs_search(args, cfg):
    """全文检索逆向文档"""
    kw = ' '.join(c for c in (list(args.codes or []) if args.codes else []) if c) or args.keyword
    if not kw:
        raise ValueError('docs-search 需要关键词 (位置参数或 --keyword)')
    return _docs.search(kw, limit=args.limit)

def _act_docs_book(args, cfg):
    """取整个分册"""
    kw = ' '.join(c for c in (list(args.codes or []) if args.codes else []) if c) or args.keyword
    if not kw:
        raise ValueError('docs-book 需要分册关键词 (webtool stock docs-books 看清单)')
    try:
        return _docs.book(kw, max_chars=(args.limit or 20) * 3000)
    except _docs.DocsError as e:
        raise ValueError(str(e)) from e

def _act_docs_section(args, cfg):
    """取分册内匹配的章节段落"""
    kw = ' '.join(c for c in (list(args.codes or []) if args.codes else []) if c) or args.keyword
    if not kw:
        raise ValueError('docs-section 需要章节关键词')
    # 支持两种写法:
    #   docs-section 衍生品 期权        (位置参数里用空格分隔分册与章节)
    #   docs-section 衍生品,期权         (单个位置参数, 逗号/顿号分隔)
    parts = [x for x in re.split(r'[\s,，、]+', kw) if x]
    if len(parts) > 1:
        book_kw, pattern = parts[0], ' '.join(parts[1:])
    else:
        book_kw = pattern = kw
    try:
        return _docs.section(book_kw, pattern, max_chars=(args.limit or 20) * 3000)
    except _docs.DocsError as e:
        raise ValueError(str(e)) from e

def _act_docs_report(args, cfg):
    """按 reportName 取接口逆向条目"""
    kw = ' '.join(c for c in (list(args.codes or []) if args.codes else []) if c) or args.keyword
    if not kw:
        raise ValueError('docs-report 需要 reportName (如 RPT_LICO_FN_CPD)')
    try:
        return _docs.report(kw, max_chars=(args.limit or 20) * 2000)
    except _docs.DocsError as e:
        raise ValueError(str(e)) from e

def _act_docs_endpoint(args, cfg):
    """按 URL 片段反查端点出现在哪些分册"""
    kw = ' '.join(c for c in (list(args.codes or []) if args.codes else []) if c) or args.keyword
    if not kw:
        raise ValueError('docs-endpoint 需要 URL 片段')
    try:
        return _docs.endpoint(kw, max_chars=(args.limit or 20) * 2000)
    except _docs.DocsError as e:
        raise ValueError(str(e)) from e

def _act_eco_health(args, cfg):
    return _eco.health()

def _act_mcp(args, cfg):
    """直接调编排层的某个动作 —— CLI 未单独暴露的那些走这条

    定位是**逃生口**, 不是主要用法: 有对应子命令 (financials / news / flow /
    announcement / holder 等) 就用子命令, 参数校验与渲染都更完整。这里只用来
    触达 CLI 尚未单独暴露的动作。
    """
    if not getattr(args, 'tool', None):
        names = sorted(_srv.tool_names())
        raise ValueError(
            f'mcp 动作需要 --tool 指定动作名, 可用: {", ".join(names[:6])} ... '
            f'(完整清单: webtool stock tools)')
    params = {}
    for kv in (getattr(args, 'params', None) or ()):
        if '=' not in kv:
            raise ValueError(f'--arg 需要 k=v 形式, 收到 {kv!r}')
        k, _, v = kv.partition('=')
        params[k.strip()] = _coerce(v)
    return _srv.do_call(args.tool, params, timeout=args.timeout)

def _act_tools(args, cfg):
    return _srv.do_tools(args.keyword or '')

def _act_health(args, cfg):
    """四侧探活。任一侧不可用都照实报 unavailable, 不因为一侧挂了就不查另一侧"""
    out = {'engine': {}, 'orchestrator': {}, 'raw': {}}
    out['engine']['installed'] = _engine.available()
    if out['engine']['installed']:
        t0 = time.time()
        try:
            q = _engine.do_quote(['600519'])
            hit = next((x for x in q if x.get('ok')), None)
            out['engine'].update(ok=bool(hit), took_ms=int((time.time() - t0) * 1000),
                                 probe='quote 600519', sample=hit.get('name') if hit else None)
        except Exception as e:                              # noqa: BLE001
            out['engine'].update(ok=False, err=f'{type(e).__name__}: {e}')
    else:
        out['engine']['err'] = ('stock engine (业务脚本层) 缺失, 应随包安装在 '
                                'webtool/stock/engine/')

    out['orchestrator']['found'] = _srv.available()
    if out['orchestrator']['found']:
        t0 = time.time()
        try:
            _srv.call('stock_health_check', {})
            out['orchestrator'].update(
                ok=True, took_ms=int((time.time() - t0) * 1000),
                actions=len(_srv.tool_names()), module=_srv.ORCHESTRATE_MOD)
        except Exception as e:                              # noqa: BLE001
            out['orchestrator'].update(ok=False, err=f'{type(e).__name__}: {e}')
    else:
        out['orchestrator']['err'] = ('编排层模块缺失, 应随包安装在 '
                                      f'webtool/stock/{_srv.ORCHESTRATE_MOD}')
    out['raw'] = {}
    out['raw']['found'] = _raw.available()
    if out['raw']['found']:
        out['raw'].update(ok=True, methods=len(_raw.methods()))
    else:
        out['raw']['err'] = ('数据源池不可用, 应随包安装在 '
                             'webtool/stock/bridge/sources/')
    out['eco'] = _eco.health()
    # 出网路由: 各通道都要过规则表, 体检要能一眼看出某条脱管了
    out['route'] = {
        'sources': 'per-request (net.transport + RoutedCffiSession)',
        'engine': 'same as sources (engine 不出网, 取数一律经 sources)',
        'eco': {lib: _eco_net.probe(lib)
                for lib in ('akshare', 'tushare', 'baostock', 'efinance')},
        'probe': _route_probe(),
    }
    out['ok'] = bool(out['engine'].get('ok') or out['orchestrator'].get('ok'))
    return out

def _route_probe():
    """规则表对一个典型数据源域名的实际决策 —— 让用户能确认配置生效了"""
    from webtool.stock.bridge.sources import _routing
    return {u: _routing.resolve(u)
            for u in ('https://push2.eastmoney.com/',
                      'https://stock.xueqiu.com/',
                      'https://qt.gtimg.cn/')}

def _old_api(args):
    """旧 `api <方法名>` 语义: codes 位置参数给方法名"""
    name = (list(args.codes) or [''])[0]
    args.codes = []
    args.method = name
    return _act_data_call(args, None)

