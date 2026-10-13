"""桥接 stock MCP server 的 24 个工具

**纯进程内**: 服务端模块就在本机 /var/minis/mcp-servers/stock_mcp_server.py,
import 后直接调它的 `_call_tool` —— 不起子进程、不经 minis-mcp-cli。
实测单次 0.1-2s, 相比子进程通道 (2.9s, 含冷启) 省一个数量级。

也正因如此, `TOOLS` 直接读服务端注册表 —— 工具增删不用在 webtool 侧维护第二份。

⚠️ 与 `webtool mcp` 那套 HTTP 通道 (net/mcpclient.py) 是两件不同的事 —— stock MCP
既不是 HTTP 端点, 也不能用 net/mcpclient 去调。

返回形状是 MCP 信封 `{"content":[{"type":"text","text":"<json>"}],"isError":bool}`,
内层 text 才是工具自己的 JSON ({"ok":true,"source":...,"data":...})。解析失败时
原样返回字符串, 不假装解析成功。
"""
import importlib
import json
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
    return _server if hasattr(_server, '_call_tool') else None


def available():
    """服务端模块能进程内加载即可"""
    return _server_mod() is not None


def call(tool, params=None, timeout=60):
    """调一个 stock MCP 工具, 返回工具自己的 JSON (dict) 或原始 text (str)

    纯进程内: 直接 import 服务端模块调它的 `_call_tool`。失败抛 McpError ——
    调用方 (command.py) 转成退出码 1 并把原因走 stderr, 不静默返回空
    (Agent 拿到空会以为"查无此项")。
    """
    mod = _server_mod()
    if mod is None:
        raise McpError(f'stock MCP 服务端不可用: {SERVER_HOME}/{SERVER_MOD}.py 导入失败 '
                       f'(STOCK_MCP_HOME 可覆盖路径)')
    return _unwrap(tool, mod._call_tool(tool, params or {}))


def _unwrap(tool, res):
    """剥 MCP 信封还原工具自己的 JSON ({"content":[{"type":"text","text":"<json>"}]})。"""
    if res.get('isError'):
        raise McpError(f'{tool} 返回错误: {_inner_text(res) or "(空)"}')
    inner = _inner_text(res)
    if inner is None:
        return res
    try:
        return json.loads(inner)
    except json.JSONDecodeError:
        return inner          # 工具回纯文本 (如 unknown tool 提示), 原样给


def _inner_text(res):
    """剥 content 信封取第一个 text 块; 形状不认识就返回 None"""
    for c in (res.get('content') or []):
        if isinstance(c, dict) and c.get('type') == 'text':
            return c.get('text')
    return None


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