"""MCP (Model Context Protocol) 客户端内核: JSON-RPC 2.0 over Streamable HTTP

通用内核, 不绑死任何具体 MCP server。给一个 Streamable HTTP 端点 + 可选
API key, 就能 list_tools / call_tool。

为什么要自己写: MCP 生态的官方 SDK (mcp / fastmcp) 依赖重、版本变动快, 而
这里只要"发一次 POST + 解析响应"这点能力, 纯 stdlib 足够, 且不受 SDK 升级影响。

协议要点 (实测 exa/mcp.exa.ai 确认):
- 请求是普通 HTTP POST, body 为 JSON-RPC 2.0 信封
- Accept 必须同时含 application/json 与 text/event-stream, 少一个服务端直接
  拒 (实测只给 json 返回 -32000 Not Acceptable)
- 响应可能是纯 JSON, 也可能是 SSE 流 (text/event-stream); 两者都要能解,
  故按 Content-Type + body 前缀双路嗅探 (见 parse_response)

分层: 本模块属 net/ (L1 采集实现), 不 import pipeline / render / cli。
"""
import json
import time
import urllib.error
import urllib.request


JSONRPC_VERSION = '2.0'
DEFAULT_TIMEOUT = 45

# MCP Streamable HTTP 硬要求: 两个 Accept 都要给
_ACCEPT = 'application/json, text/event-stream'


def build_url(base_url, tools_filter=''):
    """端点 + 可选工具白名单 (?tools=a,b)

    白名单让服务端只暴露指定工具, 缩小 Agent 的选择面 (免 key 部署尤其有用
    —— 部分 server 凭 key 决定暴露哪些工具)。
    """
    tools_filter = (tools_filter or '').strip()
    if not tools_filter:
        return base_url
    sep = '&' if '?' in base_url else '?'      # 端点自带 query 时不能再拼 '?'
    return f'{base_url}{sep}tools={tools_filter}'


def build_headers(api_key='', protocol_version=''):
    """请求头。Accept 双值是硬要求; api_key 为空则完全不发认证头 (免 key 通道)。"""
    headers = {'Content-Type': 'application/json',
               'Accept': _ACCEPT,
               'User-Agent': 'Minis/1.0'}
    if protocol_version:
        headers['MCP-Protocol-Version'] = protocol_version
    if api_key:
        # 只发 x-api-key: 实测带无效 key 与不带 key 完全等价 (服务端不校验,
        # 也不因此放宽工具集), 发三种头名纯属冗余
        headers['x-api-key'] = api_key
    return headers


def parse_sse_message(text):
    """SSE 帧 → 最后一个完整 payload

    按 SSE 规范逐字段处理: event / data / id / retry; 跳过 ':' 开头的注释行
    (keepalive) 与空行(帧分隔); 多行 data 用 \\n 拼接。

    流式响应会推多次, 取最后一个 (最终态)。JSON 解析失败不抛异常 ——
    退回原始字段结构返回, 保证调用方总能拿到现场信息。
    """
    chunks = [c.strip() for c in text.split('\n\n') if c.strip()]
    last_payload = None
    for chunk in chunks:
        data_lines = []
        event_type = 'message'
        event_id = None
        retry = None
        for line in chunk.splitlines():
            if not line or line.startswith(':'):
                continue                        # 空行 / 注释行 (keepalive)
            if ':' in line:
                field, value = line.split(':', 1)
                if value.startswith(' '):
                    value = value[1:]           # 规范规定冒号后去一个空格
            else:
                field, value = line, ''         # 无冒号 = field 名, value 空
            if field == 'event':
                event_type = value
            elif field == 'data':
                data_lines.append(value)
            elif field == 'id':
                event_id = value
            elif field == 'retry':
                retry = value
        payload = '\n'.join(data_lines).strip()
        if not payload:
            continue
        try:
            last_payload = json.loads(payload)
        except json.JSONDecodeError:
            # 解析不了就把原始结构带出去, 别把诊断信息吞了
            last_payload = {'event': event_type, 'id': event_id, 'retry': retry,
                            'data': payload, 'raw': chunk}
    if last_payload is None:
        raise json.JSONDecodeError('Empty SSE payload', text, 0)
    return last_payload


def parse_response(content_type, text):
    """双协议自适应: SSE 流 / 纯 JSON

    Content-Type 判一次, 再用 body 前缀兜底 (有些网关会改写 Content-Type)。
    """
    stripped = text.lstrip()
    if ('text/event-stream' in (content_type or '').lower()
            or stripped.startswith('event:') or stripped.startswith('data:')):
        return parse_sse_message(text)
    return json.loads(text)


def _error(message, code=-1, data=None):
    err = {'code': code, 'message': message}
    if data is not None:
        err['data'] = data
    return {'jsonrpc': JSONRPC_VERSION, 'id': None, 'error': err}


PROTOCOL_VERSION = '2025-06-18'
_SESSION_HEADER = 'Mcp-Session-Id'
# 服务端要求先握手时的特征串 (实测: "Missing mcp-session-id header")
_NEEDS_SESSION = 'mcp-session-id'


def _send(url, payload, headers, timeout, proxy):
    """POST 一次, 返回 (status, resp_headers, text); 异常统一成 (None, {}, msg)"""
    # 证书策略走 core.tls (与搜索/抓取/zen 通道同源), 不在这里自建 opener
    from webtool.core import http as _http
    opener = _http.build_opener(proxy, url=url)
    req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'),
                                 headers=headers, method='POST')
    try:
        with opener.open(req, timeout=timeout) as resp:
            raw = resp.read()
            try:
                charset = resp.headers.get_content_charset()
            except Exception:
                charset = None                 # 响应头异常不该影响解析
            return (resp.status, dict(resp.headers),
                    raw.decode(charset or 'utf-8', errors='replace'))
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode('utf-8', errors='replace')
        except Exception:
            body = ''
        return (getattr(e, 'code', -1), dict(getattr(e, 'headers', {}) or {}), body)
    except Exception as e:
        return (None, {}, str(e))


def _handshake(url, headers, timeout, proxy):
    """MCP 初始化握手, 返回 session id; 无状态服务端返回 None。

    Streamable HTTP 允许服务端有状态: 必须先 initialize 拿 Mcp-Session-Id,
    后续请求带上它。基于官方 SDK 的服务端默认走这条路。
    """
    init = {'jsonrpc': JSONRPC_VERSION, 'id': 1, 'method': 'initialize',
            'params': {'protocolVersion': PROTOCOL_VERSION, 'capabilities': {},
                       'clientInfo': {'name': 'webtool', 'version': '1.0'}}}
    st, rh, _ = _send(url, init, headers, timeout, proxy)
    sid = rh.get(_SESSION_HEADER) or rh.get(_SESSION_HEADER.lower())
    if not sid:
        return None
    # 规范要求 initialize 之后补一条 initialized 通知
    note = {'jsonrpc': JSONRPC_VERSION, 'method': 'notifications/initialized'}
    nh = dict(headers)
    nh[_SESSION_HEADER] = sid
    _send(url, note, nh, timeout, proxy)
    return sid


def make_request(base_url, method, params=None, *, api_key='', tools_filter='',
                 timeout=DEFAULT_TIMEOUT, proxy=None, protocol_version=''):
    """发一次 JSON-RPC 请求, 返回解析后的响应体 (dict)。

    刻意**不抛异常**: 网络/协议/校验类失败一律转成 JSON-RPC error 结构返回。
    调用方 (Agent) 因此只有一条解析路径 —— 成功失败都是 JSON, 不会因为
    Python traceback 中断。HTTPError 分支单独读 body, 因为服务端的诊断信息
    (如参数校验明细) 只在 body 里, 只看 str(e) 会丢现场。

    会话是**惰性**的: 先按无状态发, 服务端回 "Missing mcp-session-id" 才握手
    重试一次 —— 无状态服务端 (exa) 因此零额外开销。
    """
    url = build_url(base_url, tools_filter)
    headers = build_headers(api_key, protocol_version)
    payload = {'jsonrpc': JSONRPC_VERSION, 'id': 1, 'method': method,
               'params': params or {}}
    st, rh, text = _send(url, payload, headers, timeout, proxy)

    if st is not None and 400 <= st < 500 and _NEEDS_SESSION in text.lower():
        sid = _handshake(url, headers, timeout, proxy)
        if sid:
            h2 = dict(headers)
            h2[_SESSION_HEADER] = sid
            st, rh, text = _send(url, payload, h2, timeout, proxy)

    if st is None:
        return _error(text if text.startswith('Network error') else f'Request failed: {text}')
    ctype = rh.get('Content-Type', '')
    if 400 <= st < 500:
        return _error(_http_msg(st), code=st, data=text)
    return parse_response(ctype, text)


def _http_msg(status):
    """'HTTP Error 429: Too Many Requests' —— 与 urllib 原生措辞一致"""
    reasons = getattr(urllib.error, 'responses', {})
    return f'HTTP Error {status}: {reasons.get(status, "Error")}'


# ---------------------------------------------------------------- 对外动作

def list_tools(base_url, **kw):
    """tools/list → {name, description, required:[...]} 精简表"""
    r = make_request(base_url, 'tools/list', **kw)
    if 'error' in r:
        return r
    tools = []
    for t in (r.get('result') or {}).get('tools') or []:
        schema = t.get('inputSchema') or {}
        tools.append({'name': t.get('name'),
                      'description': (t.get('description') or '').strip(),
                      'required': list(schema.get('required') or []),
                      'params': sorted((schema.get('properties') or {}).keys())})
    return {'tools': tools, 'total': len(tools)}


def call_tool(base_url, tool, arguments=None, **kw):
    """tools/call → {text, is_error, raw}

    MCP 的工具结果统一是 content 数组里的 text 块 (结构化内容另议), 这里拼成
    纯文本给下游用, 同时保留 raw 供需要结构化时自取。
    """
    r = make_request(base_url, 'tools/call',
                     {'name': tool, 'arguments': arguments or {}}, **kw)
    if 'error' in r:
        return r
    res = r.get('result') or {}
    blocks = res.get('content') or []
    text = '\n'.join(b.get('text', '') for b in blocks
                     if isinstance(b, dict) and b.get('type') == 'text')
    return {'text': text, 'is_error': bool(res.get('isError')), 'raw': res}


def probe(base_url, **kw):
    """端点自检: list_tools 看通不通, 返回 {ok, total, error}"""
    t0 = time.time()
    r = list_tools(base_url, **kw)
    took = int((time.time() - t0) * 1000)
    if 'error' in r:
        return {'ok': False, 'took_ms': took, 'error': r['error']}
    return {'ok': True, 'took_ms': took, 'total': r['total']}


def endpoint(name='exa'):
    """取 data/mcp.json 里登记的端点声明; 取不到抛 RuntimeError"""
    from webtool.core import config_data
    table = config_data.load('mcp', 'mcp.json')
    spec = table.get(name)
    if not spec:
        known = ', '.join(sorted(table)) or '(无)'
        raise RuntimeError(f'未登记端点 {name!r}; 可用: {known}')
    return spec


def api_key_of(spec):
    """按声明的 api_key_env 从环境变量取 key; 没声明或没配则空串 (=免 key)"""
    import os
    env = spec.get('api_key_env')
    return os.environ.get(env, '') if env else ''


def call_verb(name, verb, arguments=None, timeout=None, proxy=None):
    """按端点声明把动词翻成工具名再调 —— 供搜索引擎与 fetch 兜底共用。

    返回 {text, is_error, error} 三态之一:
    - 正常: {text, is_error}
    - 协议/网络失败: {error}
    - 上游工具报错: {is_error: True, text}

    代理策略与 `cli/mcp.py::_proxy_for` 同源: 端点表不参与决策, 缺省 `'auto'` 走
    路由表。端点曾声明 `proxy: direct` 强制直连 (免 key 配额按出口 IP 计), 已
    移除 —— 那是服务方的计量策略, 该由用户配置决定。需要直连:
    `webtool config set engine_proxy.<端点> direct`, 或在规则表里写域名规则。
    此处没有 args.no_proxy 可看, 临时绕过由调用方显式传 proxy=None。
    """
    spec = endpoint(name)
    tool = (spec.get('verbs') or {}).get(verb)
    if not tool:
        have = ', '.join(sorted(spec.get('verbs') or {})) or '(该端点未声明 verbs)'
        raise RuntimeError(f'端点 {name!r} 未声明 {verb!r} 动词; 可用: {have}')
    return call_tool(spec.get('url', ''), tool, arguments or {},
                     api_key=api_key_of(spec), timeout=timeout,
                     proxy=proxy)
