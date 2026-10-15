"""
"""

import json
import sys

from webtool.cli import zenproto as _zp
from webtool.cli.zenproto import StickySession
from webtool.cli.zen.render import _C_HEAD
from webtool.cli.zen.render import _C_RESET
from webtool.cli.zen.render import _C_THINK
from webtool.cli.zen.render import _C_TOOL
from webtool.cli.zen.client import _ThinkSplitter
from webtool.cli.zen.client import _color_on
from webtool.cli.zen.render import _fmt_payload
from webtool.cli.zen.render import _print_check
from webtool.cli.zen.render import _print_models
from webtool.cli.zen.render import _show_view
from webtool.cli.zen.client import _tool_names
from webtool.cli.zen.render import _tool_warn
from webtool.cli.zen.client import call_zen_retry
from webtool.cli.zen.client import fetch_models_detail
from webtool.cli.zen.client import is_free_model

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

