# -*- coding: utf-8 -*-
"""zen 记住"上游报过的模型输出上限" (纯本地, 不联网)

要钉住的行为:
1. 从各家 400 文案里抠出**上限** (不是被拒的那个值); 抠不出就不记 (不许猜)
2. 学到就落盘, 下次运行直接按上限发请求 —— 不必再撞一次墙
3. 能读出来 (`zen limits`), 能忘掉 (`zen limits --forget`)
4. 上游改了口径就覆盖旧值, 死守旧值等于一直撞墙

跑法: python3 tests/test_zen_token_memory.py
"""
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'src'))

# USER_DIR 在 import 时就定下来, 所以必须先设环境变量再 import
TMP = tempfile.mkdtemp(prefix='zen-limits-')
os.environ['WEBTOOL_DIR'] = TMP

from webtool.cli.zen import limits as L                           # noqa: E402
from webtool.cli.zen import client as C                           # noqa: E402

fails = []


def check(cond, msg, detail=''):
    print(('PASS ' if cond else 'FAIL ') + msg + (('  ' + str(detail)) if detail and not cond else ''))
    if not cond:
        fails.append(msg)


# ── 1. 从报文里抠上限 ────────────────────────────────────────────
_parse = [
    ('max_tokens is too large: 200000. This model supports at most 131072 '
     'completion tokens, whereas you provided 200000.', 131072),
    ('max_tokens: 32000 > 16384, which is the maximum allowed number of '
     'output tokens for claude-sonnet-4', 16384),
    ('Invalid request: maxOutputTokens must be <= 65536', 65536),
    ('max_tokens must be less than or equal to 8192', 8192),
    ('the maximum number of tokens allowed is 4096', 4096),
    ('MAX_TOKENS ... AT MOST 32768', 32768),
    # 上下文窗口不是回复上限 —— 记错会拿个不相干的数字当上限
    ('maximum context length is 200000 tokens, you requested 300000', None),
    ('max_tokens too large', None),
    ('rate limited, retry later', None),
    ('', None),
    (None, None),
]
for body, want in _parse:
    check(L.parse_limit(body) == want, '抠上限: %r → %r'
          % (str(body)[:38], want), L.parse_limit(body))

# ── 2. 落盘 / 读取 / 忘记 ────────────────────────────────────────
check(L.load() == {} and L.limit_for('m1') is None, '初始为空')

check(L.remember('m1', 131072)[0] is True, '记住一个上限 → 写盘成功')
check(L.limit_for('m1') == 131072, '读得回来')
check(L.clamp('m1', 200000) == (131072, 131072), '超了记住的上限 → 降档并告知')
check(L.clamp('m1', 4096) == (4096, None), '没超 → 原样, 不动用户给的值')
check(L.clamp('m1', None) == (None, None), '没给值 → 原样')
check(L.clamp('没记住的模型', 200000) == (131072, 131072),
      '没记住的模型 → 按表里最小上限兜底 (宁可少要, 不盲发注定被拒的请求)')

L.remember('m1', 131072)
check(L.load()['m1']['hits'] == 2, '同一个上限再学到 → hits 累加',
      L.load()['m1'].get('hits'))
check(L.clamp('m1', 200000)[0] == 131072, 'hits 变了不影响降档结果')

L.remember('m1', 8192)
check(L.limit_for('m1') == 8192 and L.load()['m1']['hits'] == 1,
      '上限变了 → 覆盖旧值 (上游改口径是常事)', str(L.load()['m1']))

check(L.remember('m2', 0)[1] is False and L.limit_for('m2') is None,
      '0 这种明显不是上限的数字不记')
check(L.remember('m2', 10 ** 9)[1] is False, '大到离谱的数字不记')
check(L.remember('', 8192)[1] is False, '没模型名不记')

check(L.forget('m1') == 1 and L.limit_for('m1') is None, 'zen limits --forget --model 只忘那一个')
L.remember('m1', 4096)
L.remember('m2', 8192)
check(L.forget() == 2 and L.load() == {}, '不点名就全忘')

# 坏文件当空: 这份是加分项, 不该让 zen 整个不可用
with open(os.path.join(TMP, 'zen_limits.json'), 'w') as f:
    f.write('{ this is not json')
check(L.load() == {} and L.clamp('m1', 999) == (999, None), '文件坏了当没记住')
with open(os.path.join(TMP, 'zen_limits.json'), 'w') as f:
    f.write('{"m9": 8192}')                  # 手写简写也认
check(L.limit_for('m9') == 8192, '手写的简写形式 {"模型": 8192} 也认')
os.remove(os.path.join(TMP, 'zen_limits.json'))
# 目录预取的缓存戳: 让 call_zen_retry 跳过联网刷新, 这段才测得到 400 反推
with open(os.path.join(TMP, 'model_catalog.json'), 'w') as f:
    json.dump({'ts': int(time.time())}, f)

# ── 3. 客户端: 撞墙时学到, 下次直接用 ────────────────────────────
CALLS = []
_REAL = C.call_zen


def fake_call(model, prompt, system=None, session=None, on_delta=None,
              tool_choice=None, tool_names=None, proxy=None, on_reason=None,
              reasoning_effort=None, max_tokens=None, messages=None,
              tool_defs=None, allow_tool_calls=False):
    CALLS.append(max_tokens)
    if max_tokens and max_tokens > 131072:
        return {'ok': False, 'status': 400, 'error_body':
                'max_tokens is too large: %d. This model supports at most '
                '131072 completion tokens' % max_tokens}
    return {'ok': True, 'status': 200, 'text': 'hi', 'usage': {}}


C.call_zen = fake_call
try:
    del CALLS[:]
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        res = C.call_zen_retry('big-pickle', 'hi', cfg={}, max_attempts=1,
                               max_tokens=200000)
    check(res.get('ok') is True, '撞上限后按上限重打一次 → 成功', str(res)[:120])
    check(CALLS == [200000, 131072], '第二次请求带的是上游报的上限', str(CALLS))
    check(L.limit_for('big-pickle') == 131072, '上限已经落盘记住')
    check('上限' in err.getvalue() and '131072' in err.getvalue(),
          '说清了"按上限重试" (不静默改数字)', err.getvalue()[:80])

    # 下一次运行: 一开始就按上限走, 不再撞墙
    del CALLS[:]
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        res = C.call_zen_retry('big-pickle', 'hi', cfg={}, max_attempts=1,
                               max_tokens=200000)
    check(CALLS == [131072], '第二次运行: 直接按记住的上限发, 没有白跑那一次',
          str(CALLS))
    check(res.get('ok') is True and '已知上限' in err.getvalue(),
          '并说明了为什么降档', err.getvalue()[:80])

    # 抠不出数字 → 不记、不重试 (不许猜一个值记下来)
    L.forget()
    del CALLS[:]
    C.fake_call = fake_call
    C.call_zen = lambda *a, **k: ({'ok': False, 'status': 400,
                                   'error_body': 'bad request: max_tokens'},
                                  CALLS.append(k.get('max_tokens')))[0]
    with contextlib.redirect_stderr(io.StringIO()):
        res = C.call_zen_retry('m-unknown', 'hi', cfg={}, max_attempts=1,
                               max_tokens=200000)
    check(res.get('status') == 400 and L.load() == {} and CALLS == [200000],
          '抠不出上限: 不重试也不记 (猜一个值比每次撞墙更糟)', str(CALLS))
finally:
    C.call_zen = _REAL
    L.forget()

# ── 4. 命令行能读出来 ────────────────────────────────────────────
L.remember('big-pickle', 131072)
env = dict(os.environ, WEBTOOL_DIR=TMP, WEBTOOL_LLM='on')
r = subprocess.run([sys.executable, os.path.join(ROOT, 'src', 'webtool', '__main__.py'),
                    'zen', 'limits'], capture_output=True, text=True, env=env,
                   timeout=180)
check(r.returncode == 0 and 'big-pickle' in r.stdout and '131072' in r.stdout,
      'webtool zen limits 列出记住的上限', r.stdout[-200:] + r.stderr[-200:])
r2 = subprocess.run([sys.executable, os.path.join(ROOT, 'src', 'webtool', '__main__.py'),
                     'zen', 'limits', '-f', 'json'], capture_output=True,
                    text=True, env=env, timeout=180)
try:
    j = json.loads(r2.stdout)
    okj = j.get('big-pickle', {}).get('max_tokens') == 131072
except ValueError:
    okj = False
check(okj, '-f json 给结构化结果 (给脚本读)', r2.stdout[-200:])
r3 = subprocess.run([sys.executable, os.path.join(ROOT, 'src', 'webtool', '__main__.py'),
                     'zen', 'limits', '--forget'], capture_output=True, text=True,
                    env=env, timeout=180)
check(r3.returncode == 0 and L.load() == {}, 'webtool zen limits --forget 清掉记录',
      r3.stdout[-120:])

shutil.rmtree(TMP, ignore_errors=True)

print()
if fails:
    print('FAILED: %d 项 -> %s' % (len(fails), ', '.join(fails)))
    sys.exit(1)
print('ALL PASS')
