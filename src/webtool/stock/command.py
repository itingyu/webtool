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
import json
import re
import sys
import time

from webtool.stock.bridge import docs as _docs
from webtool.stock.bridge import http as _http
from webtool.stock.bridge import eco as _eco
from webtool.stock.bridge import _eco_net
from webtool.stock.bridge import engine as _engine
from webtool.stock.bridge import rawapi as _raw
from webtool.stock.bridge import srv as _srv


def _norm_fmt(v, default='text'):
    return v or default


def _unresolved(out):
    """检测"取数层回了但没解析出结构"的情况。

    engine 的 clients 把上游载荷原样透传, 所以会碰到两种形状:
    同花顺 stockpage 是 SPA, 上游站点解析不出列表就把 100KB 原始 HTML 塞进 data.html;
    另一路把结构化结果 json.dumps 成了字符串塞进 data。
    这两种都不是"没数据", 强行当结果渲染会把 HTML 噪声喂给 Agent ——
    按硬约束第 9 条显式标注, 由调用方决定是换源还是自行解析。
    """
    if not isinstance(out, dict):
        return None
    if not out.get('ok', True):
        return out.get('err') or out.get('error') or '接口返回失败'
    data = out.get('data')
    if isinstance(data, str) and data.lstrip()[:1] in '{[':
        try:
            return _unresolved(json.loads(data))
        except json.JSONDecodeError:
            return None
    if isinstance(data, dict):
        if data.get('error'):
            return f'数据源错误: {data["error"]}'
        if _table_of(data):
            return None                     # headers+rows 表结构, 各动作自己渲染
        if data.get('html') and _items_of(data) is None:
            return (f'源返回原始 HTML 未解析出条目 ({len(data["html"])} 字符, '
                    f'html_len={data.get("html_len")}); 换 news 源或用 webtool fetch 自行解析')
    return None


def _table_of(data):
    """headers+rows 表结构 (同花顺资金流)。识别到就返回 (headers, rows) 供渲染。"""
    if isinstance(data, dict) and isinstance(data.get('headers'), list) \
            and isinstance(data.get('rows'), list):
        return data['headers'], data['rows']
    return None


# 动作表

def _code(args, required=True):
    """单股动作取代码: 用位置参数 codes 的第一项。

    这些动作只对一只股票, 但 CLI 统一用 codes 位置参数收 (quote/check/risk 是
    多股), 这里取首个并校验 —— 没给就报错退 2, 不把空代码丢给数据源。
    required=False 用于 report/diagram 这类既可单股又可不带代码的动作。
    """
    codes = getattr(args, 'codes', None) or []
    if not codes:
        if not required:
            return None
        raise ValueError('需要一个股票代码, 例: webtool stock analyze 600519')
    return codes[0]


def _act_quote(args, cfg):
    return _engine.do_quote(args.codes)


def _act_pool(args, cfg):
    return _engine.do_pool(args.date, args.only_buy)


def _act_check(args, cfg):
    return _engine.do_check(args.codes)


def _act_calendar(args, cfg):
    return _engine.do_calendar(args.date, args.n)


def _act_flow(args, cfg):
    return _engine.do_capital_flow(args.scope)


def _act_news(args, cfg):
    return _engine.do_news(_code(args), args.limit)


def _act_announcement(args, cfg):
    return _engine.do_announcements(_code(args), args.limit)


def _act_financials(args, cfg):
    return _engine.do_financials(_code(args))


def _act_analyze(args, cfg):
    return _engine.do_analyze(_code(args))


def _act_screen(args, cfg):
    return _engine.do_screen(args.pool, args.min_score, args.codes)


def _act_risk(args, cfg):
    return _engine.do_risk(args.codes)


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


def _act_holder(args, cfg):
    """股东研究 (东财) —— 持仓变动/机构调研, 比 stock_top_holders 动作更细"""
    code = _code(args)
    mkt = 'SH' if code.startswith('6') else ('SZ' if code[0] in '03' else 'BJ')
    return _raw.call('em_shareholder_research', {'code': f'{mkt}{code}'})


def _act_forecast(args, cfg):
    """盈利预测 (东财) + 主营构成 (em_business_analysis) 交叉"""
    code = _code(args)
    mkt = 'SH' if code.startswith('6') else ('SZ' if code[0] in '03' else 'BJ')
    return _raw.call('em_profit_forecast', {'code': f'{mkt}{code}'})


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


def _http_client(args):
    """每次动作新建连接, 避免跨动作串 cookie"""
    return _http.Http(timeout=getattr(args, 'http_timeout', None) or 20)


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
    import json as _json
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



# data: 通用取数入口 (融合原 api/eco/http/em/docs)

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


# ===== data 域路由表 (唯一事实来源) =====
# 域名 → (说明, api 层功能分类名, eco 层接口名正则)
# api 层分类名来自 rawapi.categories() 的别名; eco 正则匹配 akshare/efinance 接口名。
# 约定: 一个接口只归一个域, 按表序先命中先用 —— 表序即优先级。
_DATA_DOMAINS = {
    '行情':    ('实时/历史行情, 指数点位', '行情快照',
               r'stock_zh_a_(spot|hist|minute|tick)|stock_zh_index|index_zh_a'
               r'|stock_bid|stock_individual_info|stock_sh_|stock_sz_|stock_bj_'
               r'|stock_hk_(spot|hist)|stock_us_(spot|hist)|stock_spot'),
    '龙虎榜':  ('龙虎榜/营业部/机构席位', '排行选股', r'lhb'),
    '资金流':  ('主力/北向/两融资金', '资金流向',
               r'fund_flow|money_flow|hsgt|margin|north|capital|stock_em_hy'
               r'|stock_sector_fund'),
    '财报':    ('三大报表/财务指标/业绩', '财务报表',
               r'indicator|report_|financial|balance|income|cashflow'
               r'|yysr|profit|zcfzb|xjllb|yjbb|yjkb|performance'),
    '股东':    ('十大股东/高管/股本', '股东股本',
               r'holder|shareholder|gdfx|gdhs|sharehold|restricted|unlock'
               r'|equity_change'),
    '板块':    ('行业/概念板块与成分', '板块行业',
               r'board|bk_|sector|industry|concept|stock_board'),
    '选股排行': ('排行/筛器/涨幅榜', '排行选股',
               r'rank|screen|top|screener|top_list|stock_zt|stock_dt'
               r'|stock_tfp|stock_dxsyl|stock_hot'),
    '公告资讯': ('公告/新闻/研报/电话会', '公告资讯',
               r'notice|announcement|news|info_|telegraph|report_'
               r'|research|stock_reply|conference'),
    '债券基金': ('债券/基金/ETF/理财', '其他/入口',
               r'bond_|cb_|fund_|etf|lof|convert|amc|amac'),
    '期货期权': ('期货/期权/贵金属', '其他/入口',
               r'futures|option|zh_|gue|gold|spot_goods|energy'),
    '外汇数字币': ('外汇/汇率/加密货币', '其他/入口',
               r'forex|currency|fx_|crypto|btc|coin'),
    '宏观':    ('宏观/行业景气/全球指标', '其他/入口',
               r'macro|gdp|cpi|ppi|pmi|china_|global|sw_|air_|movie|car'
               r'|energy_calendar|article_|fred|sunrise|migration|nlp|bank_'),
    '全球市场': ('港股/美股/中概/全球指数', '指数成分',
               r'hk_|us_|sk_|world|global_idx|usstock|hf_sp|qdii|reits'),
    '指数':    ('中外指数点位/成分/编制', '指数成分',
               r'^index_|_index$|index_value|index_detail'),
    '其他':    ('工具/配置/不便归类', '其他/入口', r'.')
}

def _domain_of_eco(name):
    """eco 接口名 → 域名 (表序先命中先用)"""
    for dom, (_desc, _cat, pat) in _DATA_DOMAINS.items():
        if re.search(pat, name):
            return dom
    return None

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
    from webtool.stock.bridge import docs as _docs
    return {
        'api': {'ok': _raw.available(), 'methods': len(_raw.methods())},
        'eco': _eco.health(),
        'em_recipes': {'ok': bool(_docs.stats().get('books')), 'books': _docs.stats()},
        'route': {'sources': 'per-request (RoutedAdapter + RoutedCffiSession)',
                  'eco': {lib: _eco_net.probe(lib)
                          for lib in ('akshare', 'tushare', 'baostock', 'efinance')}},
    }

def _act_report(args, cfg):
    return _engine.do_report(code=_code(args, required=False), pool=args.pool,
                             news=list(args.texts or []) or None)


def _act_excel(args, cfg):
    if not args.excel:
        raise ValueError('excel 需要 --excel 指定输出路径, 例: --excel picks.xlsx')
    return _engine.do_excel(args.excel, pool='short', min_score=args.min_score)


def _act_sentiment(args, cfg):
    items = list(args.texts or [])
    if not items:
        # 没给 --text 就理解为"给这只票的新闻打分", 省一次取新闻的重复输入
        items = _engine._news_texts(_code(args))
    return _engine.do_sentiment(items)


def _act_diagram(args, cfg):
    return _engine.do_diagram(args.kind or 'tree', code=_code(args, required=False),
                              name=args.name, thesis=args.thesis,
                              drivers=list(args.drivers or []),
                              risks=list(args.risks or []),
                              catalysts=list(args.catalysts or []),
                              mid=list(getattr(args, 'mid', None) or []))



def _act_std(action_name):
    """编排动作的通用子命令包装

    与 mcp 透传的区别: 位置参数直接给 symbol/codes (不用 --arg symbol=),
    渲染层按动作名走对表格, 编排层错误转 StockError 统一退出码。
    """
    def run(args, cfg):
        params = {}
        # 位置参数 → symbol (支持多个, 编排层只吃一个则取首个)
        codes = [c for c in (list(args.codes) if args.codes else []) if c]
        if codes and 'symbol' not in params:
            params['symbol'] = codes[0]
        # 指数动作: 中文别名/裸 6 位在动作层归一, 编排层只认标准形态
        if action_name == 'stock_index' and params.get('symbol'):
            params['symbol'] = _index_symbol(params['symbol'])
        params.update(_args_dict(args))
        return _srv.do_call(action_name, params, timeout=args.timeout)
    return run


_IDX_ALIAS = {
    '上证指数': 'sh000001', '上证': 'sh000001', '上证50': 'sh000016',
    '深证成指': 'sz399001', '创业板指': 'sz399006', '科创50': 'sh000688',
    '沪深300': 'sh000300', '中证500': 'sh000905', '中证1000': 'sh000852',
    '北证50': 'bj899050', '国证2000': 'sz399303',
}

def _index_symbol(s):
    """中文别名 / 裸 6 位 → idx:交易所+代码 (编排层 normalize_index 的口径)"""
    s = (s or '').strip()
    if s in _IDX_ALIAS:
        return 'idx:' + _IDX_ALIAS[s]
    if re.fullmatch(r'\d{6}', s) and s[0] in '03':
        return 'idx:' + ('sh' if s[0] == '0' else 'sz') + s
    return s


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
        'sources': 'per-request (RoutedAdapter + RoutedCffiSession)',
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


ACTIONS = {
    'quote': _act_quote, 'pool': _act_pool, 'check': _act_check,
    'calendar': _act_calendar, 'flow': _act_flow, 'news': _act_news,
    'announcement': _act_announcement, 'financials': _act_financials,
    'analyze': _act_analyze, 'screen': _act_screen, 'risk': _act_risk,
    'report': _act_report, 'excel': _act_excel, 'sentiment': _act_sentiment,
    'diagram': _act_diagram,
    'mcp': _act_mcp, 'tools': _act_tools, 'health': _act_health,
    'holder': _act_holder, 'forecast': _act_forecast,

    # 编排层动作升格 (原来只能 mcp --tool 透传)
    'kline': _act_std('stock_kline'),
    'index': _act_std('stock_index'),
    'income': _act_std('stock_income_statement'),
    'balance': _act_std('stock_balance_sheet'),
    'cashflow': _act_std('stock_cashflow'),
    'company': _act_std('stock_company'),
    'business': _act_std('stock_business_analysis'),
    'holders': _act_std('stock_top_holders'),
    'holder_chg': _act_std('stock_holder_change'),
    'industry': _act_std('stock_industry_list'),
    'concept': _act_std('stock_concept_list'),
    'industry_of': _act_std('stock_industry_concept'),
    'dividend': _act_std('stock_dividend_rank'),
    'margin': _act_std('stock_margin_list'),
    'screener': _act_std('stock_screener'),
    'ipo': _act_std('stock_ipo'),

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
    """旧 `api <方法名>` 语义: codes 位置参数给方法名"""
    name = (list(args.codes) or [''])[0]
    args.codes = []
    args.method = name
    return _act_data_call(args, None)

def _args_dict(args):
    """把 --arg k=v 收成 dict (纯数字留字符串, 同 mcp 动作的口径)"""
    params = {}
    for kv in (getattr(args, 'params', None) or ()):
        if '=' not in kv:
            raise ValueError(f'--arg 需要 k=v 形式, 收到 {kv!r}')
        k, _, v = kv.partition('=')
        params[k.strip()] = _coerce(v)
    return params


USAGE = """用法: webtool stock <动作> [参数]

数据动作 (走 engine 脚本层)
  quote <代码...>              实时行情, 支持指数别名(上证指数/创业板指)
  pool [--date D] [--only-buy] 涨停池 (连板/首封/炸板/封单/行业)
  check <代码...>              可买性核查 (板块归属 + ST/退市风险)
  calendar [--date D] [-n N]   交易日历
  flow [--scope industry|individual|north]  资金流榜单
  news <代码> [-n N]           个股新闻
  announcement <代码> [-n N]   公告列表
  financials <代码>            核心财务指标
  analyze <代码>               单股深度 (技术面+评分+决策信号+画像)
  screen [--pool short|mid|long] [--min-score N]  选股池
  risk <代码...>               风险核查 (重组/减持/立案/预亏)
  report <代码> | --pool short  成稿研报 (markdown, 单股/短线池)
  excel --excel 路径 [--min-score N]   选股池导出 xlsx (需 openpyxl)
  sentiment <代码> | --text "..."      消息面打分 -100~+100 (不给 --text 则给该股新闻打分)
  diagram --kind logic|tree|chain [...] mermaid 图
             tree  无参; logic 需 代码 --name [--thesis];
             chain 需 --name --driver(上游) --mid(中游) --catalyst(下游)

透传动作 (按名调用 24 个动作)
  mcp <动作名> [--arg k=v]     透传调用, 例: webtool stock mcp stock_indicators --arg symbol=600519
  tools [关键词]               列动作清单

通用取数入口 (按 15 个功能域组织, 1300+ 接口全从这里进)
  data                          入口导航 (15 个域, 各域接口数)
  data list                     域总览 (每域多少接口)
  data list <域>                域内明细 (api 分类 + eco 接口 + em 配方)
                                例: data list 行情 / data list 龙虎榜
  data <域> find <关键词>       域内搜, 例: data 行情 find 茅台 / data 龙虎榜 find lhb
  data find <关键词>            跨域搜四类目录 (eco/api/em配方/docs), 结果带来源
  data call <名称> [--arg k=v]  按名调, 分发顺序: em 配方 → api 方法 → eco 接口
                                例: data call RPT_LICO_FN_CPD --arg date=20260331
                                    data call sse_yunhq_snap --arg code=sh600519
  data url <URL> [--post] [--pick data.0.quote]   裸 HTTP 直调 (反爬已内置)
  data health                 数据面体检 (api/eco/em + 各库出网路由探测)

  域: 行情 龙虎榜 资金流 财报 股东 板块 选股排行 公告资讯 债券基金
      期货期权 外汇数字币 宏观 全球市场 指数 其他

生态库 (akshare 1093 / tushare 122 / baostock 29 / efinance 55 —— 实数以 data health 为准)
  注: efinance 是子模块结构, 接口名带前缀 (stock.get_quote_history / fund.get_base_info)

第五侧: 底层 HTTP 直调 (data url 的老入口, 逆向出的 900+ 接口都能自己打)
  反爬已内置: 雪球走 curl_cffi chrome110+token warmup, 新浪/中证自动带 Referer,
  东财 push2 自动补 ut, datacenter 自动补 token+source+client

第六侧: 逆向接口文档 (从 akshare 源码手工逆向, 900+ 接口, 带源码行号可回溯)
  回答的是前三层给不了的问题: 端点 URL 是什么 / 参数怎么拼 / 返回字段对应哪一列
  docs-search <关键词>                   全文检索, 带行号上下文 (例: companyType / hexin-v)
  docs-report <reportName>               单个接口的完整逆向条目 (参数表+字段列序映射)
  其余: docs-books / docs-stats / docs-book / docs-section / docs-endpoint

原始 API (数据源层 154 方法 — 编排层未覆盖的能力)
  api-list --by function       按**功能**分组 (行情/K线/财报/股东/公司/板块/
                              选股/资金/公告/指数/新股) —— 回答"要干什么"
  api <方法名> [--arg k=v]     直接调任一方法, 例: webtool stock api ths_stockpage_finance --arg code=600519
  holder <代码>                股东研究 (东财 持仓变动/机构调研)
  forecast <代码>              盈利预测 (东财)

财务/要素类 (编排层升格, 多源回退)
  kline <代码> [--arg period=week]     K 线 (东财/雪球/新浪)
  index <指数> [--arg count=30]        指数行情 (支持中文别名/裸代码)
  income|balance|cashflow <代码>       三大报表 (东财 F10 + 大盘表双源)
  company|business <代码>              公司概况 / 主营构成
  holders|holder_chg <代码>            十大股东 / 高管持股变动
  industry|concept                     行业板块 / 概念板块清单
  industry_of <代码>                   个股的板块归属
  dividend [--arg year=2025]           分红排名
  margin [--arg page=1]                两融标的
  screener [--arg market=cn_a]         全市场筛器 (雪球/新浪)
  ipo [--arg type=gem]                 IPO 清单 (主板/创业板/科创板)

元动作
  health                       三侧探活 (master / 编排层 / 原始 API)
"""


def _coerce(v):
    """--arg 的值猜类型。与 cli/mcp.py 的差别: 纯数字一律留字符串。

    股票代码 (600519 / 00700) 恒是字符串标识, 动作参数也按 string 收;
    按 JSON 字面量猜成 int 会被拒 (symbol must be non-empty string, got 600519)。
    其余值 (排序字段/枚举/布尔/嵌套 JSON) 仍按 JSON 解析。
    """
    s = v.strip()
    if not s:
        return v
    if s.isdigit() or (s.startswith('-') and s[1:].isdigit()):
        return s
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        return v


def do_stock(args, cfg):
    """分发 + 渲染。返回退出码: 0 成功 / 1 动作失败 / 2 用法错"""
    action = args.action
    if not action:
        print(USAGE, file=sys.stderr)
        return 2
    fn = ACTIONS.get(action)
    if not fn:
        print(f'unknown action: {action}\n\n{USAGE}', file=sys.stderr)
        return 2

    try:
        out = fn(args, cfg)
    except ImportError as e:
        # requests 是 stock/http.py 的顶层 import, 而 stock 整体是延迟导入
        # —— 少装一个包的表现是 `webtool stock` 抛一串 importlib 栈, 而
        # search/fetch 等其他命令完全正常, 很难联想到是依赖缺失。
        from webtool.core import deps
        print(f'error: stock 不可用 — {deps.install_hint(e.name or "")}',
              file=sys.stderr)
        return 2
    except _engine.EngineMissing as e:
        print(f'error: {e}', file=sys.stderr)
        return 2
    except _srv.SrvError as e:
        print(f'error: {e}', file=sys.stderr)
        return 1
    except _raw.RawApiError as e:
        print(f'error: {e}', file=sys.stderr)
        return 1
    except _eco.EcoError as e:
        print(f'error: {e}', file=sys.stderr)
        return 1
    except _docs.DocsError as e:
        print(f'error: {e}', file=sys.stderr)
        return 2
    except _http.HttpError as e:
        print(f'http error: {e}', file=sys.stderr)
        return 3
    except ValueError as e:
        print(f'error: {e}', file=sys.stderr)
        return 2

    # 载荷形状问题在渲染层拦 (raw HTML / 字符串化 data), 不让噪声进结果
    _render(out, args.format, action)
    return 0


# 渲染

def _render(out, fmt, action):
    fmt = _norm_fmt(fmt)
    # http-rows / em-report 直接返回 DataFrame, 渲染层先转成可序列化形状
    if hasattr(out, 'to_dict') and hasattr(out, 'columns'):
        n = len(out)
        out = {'rows': n, 'columns': [str(c) for c in out.columns],
               'records': out.to_dict('records')}
    # 未解析载荷只在 text/markdown 显式标注; json 保持原样 —— 程序消费方
    # 可能自己要那份 html, 但不该由我们替它决定丢弃。
    note = _unresolved(out)
    if fmt == 'json':
        print(_j(out, 10 ** 9))
        return
    if action in ('api', 'data', 'data-call', 'data-url', 'data-find',
                  'data-list', 'data-health',
                  'forecast', 'api-list', 'api-search'):
        # 数据源层的接口形态千差万别 (含本身就返回 HTML 的), 那个"本该是
        # 列表却回了原始 HTML"的守卫对它不适用, 会把正常响应误报成未解析。
        note = None
    if note:
        print(f'⚠ {note}', file=sys.stderr)
    if fmt == 'markdown':
        _md(out, action)
    else:
        _text(out, action)


# 原样透传类动作
# report / diagram / excel 产出的是"可直接给人看的东西" (成稿 markdown /
# mermaid 源码 / 已落盘文件), 再包一层 JSON 或表格反而破坏可读性 —— 直接出。

def _passthrough(out, key):
    if isinstance(out, dict) and out.get(key):
        print(out[key])
    elif isinstance(out, dict):
        print(json.dumps(out, ensure_ascii=False, indent=1))
    else:
        print(out)


def _k(*row):
    """表格行: None → '—' (缺数据显式占位, 不印 0)"""
    return ' | '.join('—' if v is None or v == '' else str(v) for v in row)


def _table(head, rows):
    print('| ' + ' | '.join(head) + ' |')
    print('|' + '|'.join(['---'] * len(head)) + '|')
    for r in rows:
        print('| ' + _k(*r) + ' |')


def _md(out, action):
    if action in ('report', 'diagram'):
        _passthrough(out, 'md' if action == 'diagram' else 'report')
        return
    if action == 'screen' and isinstance(out, dict):
        p_cnt, f_cnt, passed, failed = _screen_counts(out)
        thr = out.get('min_score_threshold')
        print(f"## 选股池 — 通过 {p_cnt} / 剔除 {f_cnt}"
              + (f", 门槛 {thr}" if thr is not None else '') + '\n')
        print('| 代码 | 名称 | 分 | 行业 | 位置 | 现价 | 突破 | 回踩 | 观察 | 止损 | 目标1 | 目标2 |')
        print('|---|---|---|---|---|---|---|---|---|---|---|---|')
        for p in passed:
            t = p.get('technical') or {}
            print('| ' + _k(p.get('code'), p.get('name'), p.get('score'),
                            _industry_cell(p.get('industry')), p.get('position_tag'),
                            t.get('current_price'), t.get('entry_breakout'),
                            t.get('entry_pullback'), t.get('entry_observing'),
                            t.get('hard_stop'), t.get('target_1'), t.get('target_2')) + ' |')
        if failed:
            print('\n### 剔除清单\n')
            print('| 代码 | 名称 | 闸门 | 原因 |')
            print('|---|---|---|---|')
            for f in failed:
                print('| ' + _k(f.get('code'), f.get('name'),
                                f.get('failed_gate'), f.get('error')) + ' |')
        return
    if action == 'tools' and isinstance(out, dict) and 'tools' in out:
        print(f'## stock 动作 ({out.get("count", len(out["tools"]))} 个)\n')
        _table(['动作', '说明'], [(t['name'], t.get('desc')) for t in out['tools']])
        return
    if action == 'quote':
        print('## 实时行情\n')
        _table(['代码', '名称', '现价', '涨跌幅%', '换手%', '量比', '流通市值亿', 'PE动', 'PB'],
               [(q.get('input'), q.get('name'), q.get('现价'), q.get('涨跌幅'),
                 q.get('换手%'), q.get('量比'), q.get('流通市值亿'),
                 q.get('PE动'), q.get('PB')) for q in out])
        return
    if action == 'pool' and isinstance(out, dict):
        print(f"## 涨停池 ({out.get('date')}) — {out.get('count')} 只\n")
        if out.get('提示'):
            print(f"> ⚠ {out['提示']}\n")
        _table(['代码', '名称', '连板', '行业', '封单亿', '炸板', '首封'],
               [(r.get('code'), r.get('name'), r.get('连板'), r.get('行业'),
                 r.get('封单亿'), r.get('炸板次数'), r.get('首封'))
                for r in out.get('rows') or []])
        return
    if action in ('api-list', 'api-search') and isinstance(out, dict):
        # 功能分类表本身是"给人读的目录", 走默认的 ```json 围栏会毁掉可读性
        # (154 个方法名挤成一行)。这里给真 markdown。
        kw = out.get('keyword')
        title = '数据源层方法分类' if not kw else f'数据源层搜索: {kw}'
        if out.get('by') == 'function':
            title = f'数据源层共 {out.get("count")} 个方法 — 按功能'
        print(f'## {title}\n')
        groups = out.get('categories') or {}
        if groups:
            for label, c in groups.items():
                print(f'### {label}\n')
                if c.get('desc'):
                    print(f"{c['desc']}\n")
                prim = c.get('primary') or []
                if prim:
                    print(f"- **首选** ({len(prim)}): "
                          + ' '.join(f'`{x}`' for x in prim))
                fb = c.get('fallback') or []
                if fb:
                    print(f"- 备选 ({len(fb)}): "
                          + ' '.join(f'`{x}`' for x in fb))
                print()
            return
        methods = out.get('methods') or []
        if isinstance(methods, list):
            _table(['方法', '功能类', '签名', '说明'],
                   [(m.get('method'), m.get('category') or '—',
                     m.get('sig', ''), (m.get('doc') or '')[:70])
                    for m in methods])
            return
        if isinstance(methods, dict):
            _table(['数据源', '个数'],
                   [(k, len(v)) for k, v in methods.items()])
            return
    print('```json')
    print(json.dumps(out, ensure_ascii=False, indent=1))
    print('```')


def _items_of(data, depth=6):
    """从动作返回的载荷里挖出条目列表 (广度优先下钻)。

    嵌套深度不固定: stock_news 是 data.items, stock_announcement 是 data.data.list,
    stock_capital_flow north 是 data.data.data.{hk2sh,sh2hk,...} (无列表)。
    只认显式的条目键 (items/list/rows) —— 其余 dict 键都往下钻一层。
    钻到底还没列表就返回 None 交给调用方标注, 不猜。
    """
    queue = [(data, 0)]
    while queue:
        node, d = queue.pop(0)
        if not isinstance(node, dict) or d > depth:
            continue
        for k in ('items', 'list', 'rows'):
            v = node.get(k)
            if isinstance(v, list):
                return v
        for v in node.values():
            if isinstance(v, dict):
                queue.append((v, d + 1))
    return None


def _text_analyze(out):
    """单股深度: 结论先行 (评分/信号), 再给三档入场价与止损。

    这份数据的消费者是人或 Agent 读结论, 不是程序读字段 —— 默认吐裸 JSON
    会把最关键的"能不能买、什么价买"埋在 20 行里。程序要字段用 -f json。
    """
    if not isinstance(out, dict):
        print(json.dumps(out, ensure_ascii=False))
        return
    t = out.get('technical') or {}
    q = out.get('quote') or {}
    bd = out.get('score_breakdown') or {}
    print(f"{out.get('code')} {out.get('name')} — {out.get('signal')} "
          f"(综合 {out.get('score')}/100)")
    if bd:
        print('  ' + '  '.join(f'{k.split("(")[0]}:{v}' for k, v in bd.items()))
    print(f"  现价 {q.get('current')} ({q.get('percent')}%)  PE {q.get('pe_ttm')}  "
          f"PB {q.get('pb')}  流通 {q.get('float_market_capital_yi')}亿")
    if t:
        print(f"  三档入场  突破 {t.get('entry_breakout')} / 回踩 {t.get('entry_pullback')} / "
              f"观察 {t.get('entry_observing')}")
        print(f"  止损 {t.get('hard_stop')}  目标 {t.get('target_1')} / {t.get('target_2')}")
        print(f"  MA5 {t.get('ma5')} MA20 {t.get('ma20')} MA60 {t.get('ma60')}  "
              f"RSI6 {t.get('rsi6')}  量比 {t.get('vol_ratio')}")
    for w in out.get('warnings') or []:
        print(f'  ⚠ {w}')
    prof = out.get('profile') or {}
    if prof.get('main_business'):
        print(f"  主营 {str(prof['main_business'])[:60]}")


def _text_sentiment(out):
    """消息面打分: 结论先行 (分数 + 倾向), 再列命中词。

    分数必须带符号显式印出 (+12 / -8), 不给绝对值 —— 消息面的关键信息是
    方向, 印成 12 会被读成"强利好"。
    """
    if not isinstance(out, dict):
        print(json.dumps(out, ensure_ascii=False))
        return
    s = out.get('score')
    n = out.get('news_count', 0)
    if not n:
        # 0 条 ≠ 中性。个股新闻源解析不出时打分器会给 0 分, 直接印"消息面 0 (中性)"
        # 会让调用方误以为"查过了没消息", 实际是根本没取到新闻。
        print('消息面 未取得 — 0 条输入 (新闻源未解析出条目, 或未指定 --text)')
        return
    s_txt = f'{s:+g}' if isinstance(s, (int, float)) else '未取得'
    tone = '利好' if isinstance(s, (int, float)) and s > 0 else (
        '利空' if isinstance(s, (int, float)) and s < 0 else '中性')
    print(f"消息面 {s_txt} ({tone}) — {n} 条, "
          f"正面 {out.get('positive_count', 0)} / 负面 {out.get('negative_count', 0)}")
    hits = out.get('hits')
    if isinstance(hits, dict):
        # 结构是 {"正": [命中词...], "负": [...]} 分组, 不是扁平的列表
        for tone, words in hits.items():
            if words:
                print(f'  [{tone}] {"、".join(str(w) for w in words)}')
    elif hits:
        for h in hits:
            print(f'  - {h.get("keyword") if isinstance(h, dict) else h}')
    if out.get('summary'):
        print(out['summary'])


def _text_risk(out):
    """风险核查: 逐股列命中项。clean=True 也必须显式说"无风险命中" ——
    空列表不显形会让调用方分不清"查过了没事"和"根本没查到"。

    scan_many 返回 {code: {hit, pending, clean}}, scan 返回单份 —— 两种都收。
    """
    if isinstance(out, dict) and 'hit' not in out and 'clean' not in out:
        items = [v if isinstance(v, dict) else {'code': k, 'hit': [v]}
                 for k, v in out.items()]
    else:
        items = [out]
    for r in items:
        code = r.get('code')
        hits = r.get('hit') or []
        if r.get('err'):
            print(f'[{code}] 查询失败: {r["err"]}')
            continue
        if r.get('clean') or not hits:
            print(f'[{code}] {r.get("name") or ""} 无风险命中 ✓')
            continue
        kinds = sorted({h.get('type') for h in hits if h.get('type')})
        print(f'[{code}] {r.get("name") or ""} 命中 {len(hits)} 项: {"、".join(kinds)}')
        for h in hits:
            print(f'    - {h.get("keyword")}: {h.get("title")}')


def _screen_counts(out):
    """通过/剔除计数。

    short 池自带 passed_count/failed_count, mid/long 池只给 passed/failed 列表
    —— 直接读 *_count 会让 mid 池渲染成 "通过 None"。列表长度为唯一可靠来源,
    有计数字段时以它为准 (short 池的 list 可能被截断)。
    """
    passed, failed = out.get('passed') or [], out.get('failed') or []
    return (out.get('passed_count') if out.get('passed_count') is not None else len(passed),
            out.get('failed_count') if out.get('failed_count') is not None else len(failed),
            passed, failed)


def _industry_cell(v):
    """行业列。short 池给字符串, mid/long 给 [{ind_code,ind_name,...}] 数组。

    数组直接塞进表格会打印整坨 dict, 这里只取一级行业名 (ind_type==1)。
    """
    if not v:
        return '—'
    if isinstance(v, str):
        return v
    if isinstance(v, list):
        names = [x.get('ind_name') for x in v
                 if isinstance(x, dict) and x.get('ind_name') and x.get('ind_type') == 1]
        return '/'.join(names) if names else (v[0].get('ind_name') if v and isinstance(v[0], dict) else str(v)[:20])
    return str(v)[:20]


def _text_screen(out):
    """选股池 text: 通过标的给三档入场价与硬止损, 剔除的必须带原因。

    剔除清单不能省 —— 调用方要判断"为什么没看到某只票", 只给通过名单等于
    让 Agent 以为它不存在。
    """
    p_cnt, f_cnt, passed, failed = _screen_counts(out)
    extra = ''
    if out.get('min_score_threshold') is not None:
        extra += f"  门槛 {out.get('min_score_threshold')}"
    if out.get('industry_dispersion') is not None:
        extra += f"  行业分散 {out.get('industry_dispersion')}"
    print(f"通过 {p_cnt} / 剔除 {f_cnt}{extra}")
    if passed:
        print('\n通过:')
        for p in passed:
            t = p.get('technical') or {}
            tag = p.get('position_tag')
            print(f"  [{p.get('code')}] {p.get('name')}  分{p.get('score')}"
                  f"  {_industry_cell(p.get('industry'))}{'  ' + tag if tag else ''}")
            if t:
                print(f"      现价{t.get('current_price')} 突破{t.get('entry_breakout')} "
                      f"回踩{t.get('entry_pullback')} 观察{t.get('entry_observing')} "
                      f"止损{t.get('hard_stop')} 目标{t.get('target_1')}/{t.get('target_2')}")
    if failed:
        print('\n剔除:')
        for f in failed:
            print(f"  [{f.get('code')}] {f.get('name')}  {f.get('error')}"
                  f"  (闸门: {f.get('failed_gate') or '—'})")


def _text_item(it):
    """单条记录: 有标题就先给标题再列关键字段; 否则按键值列全 (截断长值)。"""
    head = next((it[k] for k in ('title', 'name', 'report_date', '公告标题')
                 if it.get(k)), None)
    if head:
        print(f'- {head}')
    for k, v in it.items():
        if v in (None, '', 0) and k != 'report_date':
            continue                      # 缺数据不显形, 别让 0/空 冒充真实值
        if isinstance(v, (dict, list)):
            print(f'  {k}: {json.dumps(v, ensure_ascii=False)[:200]}')
        else:
            print(f'  {k}: {v}')


def _text_srv(out, note_only=False):
    """动作载荷的 text 渲染: 结构化则列条目, 未解析只给提示。

    载荷固定是 {"ok", "source", "data"(可能是 dict / 字符串化 JSON / raw html)}。
    """
    if note_only:
        return
    if not isinstance(out, dict):
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return
    source = out.get('source')
    if source:
        print(f'源: {source}')
    data = out.get('data')
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except json.JSONDecodeError:
            print(data[:500])
            return
    if isinstance(data, dict):
        items = _items_of(data)
        if items is not None:
            if not items:
                print('(无条目)')
                return
            for it in items:
                if not isinstance(it, dict):
                    print(str(it)[:300])
                    continue
                _text_item(it)
            return
        for k, v in data.items():
            if k in ('html', 'raw_html'):
                continue
            if isinstance(v, (dict, list)):
                print(f'{k}: {json.dumps(v, ensure_ascii=False)[:400]}')
            else:
                print(f'{k}: {v}')
        return
    print(json.dumps(data, ensure_ascii=False, indent=1)[:2000])


def _text_flow(out):
    """资金流: 同花顺/东财回 headers+rows 的表格结构, 按表头直接铺。

    北向口径下 status=3 时数据源会显式给 unavailable, 这里照原样透出并标 ⚠,
    绝不当成 0 净额显示 —— 那会让 Agent 得出"北向零流入"的错误结论。
    """
    if not isinstance(out, dict):
        print(json.dumps(out, ensure_ascii=False, indent=1)[:2000])
        return
    if out.get('unavailable'):
        print(f"⚠ 资金流不可用: {out['unavailable']}")
        return
    source = out.get('source')
    if source:
        print(f'源: {source}')
    data = out.get('data')
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except json.JSONDecodeError:
            print(data[:500])
            return
    if not isinstance(data, dict):
        print(json.dumps(data, ensure_ascii=False, indent=1)[:2000])
        return
    table = _table_of(data)
    if table:
        headers, rows = table
        print(' | '.join(str(h) for h in headers))
        for r in rows:
            if isinstance(r, list):
                print(' | '.join('—' if v in (None, '') else str(v) for v in r))
            else:
                print(json.dumps(r, ensure_ascii=False)[:300])
        return
    # 北向: data.data.{hk2sh,sh2hk,hk2sz,sz2hk} 四条通道, 每条带 status/date/净额
    inner = data.get('data')
    if isinstance(inner, dict) and any(k in inner for k in ('hk2sh', 'sh2hk', 'sz2hk', 'hk2sz')):
        for ch, v in inner.items():
            if not isinstance(v, dict):
                continue
            if v.get('status') == 3:
                print(f'⚠ {ch}: 数据源声明不可用 (status=3)'
                      + (f' — {v.get("unavailable")}' if v.get('unavailable') else ''))
                continue
            date = v.get('date2') or '—'
            net, quota = v.get('dayNetAmtIn'), v.get('dayAmtThreshold')
            # 东财北向接口在未推送真实值时会把 dayNetAmtIn 填成额度上限,
            # 沪股通返回 0 而深股通返回额度上限, 自相矛盾。净流入等于额度上限
            # 一律按"未取得"标注 —— 印成 4,200,000 万 (=4200亿) 会让调用方
            # 得出完全错误的结论。
            if isinstance(net, (int, float)) and quota and net == quota:
                print(f'⚠ {ch}  日期{date}  净流入未取得 (接口回填额度上限 {quota:,.0f} 万, 非真实值)')
                continue
            net_txt = f'{net:,.0f} 万' if isinstance(net, (int, float)) else '未取得'
            print(f'{ch}  日期{date}  净流入 {net_txt}')
        return
    for k, v in data.items():
        if k == 'html':
            continue
        print(f'{k}: {json.dumps(v, ensure_ascii=False)[:300] if isinstance(v, (dict, list)) else v}')


def _text_raw(out, action=''):
    """原始 API 载荷: 摘要 + 键结构, 不倾倒原始 JSON。

    数据源层返回的数据量动辄几十 KB (股东研究一家 34KB), 全量印出来
    既刷屏又淹掉重点。这里只给: 状态 / 来源 / 各键的条目数与首条要点。
    要全量用 -f json。
    """
    if not isinstance(out, dict):
        print(json.dumps(out, ensure_ascii=False)[:2000])
        return
    if action == 'api-list':
        print(f"数据源层共 {out.get('count')} 个方法 "
              f"(按{(out.get('by') or 'source')}):")
        if out.get('by') == 'function':
            for label, c in (out.get('categories') or {}).items():
                n = len(c['primary']) + len(c['fallback'])
                print(f"\n{label} ({n})  {c['desc']}")
                print(f"  首选: {' '.join(c['primary'])}")
                if c['fallback']:
                    print(f"  备选: {' '.join(c['fallback'])}")
            return
        for src, ms in (out.get('methods') or {}).items():
            print(f"  {src}({len(ms)}): {' '.join(ms[:6])}{' …' if len(ms) > 6 else ''}")
        return
    if action == 'api-search':
        if out.get('by') == 'category':
            print(f'"{out["keyword"]}" 命中 {out["count"]} 个功能类:')
            for label, c in (out.get('categories') or {}).items():
                print(f"\n{label}  {c['desc']}")
                print(f"  首选: {' '.join(c['primary'])}")
                if c['fallback']:
                    print(f"  备选: {' '.join(c['fallback'])}")
            return
        print(f'"{out["keyword"]}" 命中 {out["count"]} 个方法:')
        for m in (out.get('methods') or []):
            cat = f"[{m['category']}] " if m.get('category') else ''
            print(f"  {cat}{m['method']}{m['sig']}")
            if m.get('doc'):
                print(f"      {m['doc'][:90]}")
        return
    print(f"ok={out.get('ok')}" + (f"  源={out['source']}" if out.get('source') else '')
          + (f"  {out['raw_size']} 字符" if out.get('raw_size') else ''))
    if out.get('error'):
        print(f'  错误: {out["error"]}')
        return
    data = out.get('data')
    if not isinstance(data, dict):
        print(json.dumps(data, ensure_ascii=False)[:1000])
        return
    for k, v in data.items():
        if isinstance(v, list):
            if not v:
                print(f'  {k}: (空)')
            else:
                first = v[0]
                hint = (', '.join(list(first)[:5]) + '…'
                        if isinstance(first, dict) else str(first)[:60])
                print(f'  {k}: {len(v)} 条  首条字段[{hint}]')
        elif isinstance(v, dict):
            print(f'  {k}: {{}} {len(v)} 键 {list(v)[:5]}')
        elif v not in (None, '', []):
            print(f'  {k}: {str(v)[:80]}')


def _text_holder(out):
    """股东研究: 摘要 + 前十大股东表 + 股东户数趋势 (这是最该先看的两块)"""
    if not isinstance(out, dict) or not out.get('ok'):
        _text_raw(out)
        return
    data = out.get('data') or {}
    gdrs = data.get('gdrs') or []
    if gdrs:
        print('股东户数 (每报告期):')
        for g in gdrs[:6]:
            print(f"  {(g.get('END_DATE') or '')[:10]}  户数{g.get('HOLDER_TOTAL_NUM'):,}  "
                  f"户均持股{g.get('AVG_FREE_SHARES')}  集中度{g.get('HOLD_FOCUS')}")
    sd = data.get('sdgd') or []
    if sd:
        print(f"\n前十大股东 ({sd[0].get('END_DATE', '')[:10]}):")
        for h in sd[:10]:
            print(f"  {h.get('HOLDER_RANK')}. {str(h.get('HOLDER_NAME'))[:28]}  "
                  f"{h.get('HOLD_NUM_RATIO')}%  变动 {h.get('HOLD_NUM_CHANGE')}")
    jg = data.get('jgcc') or []
    if jg:
        print(f'\n机构持股 ({(jg[0].get("REPORT_DATE") or "")[:10]}):')
        for j in jg[:5]:
            print(f"  {j.get('ORG_TYPE')}  机构{j.get('TOTAL_ORG_NUM')}家  "
                  f"占流通股{j.get('TOTAL_SHARES_RATIO')}%")
    _text_raw_tail(out)


def _text_raw_tail(out):
    """给摘要渲染收尾: 剩下的键用条数说明 (不重复已展示的大块)"""
    data = out.get('data') or {}
    shown = {'gdrs', 'sdgd', 'jgcc', 'sdltgd'}
    rest = [k for k in data if k not in shown]
    if rest:
        parts = [f'{k}({len(data[k])})' if isinstance(data[k], (list, dict)) else k
                 for k in rest]
        print(f"\n其余字段: {', '.join(parts)}  (用 -f json 看全量)")


def _j(v, n=200):
    """json.dumps 兜底 —— akshare/efinance 的列里常有 datetime.date、numpy 标量。

    这些类型不是 JSON 原生, 直接 dumps 会 TypeError 崩掉整条命令, 而崩在
    渲染层尤其冤 (数据已经取到了)。所以统一走这里, 非原生类型转字符串。
    """
    def default(o):
        for attr in ('isoformat', 'item'):        # date/datetime → 字符串, numpy 标量 → python
            m = getattr(o, attr, None)
            if callable(m):
                try:
                    return m()
                except Exception:                  # noqa: BLE001
                    pass
        return str(o)
    try:
        return json.dumps(v, ensure_ascii=False, default=default)
    except (TypeError, ValueError):
        return str(v)[:n]


def _text_eco(out):
    """生态库返回: 形状摘要 + 前几行预览 (DataFrame 转 dict 前 N 行)。

    akshare 很多接口返回几千行 (全市场快照 5923×23), 直接印会刷屏 —— 默认只给
    形状与预览, --full 才给全量。
    """
    if not isinstance(out, dict):
        print(_j(out, 2000))
        return
    if out.get('ok') is False:
        print(f"error: {out.get('error')}")
        return
    print(f"[{out.get('lib')}.{out.get('name')}] {out.get('kind')}"
          f" shape={out.get('shape')}  {out.get('took_s')}s"
          + (f"  列={out['columns']}" if out.get('columns') else ''))
    for i, row in enumerate(out.get('preview') or []):
        print(f'  {i + 1}. {_j(row)}')
    if out.get('truncated'):
        print(f"  …共 {out.get('shape')} 行, --full 取全量")


def _text_eco_list(out):
    if not isinstance(out, dict):
        print(json.dumps(out, ensure_ascii=False))
        return
    lib, n = out.get('library'), out.get('count')
    if 'signature' in out:
        print(f"{lib}.{out.get('name')}  ({out.get('lib')} 共 {n} 个接口)")
        print(f"  签名: {out['signature']}")
        doc = (out.get('doc') or '').strip().splitlines()
        for line in doc[:6]:
            print(f'  {line}')
        return
    print(f"{lib} 共 {n} 个接口")
    for f in out.get('funcs') or []:
        print(f'  {f}')
    if out.get('truncated'):
        print('  …用 --limit 调整, 或 eco-search <关键词> 精确找')


def _text_eco_search(out):
    if not isinstance(out, dict):
        print(json.dumps(out, ensure_ascii=False))
        return
    if not out.get('libraries'):
        print(f"无匹配: {out.get('keyword')}")
        return
    print(f"\"{out.get('keyword')}\" 匹配 {out.get('count')} 个:")
    for lib, names in out['libraries'].items():
        print(f"  {lib} ({len(names)}): {' '.join(names[:8])}{' …' if len(names) > 8 else ''}")


def _text(out, action):
    if action == 'eco':
        _text_eco(out)
        return
    if action == 'eco-list':
        _text_eco_list(out)
        return
    if action == 'eco-search':
        _text_eco_search(out)
        return
    if action in ('http-get', 'http-post'):
        print(out if isinstance(out, str) else json.dumps(out, ensure_ascii=False, indent=1))
        return

    if action and action.startswith('docs-'):
        c = out.get('content')
        if c:
            print(c)
            rest = {k: v for k, v in out.items() if k != 'content'}
            if rest:
                print('\n--- meta ---')
                print(json.dumps(rest, ensure_ascii=False, indent=1))
            return
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return

    if action == 'eco-health':
        for lib, st in (out or {}).items():
            if st.get('installed'):
                print(f"  ✓ {lib}: {st.get('funcs')} 个接口")
            else:
                print(f"  ✗ {lib}: 未安装")
        return
    if action in ('news', 'announcement', 'financials', 'mcp'):
        _text_srv(out, note_only=bool(_unresolved(out)))
        return
    if action == 'holder':
        _text_holder(out)
        return
    if action in ('api', 'forecast', 'api-list', 'api-search'):
        # 不跑 _unresolved 守卫: 那守卫针对 news/announcement 那类"本该给列表
        # 却回了原始 HTML"的情况。数据源层有些接口 (如 ths_stockpage_finance)
        # 本身就返回 HTML 表格, 套同一个守卫会误报成"未解析"。
        _text_raw(out, action)
        return
    if action == 'analyze':
        _text_analyze(out)
        return
    if action == 'risk':
        _text_risk(out if isinstance(out, dict) else {})
        return
    if action == 'flow':
        _text_flow(out)
        return
    if action in ('report', 'diagram'):
        _passthrough(out, 'md' if action == 'diagram' else 'report')
        return
    if action == 'excel':
        if isinstance(out, dict) and out.get('ok'):
            print(f"已导出 {out.get('path')} — 通过 {out.get('passed')} / 剔除 {out.get('failed')}")
        else:
            print(json.dumps(out, ensure_ascii=False))
        return
    if action == 'sentiment':
        _text_sentiment(out)
        return
    if action == 'quote':
        for q in out:
            if not q.get('ok'):
                print(f"[{q.get('input')}] 无数据: {q.get('err')}")
                continue
            print(f"[{q.get('name')}] {q.get('现价')}  {q.get('涨跌幅')}%  "
                  f"换手{q.get('换手%')}% 量比{q.get('量比')} "
                  f"流通市值{q.get('流通市值亿')}亿 PE{q.get('PE动')}")
        return
    if action == 'screen' and isinstance(out, dict):
        _text_screen(out)
        return
    if action == 'tools' and isinstance(out, dict) and 'tools' in out:
        for t in out['tools']:
            print(f"{t['name']}  {t.get('desc')}")
        return
    if action == 'pool' and isinstance(out, dict):
        if not out.get('ok'):
            print(f"涨停池失败: {out.get('err') or out.get('error')}")
            return
        print(f"涨停池 {out.get('date')} — {out.get('count')} 只")
        if out.get('提示'):
            print(f"⚠ {out['提示']}")
        for r in out.get('rows') or []:
            print(f"[{r.get('code')}] {r.get('name')}  {r.get('行业') or ''}  "
                  f"连板{r.get('连板', '—')}  {r.get('涨停统计') or ''}  "
                  f"封单{r.get('封单亿', '—')}亿")
        return
    # 通用兜底: 非结构化的按 key: value 或原样 JSON
    if isinstance(out, dict):
        for k, v in out.items():
            if isinstance(v, (dict, list)):
                print(f"{k}: {json.dumps(v, ensure_ascii=False)}")
            else:
                print(f"{k}: {v}")
    else:
        print(json.dumps(out, ensure_ascii=False, indent=1))