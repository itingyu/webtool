"""engine 桥 —— 业务脚本层与 CLI 之间的转发

`webtool/stock/engine/` 是本仓的**第一方代码**（从 stock-master 技能搬进来的
那批：选股池、评分、可买性闸门、研报模板…）。它自带工作流编排与业务口径，
本模块只做两件事：定位它、把它的动作转发出去。

对外只有 `mod(name)` —— 静态 import `webtool.stock.engine.<name>`，不找路径、
不动 sys.path。延迟 import 是为了让脚本层缺失时只让 stock 动作退 2，而不是
拖垮整个 webtool。

取数不在这里：所有 HTTP 都经 `bridge/sources`，engine 侧只保留业务口径。
"""
import importlib
import os
import sys

from webtool.stock.error import EngineMissing

ENGINE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'engine')


def available():
    """engine 包在不在。判据是 `engine/__init__.py`（代码），不是文档"""
    return os.path.isfile(os.path.join(ENGINE_DIR, '__init__.py'))


def mod(name):
    """import `webtool.stock.engine.<name>`; 失败抛 EngineMissing (带原因)"""
    try:
        return importlib.import_module(f'webtool.stock.engine.{name}')
    except ImportError as e:
        # 两种完全不同的病, 别混成一句话: engine 文件不在 = 装包不完整; engine
        # 在但它的第三方依赖不在 = 没装 extra (numpy 之类)。后者以前被误报成
        # "应随包安装在 webtool/stock/engine/", 指引的是错的方向。
        from webtool.core import deps
        miss = getattr(e, 'name', None) or ''
        if not miss.startswith('webtool'):
            raise EngineMissing(
                f'stock engine 不可用: {deps.install_hint(miss)}') from e
        raise EngineMissing(
            f'stock engine 不可用: {e}; engine 文件缺失, '
            f'{deps.install_hint("webtool 本体")}') from e


def clients():
    """数据层唯一入口: quote / limit_up_pool / announcements / capital_flow / code_ok ..."""
    return mod('clients')


def _log(msg, level='INFO'):
    """日志走 stderr, 不污染 stdout 的结果输出 (同 engine._common.log 口径)"""
    print(f'[{level}] {msg}', file=sys.stderr)


# ---------- 动作实现 (每个都只做参数整形 + 调用, 不加工业务口径) ----------

def do_quote(codes):
    """实时行情。腾讯主源, 指数别名(上证指数/创业板指)可用。返回 list[dict]"""
    return clients().quote(list(codes))


def do_pool(date=None, only_buy=False):
    """涨停池。东财 push2ex; date=None/last = 上一交易日, only_buy = 只留可买板块

    返回 {"ok", "date"(真实数据日), "count", "rows"}; 非 ok 时原样透传错误,
    不把失败伪装成空池 (涨跌停池接口对无效日期会静默回旧数据, date 是唯一可信锚)。
    """
    c = clients()
    r = c.limit_up_pool(date)
    if not isinstance(r, dict) or not r.get('ok'):
        return r
    out = dict(r)
    rows = r.get('rows') or []
    if only_buy:
        rows = [it for it in rows if c.code_ok(it.get('code'), it.get('name'))[0]]
    out['rows'] = rows
    out['count'] = len(rows)
    out['filtered_only_buy'] = bool(only_buy)
    return out


def do_check(codes):
    """可买性核查: 板块归属 + 停牌/ST/退市风险 + 涨跌停制度口径

    code_ok 返回 (可买, 板块名); 不可买的也照样返回并标注 —— 调用方要的是
    "为什么被剔除", 静默丢弃等于让 Agent 以为查无此股。
    """
    c = clients()
    checks = []
    for code in codes:
        try:
            ok, board = c.code_ok(code)
        except Exception as e:                              # noqa: BLE001
            checks.append({'code': code, '可买': False, '板块': None,
                           'err': f'{type(e).__name__}: {e}'})
            continue
        checks.append({'code': code, '可买': bool(ok), '板块': board})
    return {'count': len(checks),
            '可买数': sum(1 for x in checks if x['可买']),
            'checks': checks}


def do_calendar(date=None, n=3):
    """交易日历 (含节假日表), date=None = 今天起往后 n 个交易日"""
    return mod('short_tool').calendar(date, n)


def do_capital_flow(scope='industry'):
    """资金流榜单。scope ∈ industry/individual/north; 北向不可用时显式给 unavailable"""
    return clients().capital_flow(scope)


def do_news(code, limit=10):
    """个股新闻。

    limit 只能取回后裁剪: `stock_news` 只接 symbol, 没有分页参数 —— 同花顺
    stockpage 一次给全量, 截断是这里做的。
    """
    r = clients().news(code)
    items = _items(r)
    if items is None or not limit or len(items) <= limit:
        return r
    data = r.get('data') if isinstance(r, dict) else None
    if not isinstance(data, dict):
        return r
    out = dict(r)
    out['data'] = _replace_items(data, items[:limit])
    out['total_items'] = len(items)
    return out


def _replace_items(data, new_items):
    """把 payload 里那条 items/list/rows 列表换掉 (保持原嵌套形状)"""
    for k in ('items', 'list', 'rows'):
        if isinstance(data.get(k), list):
            return {**data, k: new_items}
    return {**data, 'items': new_items}


def do_announcements(code, page_size=10):
    """公告列表。page_size 透传给编排层的 stock_announcement。"""
    return clients().announcements(code, page_size)


def do_financials(code):
    """核心财务指标 (PE/PB/ROE/毛利率/营收净利同比 等)。"""
    return clients().financials(code)


def do_analyze(code, news_items=None):
    """单股深度: quote + K线 + 技术指标 + 100分制评分 + 决策信号 + 公司画像"""
    return mod('analysis.single_analysis').analyze(code, news_items)


def do_screen(pool='short', min_score=60, codes=None):
    """选股池。pool ∈ short/mid/long, 走 pool_selector 统一路由

    三个池入参不同, 不能透传: short 收 min_score (自跑全市场), mid/long 收
    codes 列表 (用户给标的), long 还要求 [{code,name}] 结构。分开组装。
    """
    if pool == 'short':
        return mod('screening.pool_selector').select('short', min_score=min_score)
    if pool == 'mid':
        return mod('screening.pool_selector').select('mid', codes=list(codes or []))
    if pool == 'long':
        items = [{'code': c, 'name': None} if isinstance(c, str) else c
                 for c in (codes or [])]
        return mod('screening.pool_selector').select('long', codes=items)
    raise ValueError(f'未知池名: {pool} (可用: short / mid / long)')


def do_risk(codes):
    """风险股核查: 重组 / 减持 / 立案 / 预亏"""
    rc = mod('screening.risk_check')
    if isinstance(codes, str):
        return rc.scan(codes)
    return rc.scan_many(list(codes))


def do_report(code=None, pool=None, news=None):
    """成稿研报 (markdown)。code=单股报告, pool=短线池报告

    报告模板在 research.report_writer, 口径全在那边; 这里只做取数 + 拼装:
    单股报告要先跑 analyze (报告模板吃的是 analyze 的输出)。
    """
    rw = mod('research.report_writer')
    if code:
        analysis = do_analyze(code)
        items = news if news is not None else _news_texts(code)
        return {'kind': 'single', 'code': code,
                'report': rw.single_stock_report(analysis, news=items)}
    if pool == 'short':
        result = do_screen('short')
        return {'kind': 'short_screen', 'report': rw.short_screen_report(result)}
    raise ValueError('report 需要 --code (单股报告) 或 --pool short (短线池报告)')


def do_excel(path, pool='short', min_score=60):
    """选股池导出 xlsx。openpyxl 不在环境里则明确报错, 不静默不出文件"""
    try:
        import openpyxl                              # noqa: F401
    except ImportError:
        raise ValueError('导出 xlsx 需要 openpyxl (apk add py3-openpyxl)')
    result = do_screen('short', min_score=min_score)
    mod('export.short_screen_excel').build_from_screen(result, path, meta={'source': 'webtool stock screen'})
    return {'ok': True, 'path': path, 'passed': len(result.get('passed') or []),
            'failed': len(result.get('failed') or [])}


def do_sentiment(texts):
    """消息面打分 (-100~+100)。texts: 字符串列表, 或 [{"title"/"text"}]"""
    return mod('sentiment.news_scorer').score(list(texts))


def do_diagram(kind, code=None, name=None, thesis=None,
               drivers=None, risks=None, catalysts=None, mid=None):
    """mermaid 图: logic(投资逻辑) / tree(决策树) / chain(产业链)

    chain 的上游/中游/下游分别对应 drivers/mid/catalysts —— 产业链图没有
    "风险"概念, 拿 risks 去当中游是语义错配, 所以单独用 --mid。

    logic 缺参数会画得空洞, 但那是调用方的事 —— 该由人给的判断不该由工具猜。
    """
    lr = mod('visualization.logic_renderer')
    if kind == 'tree':
        return {'kind': kind, 'md': lr.decision_tree()}
    if kind == 'chain':
        if not name:
            raise ValueError('chain 需要 --name (产业链名)')
        return {'kind': kind, 'md': lr.industry_chain(
            name, drivers or [], mid or [], catalysts or [])}
    if kind == 'logic':
        if not (code and name):
            raise ValueError('logic 需要 --code 与 --name')
        return {'kind': kind, 'md': lr.investment_logic(
            code, name, thesis or '', drivers or [], risks or [], catalysts or [])}
    raise ValueError(f'未知图类型: {kind} (可用: logic / tree / chain)')


def _news_texts(code, limit=10):
    """取个股新闻的纯文本, 供消息面打分 / 研报附新闻。

    载荷可能是 items / data.list 等不同嵌套, 且同花顺那条路会回原始 HTML
    未解析 —— 两种情况都取不到可用文本, 此时返回空列表让下游按"无新闻"处理,
    不把 HTML 塞进打分器。
    """
    r = do_news(code, limit)
    out = []
    for it in (_items(r) or []):
        if isinstance(it, str):
            out.append(it)
        elif isinstance(it, dict):
            t = it.get('title') or it.get('text')
            if t:
                out.append(t)
    return out


def _items(payload):
    """从载荷里挖条目列表 (广度优先下钻 items/list/rows)。"""
    queue = [(payload, 0)]
    while queue:
        node, d = queue.pop(0)
        if not isinstance(node, dict) or d > 6:
            continue
        for k in ('items', 'list', 'rows'):
            v = node.get(k)
            if isinstance(v, list):
                return v
        for v in node.values():
            if isinstance(v, dict):
                queue.append((v, d + 1))
    return None
