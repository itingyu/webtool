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

# ── 对外再导出: 拆包前这些名字在本模块上, 拆包后调用方不该改 import ──
from webtool.cli.zen.client import call_zen as call_zen
from webtool.cli.zen.client import call_zen_on_route as call_zen_on_route
from webtool.cli.zen.client import call_zen_retry as call_zen_retry
from webtool.cli.zen.client import fetch_models as fetch_models
from webtool.cli.zen.client import fetch_models_detail as fetch_models_detail
from webtool.cli.zen.client import split_think as split_think
from webtool.cli.zen.client import _ThinkSplitter
from webtool.cli.zen.client import _color_on
from webtool.cli.zen.client import _tool_names
from webtool.cli.zen.client import is_free_model
from webtool.cli.zen.render import _C_HEAD
from webtool.cli.zen.render import _C_RESET
from webtool.cli.zen.render import _C_THINK
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

    # 记住的模型输出上限: --limits 读出来, --forget-limits 清掉 (都不联网)
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

    # dry-run: 打印请求, 不联网
    view = _show_view(args)
    if view:
        ses = StickySession() if args.sticky else None
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

    res = call_zen_retry(args.model, prompt, args.system, session, on_delta,
                         args.tool_choice, _tool_names(args), cfg,
                         max_attempts=args.retries,
                         verbose=args.stream, on_reason=on_reason,
                         reasoning_effort=getattr(args, 'think', None),
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

    # stdout 只出最终结果 (流式内容已随 on_delta 打出), 管道里 json 不会被流污染
    calls = res.get('tool_calls_detail') or []
    if fmt == 'json':
        print(json.dumps(_fmt_payload(res, args), indent=2, ensure_ascii=False))
    elif live:
        if marks['reason'] or marks['text']:
            print('')              # 流出去过东西就补个换行收尾
        # 工具调用等流读完再打: 名字先到、参数后到, 早点打只有 "(…)" 可写
        print_tool_calls(calls, color=color, sink=sys.stdout)
    else:
        # 缓冲模式: 思考先打 (终端走 stdout, 重定向走 stderr), 回答只走 stdout
        if show_reason and (res.get('reasoning') or '').strip():
            think = res['reasoning'].strip()
            print('%s %s%s%s' % (_head('[思考]'), _C_THINK if color else '', think,
                                 _C_RESET if color else ''), file=reason_sink)
            if tty:                       # 终端上给回答也起个头, 两段一眼分得开
                print('%s %s' % (_head('[回答]'), res.get('text', '')))
                print_tool_calls(calls, color=color, sink=reason_sink)
                return 0 if res.get('ok') else 2
        print(res.get('text', ''))
        print_tool_calls(calls, color=color, sink=reason_sink)
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
        # 强制直连的约定值 (netx / transport / net.http 三处都认)。
        cfg['proxy'] = 'direct'
    return _do_zen(args, cfg)

