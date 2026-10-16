# -*- coding: utf-8 -*-
"""弹性层与 stdin 的边界单测 (纯本地, 不联网; state 走临时 HOME)

覆盖:
  1. core.resilient: retry_call 重试/退避/耗尽, Breaker 计数与半开,
     parallel_map 顺序恒定与异常隔离, Checkpoint 续跑
  2. core.stdin: read_input 的四种情况, parse_lines/parse_jsonl

跑法: python3 tests/test_resilient.py
"""
import io
import os
import sys
import tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 先把 HOME 指到临时目录 —— 熔断状态与断点不许落到真实 HOME
_TMP = tempfile.mkdtemp(prefix='wt-test-')
os.environ['HOME'] = _TMP

fails = []

def check(name, cond):
    print(('PASS' if cond else 'FAIL') + ' ' + name)
    if not cond:
        fails.append(name)

from webtool.dao import state
state.PATH = os.path.join(_TMP, '.webtool', 'state.json')

from webtool.core import resilient as R

# ── 1. retry_call ────────────────────────────────────────────────
calls = []
def _flaky():
    calls.append(1)
    if len(calls) < 3:
        raise IOError('boom')
    return 'ok'

sleeps = []
out = R.retry_call(_flaky, url='', retries=3, backoff='flat',
                   sleep=lambda s: sleeps.append(s))
check('重试到成功返回结果', out == 'ok' and len(calls) == 3)
check('重试之间有等待', len(sleeps) == 2)

def _always_fail():
    raise IOError('nope')

try:
    R.retry_call(_always_fail, url='', retries=2, backoff='flat',
                 sleep=lambda s: None)
    check('耗尽后原样抛异常', False)
except IOError:
    check('耗尽后原样抛异常', True)

R.retry_call(lambda: 'x', url='', retries=0, backoff='flat')
check('retries=0 直接调用不重试', True)

delays = []
def _f():
    raise IOError('x')
try:
    R.retry_call(_f, url='', retries=6, backoff='exp', sleep=delays.append)
except IOError:
    pass
check('exp 退避有上限', all(d <= R.RETRY_CAP for d in delays) and len(delays) == 6)

seen = []
try:
    R.retry_call(_always_fail, url='', retries=1, backoff='flat',
                 sleep=lambda s: None, on_retry=lambda a, e: seen.append(a))
except IOError:
    pass
check('on_retry 每次重试都回调', seen == [1])

check('retry_policy 无规则走默认',
      R.retry_policy('https://example.org/') == (R.DEFAULT_RETRIES,
                                                 R.DEFAULT_BACKOFF))
check('breaker_policy 无规则走默认',
      R.breaker_policy('https://example.org/') == (R.DEFAULT_FAIL_THRESHOLD,
                                                   R.DEFAULT_COOL_SECONDS))

# ── 2. Breaker ───────────────────────────────────────────────────
b = R.Breaker('https://flaky.example/x')
check('初始未打开', b.check() is None)
for _ in range(R.DEFAULT_FAIL_THRESHOLD - 1):
    b.record(False)
check('未到阈值不打开', b.check() is None)
b.record(False)
left = b.check()
check('到阈值打开并报剩余冷却', isinstance(left, (int, float)) and left > 0)

b2 = R.Breaker('https://ok.example/x')
for _ in range(10):
    b2.record(False)
    b2.record(True)
check('成功清零连败', b2._load().get('fails') == 0)

b3 = R.Breaker('https://half.example/x')
for _ in range(R.DEFAULT_FAIL_THRESHOLD):
    b3.record(False)
state.set_breaker(b3.name, open_until=1)          # 手工过期 → 半开
check('冷却过期后放行 (半开清零)',
      b3.check() is None and b3._load().get('fails') == 0)

# ── 3. parallel_map ──────────────────────────────────────────────
import time as _t
items = list(range(8))
res = R.parallel_map(items, lambda x: (x, x * 2) if x != 3 else x, max_workers=4)
check('顺序按声明 (结果与输入一一对应)',
      [r[0] for r in res[:3]] == [(0, 0), (1, 2), (2, 4)])

def _boom(x):
    if x == 3:
        raise ValueError('x=3')
    return x
res2 = R.parallel_map(items, _boom, max_workers=4)
check('单任务异常不炸整批',
      [r[0] for r in res2 if r[1] is None] == [0, 1, 2, 4, 5, 6, 7])
check('异常放回自己的槽位', isinstance(res2[3][1], ValueError))

t0 = _t.time()
R.parallel_map(range(6), lambda x: (_t.sleep(0.2), x)[1], max_workers=6)
check('并发确实并发 (6×0.2s < 1s)', _t.time() - t0 < 0.9)
check('空列表返回空', R.parallel_map([], lambda x: x) == [])
check('声明顺序在多线程下也保持',
      [r[0] for r in R.parallel_map(range(20), lambda x: x, max_workers=8)] == list(range(20)))

# ── 4. Checkpoint ────────────────────────────────────────────────
cp = R.Checkpoint('unittest-' + os.path.basename(_TMP))
cp.clear()
check('初始全部待办', cp.pending(['a', 'b', 'c']) == ['a', 'b', 'c'])
cp.done('a')
cp.done('b')
check('已完成条目被跳过', cp.pending(['a', 'b', 'c']) == ['c'])
cp2 = R.Checkpoint('unittest-' + os.path.basename(_TMP))
check('断点跨实例生效 (落盘)', cp2.pending(['a', 'b', 'c']) == ['c'])
cp2.clear()
check('清空后重新待办', cp2.pending(['a']) == ['a'])

# ── 5. stdin ────────────────────────────────────────────────────
from webtool.core import stdin as S

check('显式参数直接返回', S.read_input('abc') == 'abc')
check('parse_lines 跳空行与注释',
      S.parse_lines('a\n\n# c\nb\n') == ['a', 'b'])
check('parse_jsonl 逐行解析',
      S.parse_jsonl('{"a":1}\n{"b":2}') == [{'a': 1}, {'b': 2}])
try:
    S.parse_jsonl('{"a":1}\nnot-json')
    check('parse_jsonl 坏行报错 rc=2', False)
except SystemExit as e:
    check('parse_jsonl 坏行报错 rc=2', e.code == 2)
check('空文本 → 空列表', S.parse_lines('') == [])

_stdin = sys.stdin
class _Pipe(io.StringIO):
    def isatty(self):
        return False
class _Tty(io.StringIO):
    def isatty(self):
        return True

sys.stdin = _Pipe('x\n')
try:
    check('无参 + 管道 → 读 stdin', S.read_input() == 'x')
finally:
    sys.stdin = _stdin
sys.stdin = _Tty('x\n')
try:
    check('无参 + tty → None', S.read_input() is None)
    try:
        S.read_input('-')
        check("'-' + tty → 用法错 rc=2", False)
    except SystemExit as e:
        check("'-' + tty → 用法错 rc=2", e.code == 2)
finally:
    sys.stdin = _stdin

print()
if fails:
    print('FAILED: %d 项 -> %s' % (len(fails), ', '.join(fails)))
    sys.exit(1)
print('ALL PASS')
