"""集成 stock 数据服务端的 24 个工具 (原 stock MCP server 的能力)

**纯进程内, 且不经 MCP 协议**: 服务端模块就在本机 /var/minis/mcp-servers/
stock_mcp_server.py, 它的 `TOOLS` 注册表里每项自带 handler 函数 ——
直接调 handler, 拿到的就是工具自己的 dict。没有子进程、没有 JSON-RPC、
没有 content 信封的序列化往返。

也正因如此 `TOOLS` 就是工具清单的单一事实来源 —— 服务端增删工具 webtool 自动跟上,
本地那份 TOOLS 只是服务端 import 不了时的兜底。

⚠️ 与 `webtool mcp` 那套 HTTP 通道 (net/mcpclient.py) 是两件不同的事 —— 那条是给
通用 MCP server (HTTP) 用的, 这里不需要它。

失败语义 (与原 MCP 路径一致): handler 抛异常或返回 ok=False → McpError。
skill 侧的包装函数 (clients.mcp 等) 捕获后仍拿到 {"ok":False,"err":...},
调用方 (command.py) 转成退出码 1 + stderr。
"""
import importlib
import os
import sys

SERVER_HOME = os.environ.get('STOCK_MCP_HOME', '/var/minis/mcp-servers')
SERVER_MOD = 'stock_mcp_server'

# 工具名 → 一句话说明。CLI 自带 stock_search_tools, 这份表只为 stock mcp tools
# 动作直接列清单用 (省一次子进程), 新增工具时两边一起更新。
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
    'stock_health_check': 'MCP 侧健康检查',
}

RESERVED = ('tools', 'call')


class McpError(RuntimeError):
    """通道不可用 / 超时 / 协议异常。业务级错误 (工具返回 isError) 不走这里"""


_server = None            # 进程内已 import 的服务端模块; None = 未加载


def _server_mod():
    """进程内加载服务端模块; 失败返回 None (调用方回落子进程)

    延迟 import + 缓存: 放在模块级会让 webtool 所有命令都依赖服务端存在,
    而服务端缺失只该让 stock 动作退 2。
    """
    global _server
    if _server is not None:
        return _server
    if SERVER_HOME not in sys.path:
        sys.path.insert(0, SERVER_HOME)
    try:
        _server = importlib.import_module(SERVER_MOD)
    except ImportError:
        return None
    return _server if isinstance(getattr(_server, 'TOOLS', None), list) else None


def available():
    """服务端模块能进程内加载即可"""
    return _server_mod() is not None


def call(tool, params=None, timeout=60):
    """调一个 stock MCP 工具, 返回工具自己的 JSON (dict) 或原始 text (str)

    纯进程内直调 handler: 注册表 TOOLS 里每项自带 handler 函数, 调它拿到的就是
    工具自己的 dict, 不经 MCP 信封。失败抛 McpError ——
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
        raise McpError(f'{tool} 调用失败: {type(e).__name__}: {e}') from e
    if not isinstance(res, dict):
        return res
    if res.get('ok') is False:
        # 保持与 MCP 路径一致的失败语义: 抛 McpError 而不是把 {"ok":false} 当结果返回
        raise McpError(f'{tool} 返回错误: {res.get("err") or res.get("error") or res}')
    return res


def _handler(tool):
    """按名字取 handler 函数。注册表是唯一事实来源 —— 服务端增删工具自动跟上。"""
    mod = _server_mod()
    if mod is None:
        raise McpError(f'stock 数据服务端不可用: {SERVER_HOME}/{SERVER_MOD}.py 导入失败 '
                       f'(STOCK_MCP_HOME 可覆盖路径)')
    for t in getattr(mod, 'TOOLS', []) or []:
        if isinstance(t, dict) and t.get('name') == tool:
            h = t.get('handler')
            if callable(h):
                return h
    raise McpError(f'未知工具: {tool} (webtool stock tools 列全部)')


def tool_names():
    """工具名集合。优先取服务端 TOOLS 注册表 (跟得上服务端增删), 回落本地表。

    本地 TOOLS 只是服务端 import 不了时的兜底, 不作为事实来源 ——
    单一事实来源是服务端自己的注册表。
    """
    mod = _server_mod()
    reg = getattr(mod, 'TOOLS', None) if mod else None
    if isinstance(reg, list):
        return [t['name'] for t in reg if isinstance(t, dict) and t.get('name')]
    return list(TOOLS)


def do_tools(keyword=''):
    """列工具清单。给了 keyword 走服务端搜索, 否则直读服务端 TOOLS 注册表"""
    if keyword:
        return call('stock_search_tools', {'keyword': keyword})
    mod = _server_mod()
    reg = getattr(mod, 'TOOLS', None) if mod else None
    if isinstance(reg, list):
        return {'count': len(reg), 'source': f'server:{SERVER_MOD}',
                'tools': [{'name': t['name'], 'desc': t.get('description')}
                          for t in reg if isinstance(t, dict)]}
    return {'count': len(TOOLS), 'source': 'local-fallback',
            'tools': [{'name': n, 'desc': d} for n, d in sorted(TOOLS.items())]}


def do_call(tool, params=None, timeout=60):
    """透传调任意 stock_* 工具 (stock 工具不在 TOOLS 表里时用这条逃生口)"""
    if tool in RESERVED:
        raise McpError(f'{tool!r} 是子命令动作名, 不是 MCP 工具名')
    return call(tool, params, timeout=timeout)