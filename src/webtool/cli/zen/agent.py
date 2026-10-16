"""zen --agent: 多轮工具循环 (模型调工具 → 本地执行 → 结果回喂 → 再问)

单发对话 (不带 --agent) 到模型要工具就收工 (`client.call_zen` 报 "no tool
loop"); 这里补上那个循环: 一轮跑到模型不再要工具为止, 中间它要什么就执行什么,
执行结果按 OpenAI 的 role:tool 消息塞回 messages, 让它看着结果继续。

**执行的只有只读 + web 一类**: read / glob / grep / websearch / webfetch。
文件类受工作空间边界约束 (`zen/workspace.py`), web 类复用本仓自己的 search /
fetch 管线。bash / write / edit 这些既没有实现也不打算在这里实现 —— 收到这类
调用时回一句"不可用"当工具结果, 模型看得见就不会一直打转 (静默忽略会让它以为
工具已执行, 然后开始编造结果)。

会话历史由 `zen/session.py` 落盘, 每轮存一次。
"""

import io
import json
import re
import sys
import time
from contextlib import redirect_stdout

from webtool.cli import zenproto as _zp
from webtool.core.logging import get_logger

logger = get_logger(__name__)

MAX_STEPS = 20               # 多轮上限 (步 = 一次模型请求)
MAX_OUT_CHARS = 8000         # 单次工具输出回喂上限
READ_LINES = 2000            # read 一次最多给多少行
GREP_MAX_FILES = 400         # grep 扫多少文件就收手 (够用且不会把整棵树读进内存)
GREP_MAX_HITS = 60
GREP_MAX_LINE = 300
GLOB_MAX = 200
SKIP_DIRS = {'.git', '__pycache__', 'node_modules', '.venv', 'venv',
             '.mypy_cache', '.pytest_cache', '.tox', 'dist', 'build'}

AGENT_TOOLS = ('read', 'glob', 'grep', 'websearch', 'webfetch')

# 没实现的工具 → 回给模型的话。写清"没有"而不是不回: 模型得知道这条路走不通。
UNAVAILABLE = {
    'bash': 'bash 没有实现 (webtool zen --agent 只执行只读与 web 类工具)。'
            '改用 websearch/webfetch 拿外部信息, 或用 read/glob/grep 看工作空间。',
    'edit': 'edit 没有实现 (--agent 不写文件)。',
    'write': 'write 没有实现 (--agent 不写文件)。',
    'question': 'question 没有实现, 无法向用户提问; 按你已有的信息继续。',
    'task': 'task 没有实现 (不支持子 agent)。',
    'skill': 'skill 没有实现。',
    'todowrite': 'todowrite 没有实现; 直接继续干活。',
}


def tool_specs(names):
    """要下发的工具定义 (data/zen_tools.json 的真机 schema, 原样)

    闸门要求 bash+read 同时在 (`zenproto` 文件头), 所以即使这两个没实现也照发 ——
    少了就是 403。多轮循环要的是"模型看得见名字才会调", 而调了会被如实告知
    不可用, 比悄悄不发更省一轮往返。
    """
    all_defs = _zp.tools('all')
    want = list(dict.fromkeys(list(_zp.DEFAULT_TOOL_NAMES) + list(names)))
    return [t for t in all_defs if t['function']['name'] in want]


def agent_system(base, names, workspace):
    """system prompt: 声明这是个工具循环, 并说清哪些工具真的能用

    闸门只验 role:system 存在、不读内容, 所以在这里追加说明不影响放行。
    不说明的话, 模型面对一个含 bash 的工具表会去试 bash, 白花一轮。
    """
    lines = [base or _zp.DEFAULT_SYSTEM, '',
             '[运行方式] 你在一个自动工具循环里: 需要外部信息或看文件时调工具, '
             '工具结果会自动回给你, 然后你据结果继续, 直到能给用户一个完整答案。',
             '',
             '[可用工具] %s' % ' / '.join(names),
             'bash / edit / write 等工具在清单里但**没有实现**, 调用它们只会拿到'
             '"不可用"的回执 —— 别在上面打转。',
             '',
             '[边界] 文件类工具 (read/glob/grep) 只能碰 %s 里面的路径。'
             % workspace.root]
    agents_md = workspace.agents_md()
    if agents_md:
        lines += ['', '[工作空间说明 AGENTS.md]', agents_md]
    return '\n'.join(lines)


# ── 文件类工具 (工作空间内) ──────────────────────────────────────────

def _walk_files(root, limit):
    """工作空间内可搜的文件, 跳过版本库/缓存/虚拟env 目录"""
    out = []
    for p in sorted(root.rglob('*')):
        if len(out) >= limit:
            break
        if not p.is_file() or p.is_symlink():
            continue
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        out.append(p)
    return out


def _rel(workspace, path):
    try:
        return str(path.relative_to(workspace.root))
    except ValueError:
        return str(path)


def t_read(args, ctx):
    """read(filePath, offset, limit) → 文件内容 (按行截)"""
    ws = ctx['workspace']
    src = args.get('filePath') or args.get('path') or ''
    if not src:
        return 'read 需要 filePath 参数'
    p = ws.inside(src)
    if p is None:
        return '路径在工作空间外: %s (只能读 %s 里的文件)' % (src, ws.root)
    if not p.is_file():
        return '文件不存在: %s' % _rel(ws, p)
    text = p.read_text(encoding='utf-8', errors='replace')
    offset = _as_int(args.get('offset'), 1)
    limit = _as_int(args.get('limit'), READ_LINES)
    lines = text.splitlines()
    body = lines[max(0, offset - 1):max(0, offset - 1) + max(1, limit)]
    head = '%s (第 %d-%d 行 / 共 %d 行)' % (_rel(ws, p), offset,
                                           offset + len(body) - 1, len(lines))
    return head + '\n' + '\n'.join(body)


def t_glob(args, ctx):
    """glob(pattern, path) → 匹配到的文件 (相对工作空间)"""
    ws = ctx['workspace']
    pat = (args.get('pattern') or '').strip()
    if not pat:
        return 'glob 需要 pattern 参数'
    base = ws.inside(args.get('path') or '.') or ws.root
    if args.get('path') and ws.inside(args.get('path')) is None:
        return '路径在工作空间外: %s' % args.get('path')
    try:
        hits = [p for p in base.glob(pat) if p.is_file()]
    except (ValueError, OSError) as e:
        return 'glob 失败 (%s): %s' % (type(e).__name__, e)
    hits.sort()
    more = len(hits) > GLOB_MAX
    rows = [_rel(ws, p) for p in hits[:GLOB_MAX]]
    if not rows:
        return '没有匹配: %s' % pat
    return '\n'.join(rows) + ('\n… 还有 %d 个没列' % (len(hits) - GLOB_MAX) if more else '')


def t_grep(args, ctx):
    """grep(pattern, path, include) → 命中行 (正则)"""
    ws = ctx['workspace']
    pat = args.get('pattern') or ''
    if not pat:
        return 'grep 需要 pattern 参数'
    try:
        rx = re.compile(pat)
    except re.error as e:
        return '正则不合法 %r: %s' % (pat, e)
    spec = args.get('path') or '.'
    base = ws.inside(spec)
    if base is None:
        return '路径在工作空间外: %s' % spec
    root = base if base.is_dir() else base.parent
    inc = args.get('include') or ''
    files = ([base] if base.is_file()
             else _walk_files(root, GREP_MAX_FILES))
    hits, truncated = [], False
    for f in files:
        if inc and inc not in f.name:
            continue
        try:
            content = f.read_text(encoding='utf-8', errors='replace')
        except OSError:
            continue
        for i, line in enumerate(content.splitlines(), 1):
            if not rx.search(line):
                continue
            if len(hits) >= GREP_MAX_HITS:
                truncated = True
                break
            hits.append('%s:%d: %s' % (_rel(ws, f), i, line.strip()[:GREP_MAX_LINE]))
        if truncated:
            break
    if not hits:
        return '没有命中: %s' % pat
    return '\n'.join(hits) + ('\n… 命中过多, 已截断' if truncated else '')


# ── web 类工具 (复用本仓管线, 不另写一份抓取逻辑) ────────────────────

def _run_cli(argv):
    """进程内跑一条 webtool 命令 → (rc, stdout)

    走 `cli.app.main(argv)` 而不是直接调 `pipeline.search.do_search`: 后者要
    29 个字段的 args 对象, 自己拼等于在本仓里复制一份 CLI 契约, 迟早漂 (与
    `stock/bridge` 调 web_search 同一个理由)。

    两处全局状态必须复原, 否则第一次工具调用就把外层弄坏:
      `_CTX` —— app 回调每次都 `_CTX.clear()`, 复原前外层已经取到的 args 不受影响,
        但之后的读 (如 args.format) 会读到空;
      日志级别 —— 回调按本层 argv 的 debug 次数重新 setup(0), 会把外层 `-d` 抹掉。
    """
    from webtool.cli import app as _app
    from webtool.cli._ctx import _CTX
    from webtool.core import logging as _log
    saved_ctx = dict(_CTX)
    saved_dbg = _log.debug_level()
    buf = io.StringIO()
    try:
        with redirect_stdout(buf):
            rc = _app.main(argv)
    finally:
        _CTX.clear()
        _CTX.update(saved_ctx)
        _log.setup(saved_dbg)
    return rc, buf.getvalue()


def _cli_json(argv):
    """跑一条 webtool 命令取 json 结果 → (ok, 值或原始文本)"""
    rc, out = _run_cli(argv)
    try:
        return True, json.loads(out)
    except ValueError:
        return False, (out.strip() or '(webtool %s 无输出, rc=%s)'
                       % (' '.join(argv[:1]), rc))


def t_websearch(args, ctx):
    """websearch(query, numResults) → webtool search 的结果"""
    query = (args.get('query') or '').strip()
    if not query:
        return 'websearch 需要 query 参数'
    n = max(1, min(20, _as_int(args.get('numResults'), 5)))
    ok, data = _cli_json(['search', query, '-n', str(n), '-f', 'json'])
    if not ok or not isinstance(data, dict):
        return 'search 无结果: %s' % str(data)[:500]
    rows = data.get('results') or []
    if not rows:
        return 'search 没有命中'
    return '\n'.join('%d. %s\n   %s\n   %s'
                     % (i, r.get('title') or '', r.get('url') or '',
                        (r.get('snippet') or '').replace('\n', ' ')[:200])
                     for i, r in enumerate(rows, 1))


def _fm_fields(block):
    """YAML 元数据头里的 `key: value` 扁平字段 (只取单行标量, 不引 yaml 依赖)"""
    out = {}
    for line in (block or '').splitlines():
        if ':' not in line or line.startswith((' ', '\t', '-')):
            continue
        k, _, v = line.partition(':')
        v = v.strip().strip('"\'')
        if v:
            out[k.strip().lower()] = v
    return out


def t_webfetch(args, ctx):
    """webfetch(url, format, timeout) → webtool fetch 的正文/metadata

    fetch 的 json 把 title/author/date 放在 content 的 YAML 元数据头里 (不是独立
    字段), 所以这里把头**读出来当一行摘要**, 再从正文里切掉 —— 整块留在正文里
    的话, 模型会把 `--- title: ... ---` 当成文章内容的一部分。
    """
    url = (args.get('url') or '').strip()
    if not url:
        return 'webfetch 需要 url 参数'
    argv = ['fetch', url, '-f', 'json', '--max-chars', str(ctx['max_chars'])]
    ok, data = _cli_json(argv)
    if not ok or not isinstance(data, dict):
        return 'fetch 失败: %s' % str(data)[:500]
    if data.get('error'):
        return 'fetch 失败: %s' % (data.get('hint') or data['error'])
    content = data.get('content') or ''
    fm = content[:content.find('\n---') + 4] if content.startswith('---') else ''
    meta = _fm_fields(fm.split('\n', 1)[1] if fm else '')
    head = ' | '.join(v for k, v in (('title', meta.get('title') or url),
                                     ('author', meta.get('author')),
                                     ('date', meta.get('date'))) if v)
    from webtool.core.text import strip_front_matter
    return (head + '\n' + strip_front_matter(content)).strip()


TOOLS = {'read': t_read, 'glob': t_glob, 'grep': t_grep,
         'websearch': t_websearch, 'webfetch': t_webfetch}


def _as_int(v, default):
    try:
        n = int(v)
    except (TypeError, ValueError):
        return default
    return n if n > 0 else default


def resolve_names(spec):
    """`--agent-tools` → 工具名清单 (过滤掉没实现的, 挡住闸门那两个)"""
    from webtool.core.errors import UsageError
    s = (spec or '').strip().lower()
    if not s or s in ('min', 'default'):
        return list(AGENT_TOOLS)
    if s == 'all':
        return list(AGENT_TOOLS)
    names = [n for n in s.replace(' ', ',').split(',') if n]
    bad = [n for n in names if n not in AGENT_TOOLS]
    if bad:
        raise UsageError('没有实现的工具: %s (可执行: %s)'
                         % ('/'.join(bad), '/'.join(AGENT_TOOLS)))
    return names


def run_tool(call, ctx):
    """执行一条工具调用 → (回喂给模型的文本, 给界面看的摘要)"""
    name = call.get('name') or '?'
    args = call.get('args') if isinstance(call.get('args'), dict) else {}
    t0 = time.time()
    if name in UNAVAILABLE:
        out = UNAVAILABLE[name]
    elif name in TOOLS:
        try:
            out = TOOLS[name](args, ctx)
        except Exception as e:                # 工具炸了不能让整轮对话崩
            out = '%s 执行失败 (%s): %s' % (name, type(e).__name__, str(e)[:200])
            logger.debug('agent | 工具 %s 抛异常', name, exc_info=True)
    else:
        out = '未知工具 %s' % name
    out = out if isinstance(out, str) else str(out)
    limit = ctx['max_chars']
    fed = out if len(out) <= limit else \
        out[:limit] + '\n… (输出过长, 已截断; 原文 %d 字)' % len(out)
    took = time.time() - t0
    logger.debug('agent | 工具 %s 用时 %.1fs 输出 %d 字 -> 回喂 %d 字',
                 name, took, len(out), len(fed))
    return fed, '%s (%.1fs, %d 字)' % (_one_line(out) or '(空)', took, len(out))


def _one_line(text, limit=120):
    s = ' '.join((text or '').split())
    return s[:limit] + ('…' if len(s) > limit else '')


def exec_calls(calls, ctx, sink=None):
    """一轮里的多条工具调用 → (assistant 的 tool_calls 载荷, role:tool 消息列表)

    每条执行完就打印一行结果摘要 (不是跑完才打): 终端里这是唯一的进度信号,
    一次工具几秒到几十秒, 没提示就像卡死了。摘要进 stdout, 完整回喂给模型。
    """
    out = sink or sys.stdout
    payload, msgs = [], []
    for c in calls:
        cid = c.get('id') or ('call_%d' % (len(payload) + 1))
        fed, brief = run_tool(c, ctx)
        payload.append({'id': cid, 'type': 'function',
                        'function': {'name': c.get('name') or '?',
                                     'arguments': json.dumps(c.get('args') or {},
                                                             ensure_ascii=False)}})
        msgs.append({'role': 'tool', 'tool_call_id': cid,
                     'name': c.get('name') or '?', 'content': fed})
        print('[结果] %s' % brief, file=out)
    return payload, msgs


def initial_messages(system, prompt):
    """system + user (闸门要求 messages[0]=system / 末条=user)"""
    return [{'role': 'system', 'content': system},
            {'role': 'user', 'content': prompt}]


def resume_messages(history, system, prompt):
    """接旧会话: 旧的整段历史 + 这一轮的新问题

    system 只放**第一条**: 历史里已经有一份, 再插一条等于让模型看到两次互相
    重复的指令 (而第二份已经过时 —— 工作空间/工具集可能变了)。所以拿最新的覆盖,
    旧的那条删掉。
    """
    msgs = [m for m in (history or []) if isinstance(m, dict)
            and m.get('role') != 'system']
    return ([{'role': 'system', 'content': system}] + msgs
            + [{'role': 'user', 'content': prompt}])


def agent_loop(call_turn, messages, on_tools, max_steps=MAX_STEPS,
               after_step=None):
    """多轮循环本体 → (最终一轮的 res, 走过的轮数, 循环内的 messages)

    `call_turn(messages)` 发一轮并返回 res (client.call_zen_retry); 模型不再要
    工具时那一轮就是最终答案, 直接返回。达到 max_steps 则把最后一轮原样交出去
    并标 `stopped_by_limit` —— 如实说"到上限了", 不假装答完了。

    `on_tools(calls, step)` 执行工具并回 (tool_calls 载荷, role:tool 消息);
    `after_step(messages, step)` 在这一轮**追加进 messages 之后**触发, 会话
    存盘挂在这里 —— 存盘必须看到完整的这一轮 (assistant + tool), 少一段就等于
    给模型喂了一段没有工具结果的对话。
    """
    steps = 0
    res = None
    while steps < max_steps:
        steps += 1
        res = call_turn(messages)
        if not res.get('ok'):
            break
        calls = res.get('tool_calls_detail') or []
        if not calls:
            break
        payload, tool_msgs = on_tools(calls, steps)
        messages.append({'role': 'assistant',
                         'content': res.get('text') or '',
                         'tool_calls': payload})
        messages.extend(tool_msgs)
        if after_step:
            after_step(messages, steps)
        logger.debug('agent | 第 %d 轮要了 %d 个工具, 已执行回喂',
                     steps, len(calls))
    res['steps'] = steps
    if steps >= max_steps and (res.get('tool_calls_detail') or []):
        res['stopped_by_limit'] = True
    return res, steps, messages