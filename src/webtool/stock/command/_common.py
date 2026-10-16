"""stock 子命令共用零件: 值格式化、表格切片、K 线取数、参数解析助手"""
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

from webtool.stock.bridge import http as _http



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

def _http_client(args):
    """每次动作新建连接, 避免跨动作串 cookie"""
    return _http.Http(timeout=getattr(args, 'http_timeout', None) or 20)

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

def _kline_rows(out):
    """从各源 K 线载荷里取 rows (统一成 render.kline_svg 认的形状)"""
    from webtool.render.kline_svg import normalize_rows
    d = (out or {}).get('data') or {}
    if not isinstance(d, dict):
        return []
    return normalize_rows(d.get('klines') or d.get('rows') or [])

def _kline_title(out, code):
    """源里带的证券名优先 (用户可能只给了代码)"""
    d = (out or {}).get('data') or {}
    qt = d.get('qt') if isinstance(d, dict) else None
    if isinstance(qt, dict):
        for v in qt.values():
            if isinstance(v, (list, tuple)) and len(v) > 2:
                return f'{v[1]} {v[2]}' if v[1] else str(v[2])
    for k in ('name', 'symbol'):
        if isinstance(d, dict) and d.get(k):
            return str(d[k])
    return code or '—'

def _write_kline_chart(out, args, code, bars):
    from webtool.render.kline_svg import write_kline_svg
    rows = _kline_rows(out)
    period = args.period or 'day'
    cn = {'day': '日线', 'week': '周线', 'month': '月线'}.get(period, period)
    path = getattr(args, 'chart_out', None) or f'{code or "kline"}-{period}.svg'
    write_kline_svg(path, rows, title=_kline_title(out, code),
                    subtitle=f'{cn} · {len(rows)} 根 · 源 {out.get("source") or "—"}',
                    ma=[m for m in (getattr(args, 'ma', None) or '5,10,20').split(',') if m.strip()],
                    bars=bars)
    return path

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

def _looks_like_list(args):
    return (args.method or '') in ('api', 'sources') and not (args.codes or [])

def _args_dict(args):
    """把 --arg k=v 收成 dict (纯数字留字符串, 同 mcp 动作的口径)"""
    params = {}
    for kv in (getattr(args, 'params', None) or ()):
        if '=' not in kv:
            raise ValueError(f'--arg 需要 k=v 形式, 收到 {kv!r}')
        k, _, v = kv.partition('=')
        params[k.strip()] = _coerce(v)
    return params

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

def _passthrough(out, key):
    if isinstance(out, dict) and out.get(key):
        print(out[key])
    elif isinstance(out, dict):
        print(json.dumps(out, ensure_ascii=False, indent=1))
    else:
        print(out)

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

def _fmt_vol(v):
    for unit, div in (('亿', 1e8), ('万', 1e4)):
        if abs(v) >= div:
            return f'{v / div:.2f}{unit}'
    return f'{v:.0f}'

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



def codes_input(args):
    """多代码动作的输入归一: 显式参数 > '-' / 管道 stdin

    `webtool stock quote -`、`cat codes.txt | webtool stock check` 都到这;
    单股动作 (kline 等) 取首个时也先过这里, 保证 '-' 不会当代码去查。
    """
    codes = list(getattr(args, 'codes', None) or [])
    if codes == ['-'] or not codes:
        from webtool.core import stdin as _stdin
        parsed = _stdin.parse_lines(_stdin.read_input(
            '-' if not codes and _stdin.is_pipe() else (codes[0] if codes else None)))
        if parsed:
            return parsed
        if not codes:
            return []
    return codes
