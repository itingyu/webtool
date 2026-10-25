"""zen --agent: 工作空间边界 / 会话存取 / 多轮循环 (纯本地, 不联网)

跑法: python3 tests/test_zen_agent.py

WEBTOOL_DIR 在 import webtool 之前就指到临时目录 —— 会话落盘不许碰真实 HOME
(见 coding-standard「测试不许碰真实 HOME」)。
"""
import io
import os
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_TD = tempfile.mkdtemp(prefix='zen-agent-')
os.environ['WEBTOOL_DIR'] = _TD

fails = []


def check(cond, msg, detail=''):
    print(('PASS ' if cond else 'FAIL ') + msg + ((' [%s]' % detail) if detail and not cond else ''))
    if not cond:
        fails.append(msg)


from webtool.cli.zen import agent as A                    # noqa: E402
from webtool.cli.zen import session as S                 # noqa: E402
from webtool.cli.zen.workspace import Workspace          # noqa: E402
from webtool.core.errors import UsageError               # noqa: E402

# ── 造工作空间: 里面两个文件, 外面一个 secret, 再加一条 symlink 绕出去 ──
_ws = Path(_TD, 'ws')
_ws.mkdir()
(_ws / 'a.py').write_text('def greet():\n    return "hi"\n', encoding='utf-8')
(_ws / 'b.txt').write_text('hello world\n', encoding='utf-8')
_out = Path(_TD, 'outside')
_out.mkdir()
(_out / 'secret.txt').write_text('SECRET', encoding='utf-8')
os.symlink(_out, _ws / 'link')

ws = Workspace(_ws)
ctx = {'workspace': ws, 'cfg': {}, 'max_chars': 500, 'tool_names': []}
sink = io.StringIO()


def run(name, args):
    """跑一个工具, 只取回喂给模型的那段文本"""
    return A.run_tool({'name': name, 'args': args}, ctx)[0]


print('\n=== 1. 工作空间是条边界 ===')
check('hi' in run('read', {'filePath': 'a.py'}), 'read 读得到工作空间里的文件')
check(run('glob', {'pattern': '*.py'}).strip() == 'a.py',
      'glob 只列工作空间里的文件', run('glob', {'pattern': '*.py'}))
check('hello world' in run('grep', {'pattern': 'hello'}), 'grep 搜得到内容')
check('SECRET' not in run('read', {'filePath': '../outside/secret.txt'}),
      '相对路径绕不出去')
check('SECRET' not in run('read', {'filePath': str(_out / 'secret.txt')}),
      '绝对路径在工作空间外挡得住')
check('SECRET' not in run('read', {'filePath': 'link/secret.txt'}),
      'symlink 绕不出去 (resolve 之后才比边界)')
check('工作空间外' in run('grep', {'pattern': 'x', 'path': '/etc'}),
      'grep 的 path 也要过边界')
try:
    ws.check('/etc/passwd')
    check(False, 'check() 越界应当抛 UsageError')
except UsageError:
    check(True, 'check() 越界抛 UsageError (退出 2)')
try:
    Workspace.resolve(str(_out / 'nope'))
    check(False, '不存在的工作空间应当报错')
except UsageError:
    check(True, '不存在的工作空间报错, 不静默退回 cwd')

print('\n=== 2. 会话存取 ===')
check(S.load('nope') is None, '不存在的会话读成 None (当作新建, 不是错)')
rejected = 0
for bad in ('../x', 'a/b', '', '.hid'):
    try:
        S.path_of(bad)
    except UsageError:
        rejected += 1
check(rejected == 4, '会话名只认字母数字 . _ - (路径分隔符/空/点开头都拒)', str(rejected))
msgs = [{'role': 'user', 'content': 'q'}, {'role': 'assistant', 'content': 'a'}]
check(S.save('t', msgs, model='m', workspace=ws), '会话能存')
got = S.load('t')
check(got and got['messages'] == msgs, '存进去的消息原样读回')
check(got and got['model'] == 'm' and got['workspace'] == str(ws.root),
      '模型与工作空间一并存下')
check(S._dir().is_relative_to(Path(_TD)), '会话落在 WEBTOOL_DIR, 不碰真实 HOME')
S.save('t', msgs + [{'role': 'assistant', 'content': 'a2'}], workspace=ws)
check(S.load('t')['steps'] == 2, '轮数由 assistant 条数算出, 不是另设的一个数')
S.save('u', msgs[:1], workspace=ws)
check(S.latest() == 'u', '--continue 取最近动过的那条')
check({r['name'] for r in S.recent()} >= {'t', 'u'}, '--sessions 列得全')
(S._dir() / 'broken.json').write_text('{不是 json', encoding='utf-8')
check(S.load('broken') is None, '坏会话文件当新建, 不抛异常')
check(S.remove('t') == 1 and S.remove('t') == 0, '删会话: 第一次 1 条, 第二次 0 条')

print('\n=== 3. 多轮循环 ===')
SCRIPT = [
    {'ok': True, 'status': 200, 'text': '找文件', 'tool_calls_detail': [
        {'id': 'c1', 'name': 'glob', 'args': {'pattern': '*.py'}}]},
    {'ok': True, 'status': 200, 'text': '读它', 'tool_calls_detail': [
        {'id': 'c2', 'name': 'read', 'args': {'filePath': 'a.py'}}]},
    {'ok': True, 'status': 200, 'text': 'greet 返回 hi', 'tool_calls_detail': []},
]
state = {'n': 0}


def turn(_msgs):
    r = dict(SCRIPT[min(state['n'], len(SCRIPT) - 1)])
    state['n'] += 1
    return r


with redirect_stdout(sink):
    res, steps, final = A.agent_loop(
        turn, A.initial_messages('s', 'q'),
        lambda calls, step: A.exec_calls(calls, ctx, sink=sink), max_steps=20)
check(res['text'] == 'greet 返回 hi', '模型不再要工具时那一轮就是答案')
check(steps == 3, '轮数 = 实际跑的模型请求数', str(steps))
check([m['role'] for m in final] ==
      ['system', 'user', 'assistant', 'tool', 'assistant', 'tool'],
      '消息序列 system/user/assistant+tool_calls/tool', str([m['role'] for m in final]))
check([t['function']['name'] for t in final[2]['tool_calls']] == ['glob']
      and final[3]['tool_call_id'] == 'c1',
      'tool_calls 与 role:tool 靠 tool_call_id 对得上')
check(final[3]['content'].strip() == 'a.py', '工具结果回喂给模型')
state['n'] = 0
with redirect_stdout(sink):
    res2, s2, _ = A.agent_loop(
        turn, A.initial_messages('s', 'q'),
        lambda calls, step: A.exec_calls(calls, ctx, sink=sink), max_steps=2)
check(res2.get('stopped_by_limit') is True and s2 == 2,
      '到 --agent-max-steps 如实标 stopped_by_limit, 不假装答完了')
seen = []
with redirect_stdout(sink):
    A.agent_loop(lambda _m: {'ok': False, 'status': 500, 'error_body': 'boom'},
                 A.initial_messages('s', 'q'),
                 lambda calls, step: A.exec_calls(calls, ctx, sink=sink),
                 after_step=lambda m, step: seen.append(len(m)))
check(not seen, '失败的一轮不触发存盘钩子')

print('\n=== 4. 没实现的工具如实回执 ===')
check('没有实现' in run('bash', {'command': 'rm -rf /'}),
      'bash 收到"不可用"回执 (静默忽略会让模型以为工具已执行)')
check('未知工具' in run('nosuch', {}), '未知工具名也回执, 不崩')

print('\n=== 5. 工具清单仍满足免费层闸门 ===')
specs = [t['function']['name'] for t in A.tool_specs(A.resolve_names(None))]
check('bash' in specs and 'read' in specs,
      'bash+read 仍在清单里 (缺任一就是 403 FreeTierError)', str(specs))
check('websearch' in specs and 'webfetch' in specs, 'agent 工具也在清单里')
check(A.resolve_names('read,glob') == ['read', 'glob'], '--agent-tools 认逗号清单')
try:
    A.resolve_names('bash')
    check(False, '把没实现的工具写进 --agent-tools 应当报错')
except UsageError:
    check(True, '把没实现的工具写进 --agent-tools 报错 (退出 2)')

print('\n=== 6. 会话恢复不重复 system ===')
hist = [{'role': 'system', 'content': '旧的'}, {'role': 'user', 'content': '上轮'},
        {'role': 'assistant', 'content': '答'}]
back = A.resume_messages(hist, '新的', '这轮')
check([m['content'] for m in back] == ['新的', '上轮', '答', '这轮'],
      '恢复时 system 只留最新的一条 (旧的那份已过时)', str([m['content'] for m in back]))

if fails:
    print('\n%d FAIL' % len(fails))
    sys.exit(1)
print('\nALL PASS')