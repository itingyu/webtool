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
import sys

from webtool.cli import zenproto as _zp
from webtool.cli.zenproto import StickySession
from webtool.core.errors import UsageError

# ── 对外再导出: 拆包前这些名字在本模块上, 拆包后调用方不该改 import ──
# (私有名与常量不在此列 —— 由下面的 __getattr__ 转发到子模块, 逐个再导出既冗长
#  又会和子模块改名脱节)
from webtool.cli.zen.client import call_zen as call_zen
from webtool.cli.zen.client import call_zen_on_route as call_zen_on_route
from webtool.cli.zen.client import call_zen_retry as call_zen_retry
from webtool.cli.zen.client import fetch_models as fetch_models
from webtool.cli.zen.client import fetch_models_detail as fetch_models_detail
from webtool.cli.zen.client import split_think as split_think
from webtool.cli.zen.client import _color_on
from webtool.cli.zen.client import _tool_names
from webtool.cli.zen.client import is_free_model
from webtool.cli.zen.render import _C_RESET
from webtool.cli.zen.render import _C_THINK
from webtool.cli.zen.render import StreamView
from webtool.cli.zen.render import agent_payload
from webtool.cli.zen.render import print_agent_step
from webtool.cli.zen.render import print_tool_calls
from webtool.cli.zen.render import _fmt_payload
from webtool.cli.zen.render import _print_check
from webtool.cli.zen.render import _print_models
from webtool.cli.zen.render import _show_view
from webtool.cli.zen.render import _tool_warn


def __getattr__(name):
    """兼容旧导入路径: 私有名与常量由本函数转发到子模块

    拆包前 _route/_backoff/RETRY_* 等都在本模块上, 逐个再导出既冗长又会和
    子模块改名脱节; 这里兜底转发, 公开名仍显式再导出 (可见即可查)。
    """
    import importlib
    for _m in ('client', 'render'):
        _mod = importlib.import_module('webtool.cli.zen.' + _m)
        try:
            return getattr(_mod, name)
        except AttributeError:
            continue
    raise AttributeError(
        "module %r has no attribute %r" % (__name__, name))


def _lim_clamp(args):
    """预览用的 max_tokens: 记住的上限会降档, dry-run 也得照实显示

    预览里装作没降档的话, `--show body` 就成了骗人的 —— 而它正是用来核对
    "我发出去的到底是什么"的。
    """
    from webtool.cli.zen import limits as _lim
    v, known = _lim.clamp(getattr(args, 'model', None),
                          getattr(args, 'max_tokens', None))
    if known:
        print('zen: 模型 %s 上次报过上限 %d tokens, 这里按上限走 '
              '(--limits 看记住的值)' % (args.model, known), file=sys.stderr)
    return v

def _agent_ctx(args, cfg):
    """agent 模式的前置件: 工具名 / 工具定义 / 工作空间 / 会话名

    会话名三条来源 (优先级从高到低): --session <名> > --continue (最近一条)
    > 不带会话 (一次性跑)。工作空间与工具名在这里定死, 后面每轮都用同一份 ——
    中途换工作空间的话, 第一轮读到的文件和最后一轮读到的不是同一个目录。
    """
    from webtool.cli.zen import agent as _ag
    from webtool.cli.zen import session as _ses
    from webtool.cli.zen.workspace import Workspace
    names = _ag.resolve_names(getattr(args, 'agent_tools', None))
    args._agent_names = names
    ws = Workspace.resolve(getattr(args, 'workspace', None))
    args.workspace_resolved = ws
    name = getattr(args, 'session', None)
    if not name and getattr(args, 'continue_session', False):
        name = _ses.latest()
        if not name:
            raise UsageError('--continue: 还没有任何会话, 先用 --session <名> 开一条')
        print('zen: 接上会话 %s' % name, file=sys.stderr)
    args.session = name
    return names, ws, name


def _agent_messages(args, prompt, ws, names, ses_name):
    """这一轮要发出去的 messages (接旧会话 or 开新的)"""
    from webtool.cli.zen import agent as _ag
    from webtool.cli.zen import session as _ses
    system = _ag.agent_system(args.system, names, ws)
    if not ses_name:
        return _ag.initial_messages(system, prompt)
    old = _ses.load(ses_name)
    if not old:
        return _ag.initial_messages(system, prompt)
    print('zen: 会话 %s 有 %d 条历史, 接上'
          % (ses_name, len(old.get('messages') or [])), file=sys.stderr)
    return _ag.resume_messages(old['messages'], system, prompt)


def _do_agent(args, cfg, prompt):
    """--agent: 多轮工具循环 (模型要工具 → 执行 → 回喂 → 再问)"""
    from webtool.cli.zen import agent as _ag
    from webtool.cli.zen import session as _ses

    names, ws, ses_name = _agent_ctx(args, cfg)
    if not prompt:
        raise UsageError('--agent 要给问题 (留空只会拿到一个"请输入问题"的回合)')
    session = StickySession() if args.sticky else None
    fmt = getattr(args, 'format', None) or 'text'
    tty = sys.stdout.isatty()
    live = args.stream and fmt != 'json' and tty
    show_reason = getattr(args, 'reasoning', True) and fmt != 'json'
    color = _color_on()
    reason_sink = sys.stdout if tty else sys.stderr
    sv = StreamView(live=live, show_reason=show_reason, color=color,
                    sink=sys.stdout, reason_sink=reason_sink)
    ctx = {'workspace': ws, 'cfg': cfg, 'max_chars': args.agent_max_chars,
           'tool_names': names}
    max_tokens = args.max_tokens
    tool_defs = _ag.tool_specs(names)

    def call_turn(messages):
        # 线路在 call_zen_retry 内一次定死, 每轮都走同一条线
        return call_zen_retry(args.model, None, None, session, sv.on_delta,
                              args.tool_choice, _tool_names(args), cfg,
                              max_attempts=args.retries, verbose=args.stream,
                              on_reason=sv.on_reason,
                              reasoning_effort=getattr(args, 'think', None),
                              max_tokens=max_tokens, messages=messages,
                              tool_defs=tool_defs, allow_tool_calls=True)

    messages = _agent_messages(args, prompt, ws, names, ses_name)

    def on_tools(calls, step):
        shown = {'step': step, 'call': calls[0] if len(calls) == 1
                 else {'name': '%d 个工具' % len(calls),
                       'args': {'calls': [c.get('name') for c in calls]}}}
        print_agent_step(shown, color=color, sink=sys.stdout)
        sv.round_break()
        return _ag.exec_calls(calls, ctx, sink=sys.stdout)

    def after_step(msgs, step):
        # 每轮存一次: 中途断网/超限时已经问过的还在, 下次能接着聊
        if ses_name:
            _ses.save(ses_name, msgs, model=args.model, workspace=ws)

    res, steps, messages = _ag.agent_loop(call_turn, messages, on_tools,
                                          max_steps=args.agent_max_steps,
                                          after_step=after_step)
    sv.finish()
    if ses_name:
        _ses.save(ses_name, messages, model=args.model, workspace=ws)

    if fmt == 'json':
        print(json.dumps(agent_payload(res, args, steps), indent=2,
                         ensure_ascii=False))
    else:
        if res.get('reasoning') and show_reason and not live:
            print('[思考] %s' % res['reasoning'].strip(), file=reason_sink)
        if live and sv.printed:
            print('')
        print(res.get('text', ''))
        if res.get('stopped_by_limit'):
            print('[zen] 达到 --agent-max-steps=%d 上限, 模型仍在调工具; '
                  '加大它或把问题拆小' % args.agent_max_steps, file=sys.stderr)
        if ses_name:
            print('[zen] 会话 %s 已存 (%d 轮, --continue 接着聊)'
                  % (ses_name, steps), file=sys.stderr)
    if not res.get('ok'):
        print('[zen] %s %s' % (res.get('status'), (res.get('error_body') or '')[:300]),
              file=sys.stderr)
        return 2
    return 0


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

    # 记住的模型输出上限: zen limits 读出来, --forget 清掉 (都不联网)
    if getattr(args, 'limits', False) or getattr(args, 'forget_limits', False):
        from webtool.cli.zen import limits as _lim
        if getattr(args, 'forget_limits', False):
            n = _lim.forget(args.model if getattr(args, 'model_explicit', False)
                            else None)
            print('已忘掉 %d 条记住的上限' % n)
            return 0
        lines = _lim.describe()
        if args.format == 'json':
            print(json.dumps(_lim.load(), indent=2, ensure_ascii=False))
        else:
            for ln in lines:
                print(ln)
        return 0

    # 会话管理 (不联网): --sessions 列 / --clear-session 删
    if getattr(args, 'sessions', False) or getattr(args, 'clear_session', False):
        from webtool.cli.zen import session as _ses
        if args.clear_session:
            name = args.session or _ses.latest()
            if not name:
                print('zen: 没有会话可清', file=sys.stderr)
                return 2
            n = _ses.remove(name)
            print('已删会话 %s' % name if n else '没有会话 %s 可删' % name)
            return 0 if n else 1
        if args.format == 'json':
            print(json.dumps({'sessions': _ses.recent()}, indent=2,
                             ensure_ascii=False))
            return 0
        print(_ses.fmt_rows(_ses.recent()))
        return 0

    # dry-run: 打印请求, 不联网
    view = _show_view(args)
    if view:
        ses = StickySession() if args.sticky else None
        pv = None
        if getattr(args, 'agent', False):
            from webtool.cli.zen import agent as _ag
            names, ws, _ = _agent_ctx(args, cfg)
            pv = _zp.request_preview(
                args.model, prompt, args.system, args.tool_choice,
                _tool_names(args), ses_id=ses.ses_id if ses else None,
                reasoning_effort=getattr(args, 'think', None),
                max_tokens=_lim_clamp(args),
                messages=_agent_messages(args, prompt, ws, names, args.session),
                tool_defs=_ag.tool_specs(names))
        else:
            pv = _zp.request_preview(args.model, prompt, args.system,
                                     args.tool_choice, _tool_names(args),
                                     ses_id=ses.ses_id if ses else None,
                                     reasoning_effort=getattr(args, 'think', None),
                                     max_tokens=_lim_clamp(args))
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

    # agent 模式: 多轮工具循环
    if getattr(args, 'agent', False):
        return _do_agent(args, cfg, prompt)

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
    sv = StreamView(live=live, show_reason=show_reason, color=color,
                    sink=sys.stdout, reason_sink=reason_sink)

    res = call_zen_retry(args.model, prompt, args.system, session, sv.on_delta,
                         args.tool_choice, _tool_names(args), cfg,
                         max_attempts=args.retries,
                         verbose=args.stream, on_reason=sv.on_reason,
                         reasoning_effort=getattr(args, 'think', None),
                         max_tokens=getattr(args, 'max_tokens', None))
    # 线路已在 call_zen_retry 内一次定死, 重试只重试同一条线。
    sv.finish()

    # stdout 只出最终结果 (流式内容已随 on_delta 打出), 管道里 json 不会被流污染
    calls = res.get('tool_calls_detail') or []
    if fmt == 'json':
        print(json.dumps(_fmt_payload(res, args), indent=2, ensure_ascii=False))
    elif live:
        if sv.printed:
            print('')              # 流出去过东西就补个换行收尾
        # 工具调用等流读完再打: 名字先到、参数后到, 早点打只有 "(…)" 可写
        print_tool_calls(calls, color=color, sink=sys.stdout)
    else:
        # 缓冲模式: 思考先打 (终端走 stdout, 重定向走 stderr), 回答只走 stdout
        if show_reason and (res.get('reasoning') or '').strip():
            think = res['reasoning'].strip()
            print('[思考] %s%s%s' % (_C_THINK if color else '', think,
                                    _C_RESET if color else ''), file=reason_sink)
            if tty:                       # 终端上给回答也起个头, 两段一眼分得开
                print('[回答] %s' % res.get('text', ''))
                print_tool_calls(calls, color=color, sink=reason_sink)
                return 0 if res.get('ok') else 2
        print(res.get('text', ''))
        print_tool_calls(calls, color=color, sink=reason_sink)
    if not res.get('ok'):
        print('[zen] %s %s' % (res.get('status'),
                               (res.get('error_body') or '')[:300]),
              file=sys.stderr)
        return 2
    return 0

def do_zen(args, cfg):
    if getattr(args, 'no_proxy', False):
        cfg = dict(cfg)
        # 必须写 'direct' 这个字符串 —— 下游 proxyhelper 把 None 解释成 "auto"
        # (跟配置/规则表走), 于是 --no-proxy 会绕一圈又走回代理; 'direct' 才是
        # 强制直连的约定值 (netx / transport / net.http 三处都认)。
        cfg['proxy'] = 'direct'
    return _do_zen(args, cfg)

