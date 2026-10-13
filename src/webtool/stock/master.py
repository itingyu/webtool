"""桥接 stock-master skill 的 scripts 包

stock-master 是独立 skill, 装在 /var/minis/skills/stock-master, 不在 webtool 的
依赖图里。这里只做进程内 import 桥: 把 skill 根塞进 sys.path, 再 import 它的
scripts.clients / analysis / screening。

为什么不把 stock-master 收成 webtool 的依赖:
  1. stock-master 自身是 skill 交付件 (SKILL.md + references + scripts), 版本由它自己管
  2. 它的 clients 已带多源 fallback 与单位约定, 收进来等于复制一份口径
  3. skill 缺失时 stock 子命令应明确报 "未安装", 而不是让 webtool 整体 import 失败

路径可用 STOCK_MASTER_HOME 环境变量覆盖 (测试与多份安装场景)。
"""
import importlib
import json
import os
import sys

DEFAULT_HOME = '/var/minis/skills/stock-master'


class MasterMissing(RuntimeError):
    """stock-master 未安装或不可 import —— 由调用方转成退出码 2 与可读提示"""


def home():
    return os.environ.get('STOCK_MASTER_HOME') or DEFAULT_HOME


def available():
    return os.path.isfile(os.path.join(home(), 'SKILL.md'))


def _ensure_path():
    p = home()
    if p not in sys.path:
        sys.path.insert(0, p)


def mod(name):
    """import stock-master 的 scripts.<name>; 失败抛 MasterMissing (带原因)"""
    _ensure_path()
    try:
        return importlib.import_module(f'scripts.{name}')
    except ImportError as e:
        raise MasterMissing(
            f'stock-master 不可用: {e}; 期望装在 {home()} '
            f'(可用 STOCK_MASTER_HOME 覆盖)') from e


def clients():
    """数据层唯一入口: quote / limit_up_pool / announcements / capital_flow / code_ok ..."""
    c = mod('clients')
    if not getattr(c, '_webtool_inproc', False):
        _patch_inproc(c)
    return c


def _patch_inproc(c):
    """把 stock-master 的两个子进程出口换成进程内实现。

    stock-master 的 clients.mcp() 每次 `subprocess.run(["minis-mcp-cli", ...])`
    (约 2.5s/次), clients.web_search() 每次 `subprocess.run(["webtool", "search", ...])`
    (webtool 自己起自己, 纯浪费)。这里在模块上覆盖这两个函数, 让它们走
    stock/srv.py 的进程内通道与 webtool 自己的 search:

      - 产物形状完全一致 ({"ok","source","data",...} / {"ok","query","results"})
      - 只在 webtool 进程内生效, 不改 skill 文件 —— skill 有自己的维护流程,
        改动应由 skill 侧提; webtool 只在运行时注入

    web_search 走 `cli.app.main(argv)` 而不是直接调 `pipeline.search.do_search`,
    因为后者要 29 个字段的 args 对象, 自己拼等于复制一份 CLI 契约, 迟早漂移。

    标记 _webtool_inproc 防重复注入 (clients 可能被多次 import 命中同一模块对象)。
    """
    c._webtool_inproc = True

    def _mcp(tool, **kwargs):
        from webtool.stock import srv as _srv
        try:
            return _srv.call(tool, kwargs)
        except _srv.SrvError as e:
            _log(f'MCP {tool} 失败: {e}', level='WARN')
            return {'ok': False, 'err': str(e)}

    def _web_search(query, max_n=8):
        import contextlib
        import io
        from webtool.cli.app import main
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                rc = main(['search', query, '-n', str(max_n), '-f', 'json'])
            out = json.loads(buf.getvalue() or '{}')
            return {'ok': rc == 0 and bool(out.get('results')),
                    'query': query, 'results': out.get('results', [])}
        except Exception as e:                              # noqa: BLE001
            _log(f'webtool 搜索失败: {type(e).__name__}: {e}', level='WARN')
            return {'ok': False, 'query': query, 'err': str(e), 'results': []}

    c.mcp = _mcp
    c.web_search = _web_search


def _log(msg, level='INFO'):
    """日志走 stderr, 不污染 stdout 的结果输出 (同 skill 的 _common.log 口径)"""
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
    """个股新闻 (stock MCP 通道)"""
    return clients().news(code)


def do_announcements(code, page_size=10):
    """公告列表 (stock MCP 通道)"""
    return clients().announcements(code, page_size)


def do_financials(code):
    """核心财务指标 (stock MCP 通道)"""
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

    服务端载荷可能是 items / data.list 等不同嵌套, 且同花顺那条路会回原始
    HTML 未解析 —— 两种情况都取不到可用文本, 此时返回空列表让下游按"无新闻"
    处理, 不把 HTML 塞进打分器。
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
    """从服务端载荷里挖条目列表 (广度优先下钻 items/list/rows)。"""
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