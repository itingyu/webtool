"""zen 输出视图: 表格/状态/错误摘要渲染"""
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

from webtool.cli import zenproto as _zp

# socket 空闲超时。urlopen 的 timeout 只管"多久没收到字节", 不是墙钟预算;
# 流式生成中间只要有 delta 就永不触发, 所以给够即可。
from webtool.cli.zen.client import _tool_names
from webtool.cli.zen.client import is_free_model

_C_RESET = '\033[0m'

_C_THINK = '\033[90m'      # 灰: 思考

_C_TOOL = '\033[33m'       # 黄: 工具调用

_C_HEAD = '\033[36m'       # 青: 分段标签

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

