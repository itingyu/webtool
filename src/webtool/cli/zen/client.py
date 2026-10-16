"""zen 客户端: 模型目录/请求/流式/思考段切分/路由与退避重试"""
"""zen: OpenCode Zen 免费层客户端 (公开模式, 无需 API key)
端点 https://opencode.ai/zen/v1/chat/completions, 认证固定是占位 `Bearer public`
(免费层不要真 key; 本包不读 OPENCODE_API_KEY —— 也没有走真 key 的代码路径)。
免费层形状校验: tools 必须非空且含名为 bash 和 read
的两个工具 (空壳 parameters={} 即可; 空/缺名 → 403 FreeTierError, 缺 function
包装或 parameters 键 → 400), 分类器只认名字和形状, 不看 description/schema,
tools 取真机定义、tool_choice 默认 auto —— 两者都是免费层闸门判据, 改不得。
请求体: messages[0]=system / messages[-1]=user / tools 含 bash+read /
tool_choice 存在 / stream=true。解析: 纯标准库 urllib + 逐行 SSE, read1() 读流, 字节层面切行 (decode 再切会把跨读边界的汉字写成 U+FFFD)。
"""

import json
import re
import random
import sys
import time

from webtool.core import urls
from webtool.core.secrets_store import redact
from webtool.cli import zenproto as _zp
from webtool.cli.zenproto import (_endpoints, build_body,
                                  build_headers, model_headers,
                                  parse_models_full, parse_sse)

# socket 空闲超时。urlopen 的 timeout 只管"多久没收到字节", 不是墙钟预算;
# 流式生成中间只要有 delta 就永不触发, 所以给够即可。

TIMEOUT = 120.0

def is_free_model(model_id):
    """按命名约定判定是否免费层 —— 但这不是证明, 用 `zen --list-models --check`"""
    return 'free' in model_id or model_id in {'big-pickle'}

def fetch_models_detail(cfg, refresh=False, timeout=15.0, proxy=None):
    """实时拉 /v1/models → 全量行 [{id, created, owned_by}] (缓存 1h)

    走的是原来那份 fetch_models 的路子: 同一个缓存键、同一条线路 (_route),
    两者打的是同一个端点, 免得"能聊天却拉不到模型清单"。差别只在于多留了
    接口原样给的字段 —— 上游哪天多给一列(上下文/价格), 加一行就能进表;
    老缓存里的 ids 结构照旧读得动。
    """
    from webtool.dao import cache as _cache
    key = 'zen/models'
    chat_url, models_url = _endpoints()
    if not refresh:
        hit = _cache.get(cfg, 'zen', key)
        if hit and isinstance(hit.get('models'), list) and hit['models']:
            return hit['models']
        if hit and isinstance(hit.get('ids'), list) and hit['ids']:
            return [{'id': i, 'created': None, 'owned_by': None}
                    for i in hit['ids']]                # 旧缓存结构
    if proxy is None:
        proxy = _route(cfg, models_url, verbose=True)
    try:
        d = json.loads(_request('GET', models_url, cfg={'proxy': proxy},
                                headers=model_headers(),
                                timeout=timeout).content)
        rows = parse_models_full(d)
    except Exception as e:                       # 超时/DNS/TLS 都要兜住
        print('[zen] %s 拉取失败: %s' % (models_url, str(e)[:120]),
              file=sys.stderr)
        return []
    if not rows:
        return []
    _cache.put(cfg, 'zen', key, {'models': rows,
                                 'ids': [r['id'] for r in rows],
                                 'ts': time.time()})
    return rows

def fetch_models(cfg, refresh=False, timeout=15.0, proxy=None):
    """模型 id 列表 (老接口, 保留给已有调用方)"""
    return [r['id'] for r in fetch_models_detail(cfg, refresh, timeout, proxy)]

def _request(method, url, *, cfg=None, headers=None, data=None, stream=False,
             timeout=TIMEOUT):
    """LLM 通道的出网口: 头/体由调用方全权给定 (raw_headers), 线路与证书归
    net.transport —— 免得 zen 这边的代理与证书判断自成一套。

    这条走 urllib 底层 (不带 impersonate): 对上家来说我们要的只是"一个说
    OpenAI 协议的普通客户端", 塞浏览器指纹没有意义, 还可能踩到对方的协议校验。
    """
    from webtool.net import transport
    return transport.request(method, url, raw_headers=True, via='urllib',
                             stream=stream, headers=headers, data=data,
                             proxy=(cfg or {}).get('proxy'), timeout=timeout)

_norm = urls.norm_key   # 请求去重键 (与 feed 共用同一把尺)

def _tool_names(args):
    """--tools 取值 → build_body 的 names (min 默认 / all / 逗号清单)"""
    return _zp.resolve_tool_names(getattr(args, 'tools', None))

def _unzipper(encoding):
    """增量解压器 (兼容旧名): 实现已下沉 net/stream.decompressor (L7 流式原语)"""
    from webtool.net.stream import decompressor
    return decompressor(encoding)

# 思考标签切分已拆到 cli/zen/think.py (P4); 再导出保兼容
from webtool.cli.zen.think import (  # noqa: E402,F401
    _THINK_TAGS, _END_THINK_TAGS, _ThinkSplitter, _color_on, split_think,
)


def call_zen(model, prompt, system=None, session=None, on_delta=None,
             tool_choice=None, tool_names=None, proxy=None, on_reason=None,
             reasoning_effort=None, max_tokens=None):
    """发一次请求, 流式返回 {ok, status, text, usage, ...}。不重试。"""
    cfg = {'proxy': proxy} if proxy else {}
    body = build_body(model, prompt, system, tool_choice, tool_names,
                      reasoning_effort, max_tokens)
    headers = session.headers() if session else build_headers()
    chat_url = _endpoints()[0]
    t0 = time.time()
    stream_err = []
    text_parts, reason_parts, tool_acc = [], [], {}
    usage = None

    def drain(lines):
        nonlocal usage
        for text, reason, calls, u, err in parse_sse(lines):
            if text:
                text_parts.append(text)
                if on_delta:
                    on_delta(text)
            if reason:
                reason_parts.append(reason)
                if on_reason:
                    on_reason(reason)
            for c in calls:
                acc = tool_acc.setdefault(c['index'],
                                          {'id': None, 'type': None,
                                           'name': '', 'arguments': ''})
                if c.get('id'):
                    acc['id'] = c['id']
                if c.get('type'):
                    acc['type'] = c['type']
                if c.get('name'):
                    acc['name'] += c['name']
                if c.get('arguments'):
                    acc['arguments'] += c['arguments']
            if u:
                usage = u
            if err:
                stream_err.append(err)

    try:
        _resp = _request('POST', chat_url, cfg=cfg, headers=headers, data=body,
                         stream=True)
        if _resp.status_code >= 400:
            # transport 把 4xx/5xx 也交回来 (它不替调用方决定"这算不算失败"),
            # 这里就是明确的失败: 交回状态码与响应体给重试层判断
            return {'ok': False, 'status': _resp.status_code,
                    'elapsed': time.time() - t0, 'error_body': _resp.text,
                    'retry_after': _resp.headers.get('retry-after')}
        from webtool.net import stream as _stream
        saw_done = False
        try:
            for line in _stream.iter_sse(_resp):
                if line.strip() == 'data: [DONE]':
                    saw_done = True
                drain([line])
        except _stream.StreamAborted as e:
            stream_err.append('stream aborted after %d chars: %s'
                              % (len(''.join(text_parts)), e))
        if not saw_done and not stream_err:
            stream_err.append('stream closed without [DONE] and without content')
    except Exception as e:
        # DNS 失败 / 连接被拒 / TLS 失败 / socket 超时。重试层只按状态码判断,
        # 这些必须自己兜住, 否则整个调用冒泡成 traceback。
        return {'ok': False, 'status': 0, 'elapsed': time.time() - t0,
                'error_body': '%s: %s' % (type(e).__name__, str(e)[:300])}

    tool_calls = []
    for idx in sorted(tool_acc):
        c = tool_acc[idx]
        try:
            c['args'] = json.loads(c['arguments']) if c['arguments'].strip() else {}
        except json.JSONDecodeError:
            c['args'] = {'__unparsed__': c['arguments']}
        c.pop('arguments', None)
        tool_calls.append(c)

    text = ''.join(text_parts)
    reason = ''.join(reason_parts)
    # 混在正文里的思考标签: 剥出来并入 reasoning, 正文只留标签之后的部分
    _leaked, text = split_think(text)
    if _leaked.strip():
        reason = (_leaked + '\n' + reason) if reason.strip() else _leaked
    used_reason = False
    if not text.strip() and reason.strip():
        text = reason                       # 少数模型只走 reasoning 通道
        used_reason = True
    base = {'status': 200, 'elapsed': time.time() - t0, 'text': text,
            'usage': usage,
            # 区分"上游没给用量"与"给了但为空": 部分 OpenAI 兼容端点不支持
            # stream_options.include_usage, 会静默省掉 usage 字段。
            'usage_available': bool(usage)}
    if reason.strip():
        base['reasoning'] = reason
        base['text_from_reasoning'] = used_reason

    if any(e == '__TOOLCALLS__' for e in stream_err):
        others = [e for e in stream_err if e != '__TOOLCALLS__']
        return dict(base, ok=False, tool_calls=True,
                    tool_calls_detail=tool_calls, truncated=True,
                    error_body=('model requested a tool call, which this '
                                'client never executes (no tool loop)'
                                + ('; ' + '; '.join(others) if others
                                   else ''))[:300])
    if stream_err:
        return dict(base, ok=False, truncated=True,
                    error_body='stream error: ' + '; '.join(stream_err)[:300])
    if not text.strip():
        return dict(base, ok=False, tool_calls_detail=tool_calls,
                    error_body='empty response (HTTP 200 but no content)')
    if tool_calls:
        return dict(base, ok=True, tool_calls=True,
                    tool_calls_detail=tool_calls)
    return dict(base, ok=True)

def _route(cfg, url, verbose=False):
    """本次请求走哪条线 (None = 直连), 全 zen 只有这一处决定

    交给 netx 判: `proxyhelper.for_url(url)` → 'auto' → netx 查路由表
    (`~/.webtool/rules.json`, 未命中走 proxies.default)。
    **不能**把代理 URL 直接喂进去: 那是"显式指定", 会整体绕过规则表,
    于是给 opencode.ai 配的 direct 形同虚设 (2026-10-14 修)。
    `--no-proxy` 时 do_zen 已把 cfg['proxy'] 置 'direct' → 这里尊重, 强制直连。
    (cfg['proxy'] 现在只承载本次运行的覆盖值, 不再是持久配置)
    """
    from webtool.net import proxyhelper
    route = None if (cfg or {}).get('proxy') == 'direct' else proxyhelper.for_url(url)
    if verbose:
        import sys
        print('[zen] 直连' if not route else '[zen] 走代理 %s' % redact(route),
              file=sys.stderr)
    return route

def call_zen_on_route(model, prompt, cfg=None, verbose=False, **kw):
    """按配置/路由表发一次 (推荐入口)

    别名 `call_zen_direct_then_proxy` 保留是为了不改调用方, 它的名字描述的是
    已取消的 failover —— 线路由 `_route` 一次决定, 请求失败就是失败。
    """
    return call_zen(model, prompt, proxy=_route(cfg, _endpoints()[0], verbose),
                    **kw)

call_zen_direct_then_proxy = call_zen_on_route

def _worth_proxy(res):
    """这次失败值不值得**再试一次** (与线路无关, 只是重试的门槛)。

    只有**传输层/可重试状态**才重试:
      status==0  → DNS 失败 / 连接被拒 / 超时 / TLS 错误
      408 / 429 → 限流, 换个出口可能就通
      5xx       → 上游错误
    不重试的:
      200       → 流已经通了, 后面是语义问题 (截断 / 模型要调工具), 与出口无关,
                   重试只会再失败一次 (和重试层同一条规则)
      其它 4xx  → 请求本身的问题, 换出口 IP 也不会变
    """
    if not res:
        return True
    st = res.get('status', 0)
    if st == 200:
        return False
    if 400 <= st < 500 and st not in (408, 429):
        return False
    return True

RETRY_BASE = 2.0      # 首次退避基数 (秒)

RETRY_CAP = 60.0      # 单次退避上限

RETRY_JITTER = 0.25   # ±25% 抖动, 免得并发重试踩在一起

def _backoff(attempt, retry_after=None):
    """指数退避 + 抖动: 2s → 4s → 8s → 16s …, 封顶 60s

    服务端给了 Retry-After (429 常见) 就听它的; 该值只在 [0, 60] 内有效,
    HTTP-date 形式不解析、退回指数。抖动是必须的: 固定间隔会让重试同步打点。
    """
    if retry_after is not None:
        try:
            return max(0.0, min(RETRY_CAP, float(str(retry_after).strip())))
        except ValueError:
            pass
    raw = RETRY_BASE * (2 ** (attempt - 1))
    # 抖动后封顶: 反过来的话 60s 还能被抖到 75s, "封顶"就不算数了
    return max(0.0, min(RETRY_CAP, raw + raw * RETRY_JITTER * random.uniform(-1, 1)))

def _blames_effort(res):
    """400 的锅是不是 reasoning_effort 背的 (模型不认这个字段/这个值)"""
    if not res or res.get('status') != 400:
        return False
    body = (res.get('error_body') or '').lower()
    return any(h in body for h in ('reasoning_effort', 'reasoning', 'effort'))

def _max_tokens_limit(res):
    """400 是不是 max_tokens 超上限背的锅? 是则返回模型上限, 否则 None

    上游文案: `max_tokens is too large: 200000. This model supports at most
    131072 completion tokens`。各家模型上限不同 (131072 / 32768 ...), 默认值
    不可能对所有模型都对, 所以按上游自报的上限降档, 而不是把默认值调小到
    最保守的那个 —— 调小了能跑的模型也被白限制。
    """
    if not res or res.get('status') != 400:
        return None
    body = res.get('error_body') or ''
    if 'max_tokens' not in body.lower():
        return None
    m = re.search(r'at most\s+(\d+)', body, re.I)
    return int(m.group(1)) if m else None


def call_zen_retry(model, prompt, system=None, session=None, on_delta=None,
                   tool_choice=None, tool_names=None, cfg=None, max_attempts=2,
                   verbose=False, on_reason=None, reasoning_effort=None,
                   max_tokens=None):
    """只重试瞬时故障: 连接错误 / 408 / 429 / 5xx。**同一线路**重试。

    退避是指数的 (见 _backoff): 2/4/8/16s + 抖动, 60s 封顶, 默认 4 次;服务端 Retry-After 优先。

    status==200 的一律不重试 —— 流已经通了, 那是语义问题 (截断 / 要调工具),
    重试除了把已流出去的正文再打一遍没有任何意义。

    线路在循环外一次定死 (cfg + 路由表): 重试只重试同一条线, 不换线。
    """
    import sys
    last = None
    route = _route(cfg, _endpoints()[0], verbose)
    for attempt in range(1, max(1, max_attempts) + 1):
        last = call_zen(model, prompt, system, session, on_delta, tool_choice,
                        tool_names, proxy=route, on_reason=on_reason,
                        reasoning_effort=reasoning_effort,
                        max_tokens=max_tokens)
        if last.get('ok'):
            return last
        status = last.get('status', 0)
        if status == 200:
            return last
        if status == 400 and reasoning_effort and _blames_effort(last):
            # 这个模型不收 reasoning_effort (或那个取值) —— 撤掉字段再打一次,
            # 别让一个可选的强度开关把整个请求废掉。只降级一次, 并明说, 免得
            # 用户以为强度生效了。默认是 medium, 所以这条路径并不罕见。
            print('[zen] 模型 %s 不接受 reasoning_effort=%r, 本次去掉该字段重试'
                  % (model, reasoning_effort), file=sys.stderr)
            reasoning_effort = None
            last = call_zen(model, prompt, system, session, on_delta, tool_choice,
                            tool_names, proxy=route, on_reason=on_reason,
                            reasoning_effort=None, max_tokens=max_tokens)
            if last.get('ok') or last.get('status') == 200:
                return last
            status = last.get('status', 0)
        if status == 400 and max_tokens and (lim := _max_tokens_limit(last)):
            # 默认 200k 是给"上游不校验"时代的; 现在部分模型会硬拒。按它自报的
            # 上限降档重打一次 (只降一次), 并明说实际用了多少, 免得用户以为
            # 200k 生效了。
            print('[zen] 模型 %s 上限 %d tokens, 本次按上限重试'
                  % (model, lim), file=sys.stderr)
            max_tokens = lim
            last = call_zen(model, prompt, system, session, on_delta, tool_choice,
                            tool_names, proxy=route, on_reason=on_reason,
                            reasoning_effort=reasoning_effort,
                            max_tokens=max_tokens)
            if last.get('ok') or last.get('status') == 200:
                return last
            status = last.get('status', 0)
        if 400 <= status < 500 and status not in (408, 429):
            return last
        if attempt < max_attempts:
            wait = _backoff(attempt, last.get('retry_after'))
            if verbose:
                print('[zen] attempt %d/%d got %s, retry in %.1fs'
                      % (attempt, max_attempts, status, wait), file=sys.stderr)
            time.sleep(wait)
    return last

