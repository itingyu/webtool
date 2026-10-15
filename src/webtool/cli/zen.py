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
import zlib
import random
import sys
import time

from webtool.core import urls
from webtool.core.secrets_store import redact
from webtool.cli import zenproto as _zp
from webtool.cli.zenproto import (StickySession, _endpoints, build_body,
                                  build_headers, model_headers,
                                  parse_models_full, parse_sse)

# socket 空闲超时。urlopen 的 timeout 只管"多久没收到字节", 不是墙钟预算;
# 流式生成中间只要有 delta 就永不触发, 所以给够即可。
TIMEOUT = 120.0
# 模型清单

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
    from webtool.core import cache as _cache
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
    """按 Content-Encoding 增量解压 (urllib 拿到压缩流不会自己解)

    头既然照真机发了 `Accept-Encoding: gzip, deflate, br, zstd`, 上游哪天开始
    压缩就得能接住 —— 否则流式解析静默变乱码, 比报错更难查。
    上游目前不压缩 SSE (Content-Encoding 空), 这里是兜底。
    gzip/deflate 走 stdlib 增量解; br/zstd 没有 stdlib 支持, 直接明确报错。
    """
    enc = (encoding or '').strip().lower()
    if enc in ('', 'identity'):
        return lambda b: b
    if enc in ('gzip', 'x-gzip'):
        d = zlib.decompressobj(16 + zlib.MAX_WBITS)
    elif enc == 'deflate':
        d = zlib.decompressobj(zlib.MAX_WBITS)
    else:
        def _no_impl(_b):
            raise RuntimeError('上游返回 %s 压缩, 本地没有对应库 (装 brotli/'
                               'zstandard, 或从 Accept-Encoding 去掉它)' % enc)
        return _no_impl
    return lambda b: d.decompress(b) if b else b


# 思考标签

# 模型把思考塞进正文时用的标签 (留作流式与非流式两条路共同识别)
_THINK_TAGS = ('<think>', '<thinking>', '<reasoning>')
_END_THINK_TAGS = ('</think>', '</thinking>', '</reasoning>')


def split_think(text):
    """把混在正文里的思考标签剥出来 → (思考, 正文)

    有些模型不走 reasoning 通道, 而是把思考直接写进 content 并用 `</think>`
    之类标签包着 (上游偶尔只留闭标签)。见到闭标签: 它前面的是思考, 后面才是
    答案。只有开标签没有闭标签 (被截断) 则整段算思考。没有标签原样返回。
    """
    if not text:
        return '', text
    low = text.lower()
    hit = None                                # (位置, 标签)
    for tag in _END_THINK_TAGS:
        i = low.find(tag)
        if i != -1 and (hit is None or i < hit[0]):
            hit = (i, tag)
    if hit is None:
        for tag in _THINK_TAGS:
            if tag in low:
                return text, ''
        return '', text
    i, tag = hit
    return text[:i], text[i + len(tag):].lstrip('\n')


class _ThinkSplitter:
    """流式剥思考标签: 标签绝不原样打到屏幕, 标签内的文字算思考。

    标签可能被切成两个 chunk, 所以尾部的"可能是标签前缀"的部分先扣在手里,
    等下一个 chunk 到了再判。分类只影响**渲染**(上文是否算思考), 最终正文由
    `split_think` 在整段上定性, 两者一致。
    """

    _TAGS = _THINK_TAGS + _END_THINK_TAGS
    _MAX = max(len(t) for t in _TAGS)

    def __init__(self):
        self.pending = ''
        self.in_think = False

    def _classify(self, piece):
        return ('think' if self.in_think else 'text', piece)

    def feed(self, chunk):
        self.pending += chunk
        out = []
        while True:
            low = self.pending.lower()
            hit = None
            for tag in self._TAGS:
                i = low.find(tag)
                if i != -1 and (hit is None or i < hit[0]):
                    hit = (i, tag)
            if hit is None:
                break
            i, tag = hit
            if self.pending[:i]:
                out.append(self._classify(self.pending[:i]))
            self.in_think = not tag.startswith('</')
            self.pending = self.pending[i + len(tag):]
        keep = 0
        low = self.pending.lower()
        for tag in self._TAGS:                     # 扣住可能是标签开头的尾巴
            for n in range(min(len(tag) - 1, len(low)), 0, -1):
                if low.endswith(tag[:n]):
                    keep = max(keep, n)
                    break
        if keep:
            ready, self.pending = self.pending[:-keep], self.pending[-keep:]
        else:
            ready, self.pending = self.pending, ''
        if ready:
            out.append(self._classify(ready))
        return out

    def flush(self):
        out = [self._classify(self.pending)] if self.pending else []
        self.pending = ''
        return out


# 终端着色

_C_RESET = '\033[0m'
_C_THINK = '\033[90m'      # 灰: 思考
_C_TOOL = '\033[33m'       # 黄: 工具调用
_C_HEAD = '\033[36m'       # 青: 分段标签


def _color_on():
    """终端着色开关: 非终端 / NO_COLOR 一律不上色 (管道与日志里不该混转义序列)"""
    import os
    if os.environ.get('NO_COLOR'):
        return False
    try:
        return bool(sys.stdout.isatty())
    except Exception:
        return False


def call_zen(model, prompt, system=None, session=None, on_delta=None,
             tool_choice=None, tool_names=None, proxy=None, on_reason=None,
             reasoning_effort=None, on_tool=None, max_tokens=None):
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
                    _first = not acc['name']       # 只报一次: 名字刚出现时
                    acc['name'] += c['name']
                    if _first and on_tool:
                        on_tool(acc['name'])
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
        with _resp.raw as r:
            remainder = b''
            saw_done = False
            # read1() 有数据就返回; read(n) 会阻塞到攒满 n 字节, 流式就没了
            read = getattr(r, 'read1', None) or (lambda n: r.read(n))
            unzip = _unzipper(r.headers.get('Content-Encoding'))
            while True:
                try:
                    chunk = unzip(read(65536))
                except (TimeoutError, OSError) as e:
                    stream_err.append('stream aborted after %d chars: %s: %s'
                                      % (len(''.join(text_parts)),
                                         type(e).__name__, str(e)[:100]))
                    break
                if not chunk:
                    break
                remainder += chunk
                # 字节层切行: 整块 decode 再切会把被边界截断的汉字写成 U+FFFD
                if b'\n' not in remainder:
                    continue
                *complete, remainder = remainder.split(b'\n')
                lines = [c.decode('utf-8', errors='replace') for c in complete]
                saw_done = saw_done or any(l.strip() == 'data: [DONE]'
                                           for l in lines)
                drain(lines)
            if remainder:
                drain([remainder.decode('utf-8', errors='replace')])
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


# 旧名别名: 名字描述的是已取消的 failover, 只用于兼容调用方
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

def call_zen_retry(model, prompt, system=None, session=None, on_delta=None,
                   tool_choice=None, tool_names=None, cfg=None, max_attempts=2,
                   verbose=False, on_reason=None, reasoning_effort=None,
                   on_tool=None, max_tokens=None):
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
                        reasoning_effort=reasoning_effort, on_tool=on_tool,
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
                            reasoning_effort=None, on_tool=on_tool,
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


# CLI

def _fmt_payload(res, args):
    """-f text/markdown 只要答案; json 给完整结构 (usage / reasoning / tool_calls)"""
    out = {
        'cmd': 'zen',
        'model': args.model,
        'ok': res.get('ok'),
        'status': res.get('status'),
        'elapsed': round(res.get('elapsed', 0), 2),
        'text': res.get('text', ''),
        'usage': res.get('usage'),
        'usage_available': res.get('usage_available', False),
    }
    if res.get('reasoning'):
        out['reasoning'] = res['reasoning']
        out['text_from_reasoning'] = res.get('text_from_reasoning', False)
    if getattr(args, 'think', None):
        out['reasoning_effort'] = args.think
    if res.get('tool_calls_detail'):
        out['tool_calls'] = res['tool_calls_detail']
    if not res.get('ok'):
        out['error_body'] = (res.get('error_body') or '')[:500]
        if res.get('truncated'):
            out['truncated'] = True
    return out


def _disp_width(text):
    """终端显示宽度: 中日韩全角字符占两列"""
    import unicodedata
    return sum(2 if unicodedata.east_asian_width(c) in 'WF' else 1 for c in text)


def _pad(text, width):
    return text + ' ' * max(0, width - _disp_width(text))


def _table(header, body):
    """等宽对齐的纯文本表; 列宽按显示宽度算, 中文表头不对齐才怪"""
    widths = [_disp_width(h) for h in header]
    for line in body:
        for i, cell in enumerate(line):
            widths[i] = max(widths[i], _disp_width(cell))
    out = ['  '.join(_pad(h, w) for h, w in zip(header, widths)).rstrip(),
           '  '.join('-' * w for w in widths)]
    out += ['  '.join(_pad(c, w) for c, w in zip(line, widths)).rstrip()
            for line in body]
    return '\n'.join(out)


def _fmt_ts(ts):
    """接口给的 created (epoch 秒) → 本地时间; 给不了就 '-'"""
    import datetime
    if not ts:
        return '-'
    try:
        return datetime.datetime.fromtimestamp(int(ts)).strftime('%m-%d %H:%M')
    except (ValueError, OSError, OverflowError):
        return '-'


def _print_models(rows, fmt):
    """模型清单: 列全部取自 /v1/models 的响应字段 (id/created/owned_by)。

    免费层是命名约定推断的, 表尾注明 —— 不内置任何本地模型元数据: 免费层
    名单上游每周都在变, 写进来第二天就是错的。
    """
    import json as _json
    if fmt == 'json':
        print(_json.dumps({'models': rows, 'count': len(rows)},
                          ensure_ascii=False, indent=1))
        return 0
    body = [[r.get('id') or '-', r.get('owned_by') or '-',
             _fmt_ts(r.get('created')),
             '是' if is_free_model(r.get('id') or '') else '否']
            for r in rows]
    print(_table(['模型', '提供方', '上架', '免费层'], body))
    print(f'\n共 {len(body)} 个模型'
          f' (免费层 {sum(1 for b in body if b[3] == "是")} 个)')
    print('提供方/上架来自接口字段; 免费层按命名约定推断, 不是接口字段')
    for idx, name in ((1, '提供方'), (2, '上架时间')):
        vals = {b[idx] for b in body}
        if len(vals) == 1 and next(iter(vals)) != '-':
            print(f'注: {name}本批全部为 {next(iter(vals))} —— '
                  f'上游这批就是这个值, 不是渲染丢了')
    return 0


def _brief_error(status, body):
    """403/400 的正文往往是一坨 JSON, 表里要的是里面那句话"""
    body = (body or '').strip().replace('\n', ' ')
    try:
        d = json.loads(body)
        err = d.get('error')
        msg = err.get('message') if isinstance(err, dict) else err
        body = str(msg or d.get('message') or body)
    except ValueError:
        pass
    return ('HTTP %s %s' % (status, body)).strip()[:60]


def _print_check(rows, fmt):
    """--check 的结果: 真调一次才算数, 模型名说明不了任何事"""
    import json as _json
    if fmt == 'json':
        print(_json.dumps({'checked': rows, 'count': len(rows)},
                          ensure_ascii=False, indent=1))
        return 0 if any(r['ok'] for r in rows) else 1
    body, ok_n = [], 0
    for r in rows:
        ok_n += 1 if r['ok'] else 0
        if r['ok']:
            brief = r['text'][:28].replace('\n', ' ') or '(空)'
            body.append([r['id'], '可用', f"{r['elapsed']}s", brief])
        else:
            body.append([r['id'], '不可用', '-',
                         _brief_error(r['status'], r['error'])])
    print(_table(['模型', '实测', '耗时', '首答 / 失败原因'], body))
    print(f'\n{ok_n}/{len(rows)} 可用')
    return 0 if ok_n else 1


def _tool_warn(args):
    """`--tools` 选得不合规时的提醒 (闸门要 bash+read 同时在, 名字还要真存在)

    只提醒不拦: 探闸门本身就需要故意发缺件的请求。
    """
    names = _tool_names(args)
    if names in (None, 'all'):
        return None
    known = {t['function']['name'] for t in _zp.tools('all')}
    miss = [n for n in _zp.DEFAULT_TOOL_NAMES if n not in names]
    unknown = [n for n in names if n not in known]
    tips = []
    if miss:
        tips.append('闸门要求 bash+read 同时在, 当前缺 %s (大概率 403)' % '/'.join(miss))
    if unknown:
        tips.append('工具名不存在会被丢掉: %s' % '/'.join(unknown))
    return '; '.join(tips) or None


def _show_view(args):
    """--show <view> / --dry-run / 旧名 --show-body|--show-text → 要看哪一段

    --dry-run 就是最常用的 `--show request` (URL + 头 + 体, 排查闸门全看得到);
    旧名保留成隐藏别名, 免得老习惯撞墙。没给则返回 None (正常发请求)。
    """
    v = (getattr(args, 'show', None) or '').strip().lower()
    if getattr(args, 'dry_run', False) and not v:
        v = 'request'
    if not v:
        if getattr(args, 'show_body', False):
            v = 'body'
        elif getattr(args, 'show_text', False):
            v = 'text'
    if not v:
        return None
    if v not in _zp.SHOW_VIEWS:
        raise SystemExit('zen: --show 只认 %s, 给的 %r'
                         % ('/'.join(_zp.SHOW_VIEWS), v))
    return v


def _do_zen(args, cfg):
    """zen 对话主体 (do_zen 是代理开关薄壳)"""
    # 命令行层 (cli/app.py) 已经把变长参数拼成了字符串; 这里只兜住直接传 list
    # 的调用方 —— 对字符串再 join 一次会逐**字符**插空格 ("hi" → "h i")。
    prompt = getattr(args, 'prompt', None) or ''
    if not isinstance(prompt, str):
        prompt = ' '.join(prompt)
    prompt = prompt.strip()

    tip = _tool_warn(args)
    if tip:
        print('zen: %s' % tip, file=sys.stderr)

    # dry-run: 打印请求, 不联网
    view = _show_view(args)
    if view:
        ses = StickySession() if args.sticky else None
        pv = _zp.request_preview(args.model, prompt, args.system,
                                 args.tool_choice, _tool_names(args),
                                 ses_id=ses.ses_id if ses else None,
                                 reasoning_effort=getattr(args, 'think', None),
                                 max_tokens=getattr(args, 'max_tokens', None))
        if view == 'headers':
            out = pv['headers']
        elif view == 'body':
            out = pv['body']
        elif view == 'text':
            out = pv['body']['messages']
        else:
            out = pv
        if args.format == 'json':
            print(json.dumps(out, indent=2, ensure_ascii=False))
        elif view == 'request':
            print('%s %s' % (pv['method'], pv['url']))
            for k, v in pv['headers'].items():
                print('%s: %s' % (k, v))
            print()
            print(json.dumps(pv['body'], indent=2, ensure_ascii=False))
        elif view == 'headers':
            for k, v in pv['headers'].items():
                print('%s: %s' % (k, v))
        else:
            print(json.dumps(out, indent=2, ensure_ascii=False))
        return 0

    # 模型清单
    if args.list_models or args.list_free:
        rows = fetch_models_detail(cfg, refresh=args.refresh, proxy=None)
        if not rows:
            print('zen: 拿不到 /v1/models (试 --refresh, 或检查代理)',
                  file=sys.stderr)
            return 1
        if args.list_free:
            rows = [r for r in rows if is_free_model(r.get('id') or '')]
        if not args.check:
            return _print_models(rows, args.format)
        # --check: 真调一遍。默认只验免费层那几行 —— 全表 80+ 个既慢又容易
        # 被上游限流, 而这里要挑的就是免费层; 想全验给 --check-all。
        probe = rows if getattr(args, 'check_all', False) else \
            [r for r in rows if is_free_model(r.get('id') or '')]
        got = []
        for r in probe:
            res = call_zen_retry(r['id'], '回复:OK', cfg=cfg, max_attempts=1,
                                 tool_choice=args.tool_choice,
                                 tool_names=_tool_names(args))
            got.append({'id': r['id'], 'ok': bool(res.get('ok')),
                        'status': res.get('status'),
                        'elapsed': round(res.get('elapsed') or 0, 2),
                        'text': (res.get('text') or '').strip(),
                        'error': (res.get('error_body') or '').strip()})
        return _print_check(got, args.format)

    # 真正的调用
    session = StickySession() if args.sticky else None
    # 实时刷屏只在"人在看终端"时做: stdout 被管道接走、或要 -f json 时, 缓冲
    # 一次输出, 否则终端上会先看到流式再看到完整结果, 重复一遍。
    fmt = getattr(args, 'format', None) or 'text'
    tty = sys.stdout.isatty()
    live = args.stream and fmt != 'json' and tty
    show_reason = getattr(args, 'reasoning', True) and fmt != 'json'
    color = _color_on()
    # 人在终端: 思考与回答都走 stdout, 用 [思考]/[回答] 分段并**上色区分** ——
    # 思考灰、工具调用黄、分段标签青、正文原色。推理过程是输出的一部分, 不是
    # 错误, 不塞 stderr。stdout 被重定向时只留回答 (思考挪 stderr), 管道干净。
    reason_sink = sys.stdout if tty else sys.stderr
    streamed = []
    marks = {'reason': False, 'text': False}
    splitter = _ThinkSplitter()

    def _head(tag):
        return (_C_HEAD + tag + _C_RESET) if color else tag

    def on_reason(chunk):
        if not (live and show_reason):
            return
        if not marks['reason']:
            marks['reason'] = True
            sys.stdout.write(_head('[思考] ') + (_C_THINK if color else ''))
        sys.stdout.write(chunk)
        sys.stdout.flush()

    def _emit_text(piece):
        streamed.append(piece)
        if show_reason and not marks['text']:
            marks['text'] = True
            if marks['reason']:                # 从灰色思考切回原色正文
                sys.stdout.write((_C_RESET if color else '') + '\n'
                                 + _head('[回答] '))
        sys.stdout.write(piece)

    def on_delta(text):
        if not live:
            return
        for kind, piece in splitter.feed(text):   # 混在正文里的思考标签就地分流
            if kind == 'think':
                on_reason(piece)
            else:
                _emit_text(piece)
        sys.stdout.flush()

    def on_tool(name):
        if not live:
            return
        sys.stdout.write('\n%s[工具] %s(…)%s'
                         % ((_C_TOOL if color else ''), name,
                            (_C_RESET if color else '')))
        sys.stdout.flush()

    res = call_zen_retry(args.model, prompt, args.system, session, on_delta,
                         args.tool_choice, _tool_names(args), cfg,
                         max_attempts=args.retries,
                         verbose=args.stream, on_reason=on_reason,
                         reasoning_effort=getattr(args, 'think', None),
                         on_tool=on_tool,
                         max_tokens=getattr(args, 'max_tokens', None))
    # 线路已在 call_zen_retry 内一次定死, 重试只重试同一条线。
    if live:
        for kind, piece in splitter.flush():      # 收尾: 扣在缓冲里的尾巴
            if kind == 'think':
                on_reason(piece)
            else:
                _emit_text(piece)
        if color and (marks['reason'] or marks['text']):
            sys.stdout.write(_C_RESET)
        sys.stdout.flush()
    else:
        for c in res.get('tool_calls_detail') or []:
            line = '[工具] %s(%s)  ← 本客户端不执行工具, 仅展示' % (
                c.get('name'), json.dumps(c.get('args', {}), ensure_ascii=False))
            print(line, file=sys.stderr)

    # stdout 只出最终结果 (流式内容已随 on_delta 打出), 管道里 json 不会被流污染
    if fmt == 'json':
        print(json.dumps(_fmt_payload(res, args), indent=2, ensure_ascii=False))
    elif live and streamed:
        print('')              # 已流出去, 补个换行收尾
    else:
        # 缓冲模式: 思考先打 (终端走 stdout, 重定向走 stderr), 回答只走 stdout
        if show_reason and (res.get('reasoning') or '').strip():
            think = res['reasoning'].strip()
            print('%s %s%s%s' % (_head('[思考]'), _C_THINK if color else '', think,
                                 _C_RESET if color else ''), file=reason_sink)
            if tty:                       # 终端上给回答也起个头, 两段一眼分得开
                print('%s %s' % (_head('[回答]'), res.get('text', '')))
                return 0 if res.get('ok') else 2
        print(res.get('text', ''))
    if not res.get('ok'):
        print('%s %s %s' % (_head('[zen]'), res.get('status'),
                            (res.get('error_body') or '')[:300]),
              file=sys.stderr)
        return 2
    return 0


def do_zen(args, cfg):
    if getattr(args, 'no_proxy', False):
        cfg = dict(cfg)
        # 必须写 'direct' 这个字符串 —— 下游 proxyhelper 把 None 解释成 "auto"
        # (跟配置/规则表走), 于是 --no-proxy 会绕一圈又走回代理; 'direct' 才是
        # 强制直连的约定值 (netx / transport / core.http 三处都认)。
        cfg['proxy'] = 'direct'
    return _do_zen(args, cfg)

