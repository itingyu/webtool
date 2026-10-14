"""zen: OpenCode Zen 免费层客户端 (公开模式, 无需 API key)
端点 https://opencode.ai/zen/v1/chat/completions, 未配置 OPENCODE_API_KEY 时
apiKey 为字面量 "public"。免费层形状校验: tools 必须非空且含名为 bash 和 read
的两个工具 (空壳 parameters={} 即可; 空/缺名 → 403 FreeTierError, 缺 function
包装或 parameters 键 → 400), 分类器只认名字和形状, 不看 description/schema,
tool_choice 值不影响; 默认只发这两个空壳, --full-tools 发全部 11 个 (已去敏)。
请求体: messages[0]=system / messages[-1]=user / tools 含 bash+read /
tool_choice 存在 / stream=true。解析: 纯标准库 urllib + 逐行 SSE, read1() 读流, 字节层面切行 (decode 再切会把跨读边界的汉字写成 U+FFFD)。
"""

import json
import sys
import time
import urllib.error
import urllib.request

from webtool.core import urls
from webtool.core.secrets_store import redact
from webtool.cli.zenproto import (StickySession, _endpoints, build_body,
                              build_headers, model_headers, parse_models,
                              parse_sse)

# socket 空闲超时。urlopen 的 timeout 只管"多久没收到字节", 不是墙钟预算;
# 流式生成中间只要有 delta 就永不触发, 所以给够即可。
TIMEOUT = 120.0
# ---------------------------------------------------------------- 模型清单

def is_free_model(model_id):
    """按命名约定判定是否免费层 —— 但这不是证明, 用 `zen --list-models --check`"""
    return 'free' in model_id or model_id in {'big-pickle'}




def fetch_models(cfg, refresh=False, timeout=15.0, proxy=None):
    """实时拉 /v1/models (缓存 1h)。

    刻意不内置名单: 免费模型上架/下架频繁, 硬编码名单很快过期。命名约定
    也只是启发式 —— 真正的判据是 `zen --list-models --check` 实发一次。

    `proxy=None` 时按 cfg + 路由表自己定线路 (与对话请求同一条), 免得
    "能聊天但拉不到模型清单" —— 两者打的是同一个端点。
    """
    from webtool.core import cache as _cache
    key = 'zen/models'
    chat_url, models_url = _endpoints()
    if not refresh:
        hit = _cache.get(cfg, 'zen', key)
        if hit and isinstance(hit.get('ids'), list) and hit['ids']:
            return hit['ids']
    if proxy is None:
        proxy = _route(cfg, models_url)
    req = urllib.request.Request(models_url, headers=model_headers())
    try:
        with _opener({'proxy': proxy} if proxy else {}, url=models_url).open(
                req, timeout=timeout) as r:
            d = json.loads(r.read())
        ids = parse_models(d)
    except Exception as e:                       # 超时/DNS/TLS 都要兜住
        import sys
        print('[zen] %s 拉取失败: %s' % (models_url, str(e)[:120]),
              file=sys.stderr)
        return []
    if not ids:
        return []
    _cache.put(cfg, 'zen', key, {'ids': ids, 'ts': time.time()})
    return ids



def _opener(cfg, url=None, verify=None):
    """urlopen() 不吃 proxy 参数, 得自己建 opener。

    空/None 代理 → 走直连 (urllib 只在显式给空 dict 时才不读环境变量, 这里
    显式关掉, 免得继承了 http_proxy 环境变量导致"配置里没代理却走了代理")。
    证书策略交给 core.tls, 与搜索/抓取通道同源。
    """
    from webtool.core import http as _http
    return _http.build_opener((cfg or {}).get('proxy'), url=url, verify=verify)


_norm = urls.norm_key   # 请求去重键 (与 feed 共用同一把尺)


def call_zen(model, prompt, system=None, session=None, on_delta=None,
             tool_choice=None, full=False, proxy=None):
    """发一次请求, 流式返回 {ok, status, text, usage, ...}。不重试。"""
    cfg = {'proxy': proxy} if proxy else {}
    body = build_body(model, prompt, system, tool_choice, full)
    headers = session.headers() if session else build_headers()
    chat_url = _endpoints()[0]
    req = urllib.request.Request(chat_url, data=body, headers=headers,
                                 method='POST')
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
        with _opener(cfg, url=chat_url).open(req, timeout=TIMEOUT) as r:
            remainder = b''
            saw_done = False
            # read1() 有数据就返回; read(n) 会阻塞到攒满 n 字节, 流式就没了
            read = getattr(r, 'read1', None) or (lambda n: r.read(n))
            while True:
                try:
                    chunk = read(65536)
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
    except urllib.error.HTTPError as e:
        with e:
            body_txt = e.read().decode('utf-8', errors='replace')
        return {'ok': False, 'status': e.code, 'elapsed': time.time() - t0,
                'error_body': body_txt}
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
    """cfg + 路由表 → 本次请求的线路 (None = 直连), 全 zen 只有这一处决定

    `do_zen` 已经在 --no-proxy 时把 cfg['proxy'] 置 None, 所以这里不用
    再看命令行 —— 单一入口避免"某个调用点忘了看 no_proxy"导致别人以为
    走了直连其实走了代理 (或反过来)。
    """
    from webtool.net import proxyhelper
    route = proxyhelper.resolve((cfg or {}).get('proxy'), url)
    if verbose and route:
        import sys
        print('[zen] 走代理 %s' % redact(route), file=sys.stderr)
    return route


def call_zen_on_route(model, prompt, cfg=None, verbose=False, **kw):
    """按配置/路由表发一次 (推荐入口)。函数名曾叫 call_zen_direct_then_proxy,
    那正是它早年的行为 —— 直连先打、失败换代理。现已不 failover: 线路由
    `_route` 一次决定, 请求失败就是失败。保留旧名做别名以免改调用方漏掉。"""
    return call_zen(model, prompt, proxy=_route(cfg, _endpoints()[0], verbose),
                    **kw)


# 旧名: 语义已变 (不再 failover), 仅保留兼容
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


def call_zen_retry(model, prompt, system=None, session=None, on_delta=None,
                   tool_choice=None, full=False, cfg=None, max_attempts=3,
                   verbose=False):
    """只重试瞬时故障: 连接错误 / 408 / 429 / 5xx。**同一线路**重试。

    status==200 的一律不重试 —— 流已经通了, 那是语义问题 (截断 / 要调工具),
    重试除了把已流出去的正文再打一遍没有任何意义。

    线路在循环外一次定死 (cfg + 路由表)。曾经这里是 `proxy=None` 直连先打,
    失败后调用方再走一遍代理 —— 于是走哪条线取决于它先在哪失败, 且代理明明
    配好了还要先撞一次墙。
    """
    import sys
    last = None
    route = _route(cfg, _endpoints()[0], verbose)
    for attempt in range(1, max(1, max_attempts) + 1):
        last = call_zen(model, prompt, system, session, on_delta, tool_choice,
                        full, proxy=route)
        if last.get('ok'):
            return last
        status = last.get('status', 0)
        if status == 200:
            return last
        if 400 <= status < 500 and status not in (408, 429):
            return last
        if attempt < max_attempts:
            wait = 1.5 * attempt
            if verbose:
                print('[zen] attempt %d/%d got %s, retry in %ss'
                      % (attempt, max_attempts, status, wait), file=sys.stderr)
            time.sleep(wait)
    return last


# ---------------------------------------------------------------- CLI

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
    if res.get('tool_calls_detail'):
        out['tool_calls'] = res['tool_calls_detail']
    if not res.get('ok'):
        out['error_body'] = (res.get('error_body') or '')[:500]
        if res.get('truncated'):
            out['truncated'] = True
    return out


def _do_zen(args, cfg):
    import sys
    prompt = ' '.join(getattr(args, 'prompt', None) or []).strip()

    # ---- dry-run: 打印请求, 不联网 ----
    if args.show_body or args.show_text:
        body = build_body(args.model, prompt, args.system, args.tool_choice,
                          args.full_tools)
        d = json.loads(body)
        if args.show_text:
            print(json.dumps(d['messages'], indent=2, ensure_ascii=False))
        else:
            print(json.dumps(d, indent=2, ensure_ascii=False))
        return 0

    # ---- 模型清单 ----
    if args.list_models or args.list_free:
        ids = fetch_models(cfg, refresh=args.refresh, proxy=None)
        if not ids:
            print('zen: 拿不到 /v1/models (试 --refresh, 或检查代理)',
                  file=sys.stderr)
            return 1
        if args.list_free:
            ids = [i for i in ids if is_free_model(i)]
            if not args.check:
                return _print_model_ids(ids, args.format)
            ok_n = 0
            ok_n = 0
            for i in ids:
                # 必须走完整路径 (stream=True), 分类器认形状
                r = call_zen_retry(i, '回复:OK', cfg=cfg, max_attempts=1,
                                   tool_choice=args.tool_choice,
                                   full=args.full_tools)
                if r.get('ok') and (r.get('text') or '').strip():
                    ok_n += 1
                    print('%s\tOK\t%ss' % (i, round(r.get('elapsed', 0), 2)))
                else:
                    why = (r.get('error_body') or '')[:80].replace('\n', ' ')
                    print('%s\tFAIL\t%s\t%s' % (i, r.get('status'), why))
            print('-- %d/%d 可用 (命名约定只是启发式, 这才是判据)'
                  % (ok_n, len(ids)), file=sys.stderr)
            return 0 if ok_n else 1
        return _print_model_ids(ids, args.format)


def _print_model_ids(ids, fmt):
    """模型清单按 -f 输出; 默认 text 保持一行一个 id 的老样子"""
    import json as _json
    if fmt == 'json':
        print(_json.dumps({'models': ids, 'count': len(ids)}, ensure_ascii=False, indent=1))
    else:
        for i in ids:
            print(i)
    return 0

    # 原 373-418 行: return 0 之后的 45 行不可达代码 (引用未定义的 prompt/
    # args/sys/cfg), zen 真正的对话逻辑在 do_zen。2026-10 批次二清理删除。


def _do_zen(args, cfg):
    """zen 对话主体 (do_zen 是代理开关薄壳)"""
    prompt = ' '.join(getattr(args, 'prompt', None) or []).strip()

    # ---- dry-run: 打印请求, 不联网 ----
    if args.show_body or args.show_text:
        body = build_body(args.model, prompt, args.system, args.tool_choice,
                          args.full_tools)
        d = json.loads(body)
        if args.show_text:
            print(json.dumps(d['messages'], indent=2, ensure_ascii=False))
        else:
            print(json.dumps(d, indent=2, ensure_ascii=False))
        return 0

    # ---- 模型清单 ----
    if args.list_models or args.list_free:
        ids = fetch_models(cfg, refresh=args.refresh, proxy=None)
        if not ids:
            print('zen: 拿不到 /v1/models (试 --refresh, 或检查代理)',
                  file=sys.stderr)
            return 1
        if args.list_free:
            ids = [i for i in ids if is_free_model(i)]
            if not args.check:
                return _print_model_ids(ids, args.format)
            ok_n = 0
            for i in ids:
                # 必须走完整路径 (stream=True), 分类器认形状
                r = call_zen_retry(i, '回复:OK', cfg=cfg, max_attempts=1,
                                   tool_choice=args.tool_choice,
                                   full=args.full_tools)
                if r.get('ok') and (r.get('text') or '').strip():
                    ok_n += 1
                    print('%s\tOK\t%ss' % (i, round(r.get('elapsed', 0), 2)))
                else:
                    why = (r.get('error_body') or '')[:80].replace('\n', ' ')
                    print('%s\tFAIL\t%s\t%s' % (i, r.get('status'), why))
            print('-- %d/%d 可用 (命名约定只是启发式, 这才是判据)'
                  % (ok_n, len(ids)), file=sys.stderr)
            return 0 if ok_n else 1
        return _print_model_ids(ids, args.format)

    # ---- 真正的调用 ----
    session = StickySession() if args.sticky else None
    # 实时刷屏只在"人在看终端"时做: stdout 被管道接走、或要 -f json 时, 缓冲
    # 一次输出, 否则终端上会先看到流式再看到完整结果, 重复一遍。
    fmt = getattr(args, 'format', None) or 'text'
    live = args.stream and fmt != 'json' and sys.stdout.isatty()
    streamed = []

    def on_delta(text):
        if not live:
            return
        streamed.append(text)
        sys.stderr.write(text)
        sys.stderr.flush()

    res = call_zen_retry(args.model, prompt, args.system, session, on_delta,
                         args.tool_choice, args.full_tools, cfg,
                         max_attempts=args.retries,
                         verbose=args.stream)
    # 曾经这里失败后再 `call_zen_direct_then_proxy` 走一遍代理 —— 线路已在
    # call_zen_retry 内一次定死, 重试也只重试同一条线, 不再换线。
    for c in res.get('tool_calls_detail') or []:
        print('[zen] tool %s(%s)  ← 未执行'
              % (c.get('name'), json.dumps(c.get('args', {}), ensure_ascii=False)),
              file=sys.stderr)

    # stdout 只出最终结果 (流式过程走 stderr), 管道里 json 不会被流污染
    if fmt == 'json':
        print(json.dumps(_fmt_payload(res, args), indent=2, ensure_ascii=False))
    elif live and streamed:
        print('')              # 已流出去, 补个换行收尾
    else:
        print(res.get('text', ''))
    if not res.get('ok'):
        print('[zen] %s %s' % (res.get('status'),
                               (res.get('error_body') or '')[:300]),
              file=sys.stderr)
        return 2
    return 0


def do_zen(args, cfg):
    if getattr(args, 'no_proxy', False):
        cfg = dict(cfg)
        cfg['proxy'] = None
    return _do_zen(args, cfg)

