"""桥接 stock MCP server 的 24 个工具

stock MCP 由 Minis 宿主以子进程方式暴露 (minis-mcp-cli), 不是 HTTP 端点 ——
所以这里走 `minis-mcp-cli call stock <tool> --input <json>`, 与 `webtool mcp`
那套 HTTP 客户端 (net/mcpclient.py) 是两条不同的通道, 别混。

CLI 返回信封:
    成功  {"server","tool","result":{"content":[{"type":"text","text":"<json>"}],"isError":false}}
    失败  同形状但 isError=true, 或进程非 0 退出时 {"error":..., "code":"PARSE_ERROR"}

内层 text 才是工具自己的 JSON ({"ok":true,"source":...,"data":...})。
这里做两层解析: 外壳剥 isError, 内层尽量还原成 dict (失败则原样返回字符串,
不假装解析成功)。

超时与并发: 子进程每次调用 ~0.8-2.5s (含 MCP 冷启), 故默认 60s 超时。
批量场景 (如逐股拉财报) 靠 WebSearch 那套 rate 限流由调用方控制, 本模块不并发。
"""
import json
import os
import shutil
import subprocess

CLI = os.environ.get('MINIS_MCP_CLI', 'minis-mcp-cli')
SERVER = os.environ.get('STOCK_MCP_SERVER', 'stock')

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
    """子进程不存在 / 超时 / 协议异常。业务级错误 (工具返回 isError) 不走这里"""


def available():
    return shutil.which(CLI) is not None


def call(tool, params=None, timeout=60):
    """调一个 stock MCP 工具, 返回工具自己的 JSON (dict) 或原始 text (str)

    失败抛 McpError —— 调用方 (command.py) 转成退出码 1 并把原因走 stderr,
    不静默返回空 (Agent 拿到空会以为"查无此项")。
    """
    if not available():
        raise McpError(f'找不到 {CLI} (装 Minis 宿主后可用; 可用 MINIS_MCP_CLI 覆盖路径)')
    payload = json.dumps(params or {}, ensure_ascii=False)
    try:
        p = subprocess.run([CLI, 'call', SERVER, tool, '--input', payload],
                           capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        raise McpError(f'{tool} 超时 {timeout}s') from e

    raw = (p.stdout or '').strip()
    if not raw:
        raise McpError(f'{tool} 无输出 (rc={p.returncode}): {(p.stderr or "").strip()[:300]}')
    try:
        env = json.loads(raw)
    except json.JSONDecodeError as e:
        raise McpError(f'{tool} 返回非 JSON: {raw[:200]}') from e

    if 'error' in env and 'result' not in env:
        raise McpError(f'{tool} 调用失败: {env.get("error")}')

    res = env.get('result') or {}
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
    """剥 MCP content 信封取第一个 text 块; 形状不认识就返回 None"""
    for c in (res.get('content') or []):
        if isinstance(c, dict) and c.get('type') == 'text':
            return c.get('text')
    return None


def do_tools(keyword=''):
    """列工具清单。给了 keyword 走服务端 stock_search_tools, 否则用本地 TOOLS 表"""
    if keyword:
        return call('stock_search_tools', {'keyword': keyword})
    return {'count': len(TOOLS),
            'tools': [{'name': n, 'desc': d} for n, d in sorted(TOOLS.items())]}


def do_call(tool, params=None, timeout=60):
    """透传调任意 stock_* 工具 (stock 工具不在 TOOLS 表里时用这条逃生口)"""
    if tool in RESERVED:
        raise McpError(f'{tool!r} 是子命令动作名, 不是 MCP 工具名')
    return call(tool, params, timeout=timeout)