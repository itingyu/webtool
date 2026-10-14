"""编排层入口 —— 24 个动作的多源回退与代码归一

## 它是什么

`financials` / `news` / `announcement` / `capital_flow` 这些动作不能只打一个
源: 腾讯快但字段少、雪球字段全但要指纹会话、东财稳但慢。所以每个动作声明一串
`(源名, 取数闭包)`, 按序尝试, 取首个通过质检的结果。另有 `normalize()` 把用户
随手写的代码转成各源要的格式 (格式拼装统一委托 `sources/_symbol.py`)。

实现落在同目录 `orchestrate.py`。

## 调用方式

`call(tool, params)` 是本层唯一入口: 纯进程内直接调 `orchestrate.py` 里的
`t_stock_*` 函数, 不起子进程、不走协议握手、不套信封 (模块名沿用 `srv`,
调用方 `clients` 与 command 的透传动作都按这个签名进来)。

动作清单的事实来源是**函数名本身**: `tool_names()` 直接扫模块里的
`t_stock_*`, 增删函数自动跟上, 不存在两处不同步。

失败语义: handler 抛异常或返回 `ok=False` → `SrvError`。调用方转成退出码 1 +
stderr, 不静默返回空 (空会被误读成"查无此项")。
"""
from webtool.stock.error import SrvError

ORCHESTRATE_MOD = 'bridge/orchestrate.py'

# 工具名 → 一句话说明。只用于 `webtool stock --list` 给人看的可读清单;
# 是否存在**不**由它决定 (那是 `tool_names()` 扫函数名说了算), 所以本表
# 漏写一条只是少一行说明, 不会让某个动作失效。
TOOLS = {
    'stock_quote': '实时行情 (A股/港股/美股/ETF, 多源 fallback)',
    'stock_kline': 'K 线 (day/week/month)',
    'stock_company': '公司基本信息与简介',
    'stock_business_analysis': '主营业务详细分析 (A股)',
    'stock_indicators': '核心财务指标 PE/PB/ROE/毛利率/营收净利同比',
    'stock_balance_sheet': '资产负债表 (200+ 字段)',
    'stock_income_statement': '利润表',
    'stock_cashflow': '现金流量表',
    'stock_top_holders': '十大股东',
    'stock_holder_change': '股东变动',
    'stock_industry_list': '行业板块列表 (按涨跌幅)',
    'stock_concept_list': '概念板块列表',
    'stock_industry_concept': '个股所属行业与概念',
    'stock_screener': '涨跌幅/成交额/PE/PB 排行 (market: cn_a/cn_b/hk/us)',
    'stock_index': '指数实时或历史收益',
    'stock_index_constituent': '指数成分股 (沪深300/中证500/中证1000/上证)',
    'stock_announcement': '公告列表',
    'stock_news': '个股新闻',
    'stock_capital_flow': '资金流向 (industry/individual/north)',
    'stock_dividend_rank': '分红排行 (连续分红年数/股息率)',
    'stock_margin_list': '融资融券列表',
    'stock_ipo': 'IPO 列表',
    'stock_search_tools': '按关键词搜工具',
    'stock_health_check': '编排层健康检查',
}

RESERVED = ('tools', 'call')




_server = None            # 进程内已 import 的服务端模块; None = 未加载


def _server_mod():
    """进程内加载编排层模块; 失败返回 None (调用方走本地兜底表)

    `bridge/orchestrate.py` 是包内模块, 静态 import —— 不找路径、不动 sys.path,
    所以它与 `rawapi` 必然解析到同一份 `APIClient` (早期靠 sys.path 注入时两者
    插的是不同目录, 真的加载了两份, token/session 缓存各一份)。

    延迟 import 的唯一理由: 编排层缺失只该让 stock 动作退 2, 不拖垮整个 webtool。
    """
    global _server
    if _server is not None:
        return _server
    try:
        from webtool.stock.bridge import orchestrate as _m
    except ImportError:
        return None
    _server = _m
    return _server if any(name.startswith('t_stock_') for name in dir(_m)) else None


def available():
    """服务端模块能进程内加载即可"""
    return _server_mod() is not None


def call(tool, params=None, timeout=60):
    """调一个 stock 动作, 返回它自己的 JSON (dict) 或原始 text (str)

    纯进程内直调 handler: 注册表 TOOLS 里每项自带 handler 函数, 调它拿到的就是
    直接返回 dict, 无信封。失败抛 SrvError ——
    调用方 (command.py) 转成退出码 1 并把原因走 stderr, 不静默返回空
    (Agent 拿到空会以为"查无此项")。
    """
    handler = _handler(tool)
    try:
        res = handler(params or {})
    except Exception as e:                                  # noqa: BLE001
        # handler 会为参数非法等直接抛 (如 normalize 失败)。原 _call_tool 捕获后
        # 包成 isError 响应, 语义是"调用失败"而非"进程崩了" —— 这里保持一致,
        # 否则 news/flow 等动作会因单只票的参数问题整条命令崩掉。
        raise SrvError(f'{tool} 调用失败: {type(e).__name__}: {e}') from e
    if not isinstance(res, dict):
        return res
    if res.get('ok') is False:
        # 失败语义: 抛 SrvError 而不是把 {"ok":false} 当结果返回
        raise SrvError(f'{tool} 返回错误: {res.get("err") or res.get("error") or res}')
    return res


def _handler(tool):
    """按名字取 handler 函数 —— 命名约定即注册表

    `stock_xxx` → 编排层的 `t_stock_xxx`, 一一对应。不另维护注册表: 注册表与
    函数体是两处事实来源, 漏删 handler 就会"列得出但调不动"。
    """
    mod = _server_mod()
    if mod is None:
        raise SrvError(f'编排层不可用: webtool/stock/{ORCHESTRATE_MOD} 导入失败')
    if not isinstance(tool, str) or not tool.startswith('stock_'):
        raise SrvError(f'工具名需以 stock_ 开头, 收到 {tool!r}')
    fn = getattr(mod, f't_{tool}', None)
    if not callable(fn):
        raise SrvError(f'未知工具: {tool} (webtool stock --list 列全部)')
    return fn


def tool_names():
    """工具名集合 —— 直接扫编排层的 `t_stock_*` 函数

    事实来源是**函数本身**。增删一个 `t_stock_xxx` 清单自动跟上, 不存在两处
    不同步。`TOOLS` 那张表只是给人看的说明文字, 不参与存在性判断。
    """
    mod = _server_mod()
    if mod is None:
        return sorted(TOOLS)
    return sorted(name[2:] for name in dir(mod)
                  if name.startswith('t_stock_')
                  and callable(getattr(mod, name)))


def do_tools(keyword=''):
    """列工具清单。给了 keyword 按名称与说明筛, 否则列全部"""
    rows = [{'name': n, 'desc': TOOLS.get(n, '')} for n in tool_names()]
    if keyword:
        k = keyword.lower()
        rows = [r for r in rows
                if k in r['name'].lower() or k in r['desc'].lower()]
    return {'count': len(rows), 'source': ORCHESTRATE_MOD, 'tools': rows}


def do_call(tool, params=None, timeout=60):
    """透传调任意 stock_* 动作 (CLI 未单独暴露的那些走这条)"""
    if tool in RESERVED:
        raise SrvError(f'{tool!r} 是子命令动作名, 不是编排层工具名')
    return call(tool, params, timeout=timeout)