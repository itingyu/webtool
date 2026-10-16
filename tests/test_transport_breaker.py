# -*- coding: utf-8 -*-
"""取页通道 (transport.get) 的熔断接线单测 —— 纯本地, 不联网

验证的是"接线对不对", 不是 http 库:
  1. 连续失败到阈值 → 熔断打开, 后续请求被短路且**不发请求**
  2. 短路时不能再调 _get_ladder (证明是真短路, 不是多发一次再报错)
  3. TlsError 不计入熔断 (证书错是配置问题, 连坐会把整站拉黑)
  4. 成功清零连败
  5. 熔断按域名隔离 (一个站挂了不影响另一个站)

跑法: python3 tests/test_transport_breaker.py
"""
import os
import sys
import tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_TMP = tempfile.mkdtemp(prefix='wt-brk-')
os.environ['HOME'] = _TMP

fails = []

def check(name, cond, detail=''):
    print(('PASS' if cond else 'FAIL') + ' ' + name + (' ' + detail if detail and not cond else ''))
    if not cond:
        fails.append(name)

from webtool.dao import state
state.PATH = os.path.join(_TMP, '.webtool', 'state.json')

from webtool.core.resilient import Breaker as _Breaker
from webtool.net import transport as T

# ── 打桩: _get_ladder 的行为完全由测试控制 ─────────────────────────
calls = []
mode = {'kind': 'raise', 'exc': RuntimeError('上游挂了')}

def fake_ladder(url, **kw):
    calls.append(url)
    m = mode['kind']
    if m == 'raise':
        raise mode['exc']
    return ('body', 200, 'cffi')

T._get_ladder = fake_ladder

def fresh(url):
    """清掉该域名的熔断状态, 让每段测试互不干扰"""
    b = _Breaker(url)
    state.set_breaker(b.name, fails=0, open_until=0)
    return b

URL = 'https://brk.example/a'

from webtool.core.resilient import DEFAULT_FAIL_THRESHOLD, Breaker

# ── 1/2. 失败累计 → 打开 → 短路 (不再发请求) ─────────────────────
fresh(URL)
n0 = len(calls)
for _ in range(DEFAULT_FAIL_THRESHOLD):
    try:
        T.get(URL)
    except RuntimeError:
        pass
    except T.BreakerOpenError as e:
        check('阈值前不该已打开', False)
check('阈值前每次都真发了请求', len(calls) - n0 == DEFAULT_FAIL_THRESHOLD,
      '实发 %d' % (len(calls) - n0))

before = len(calls)
try:
    T.get(URL)
    check('熔断打开后抛 BreakerOpenError', False)
except T.BreakerOpenError as e:
    check('熔断打开后抛 BreakerOpenError', '熔断打开中' in str(e))
check('短路: 请求根本没发出去', len(calls) == before)

# ── 3. TlsError 不连坐 ──────────────────────────────────────────
TLSURL = 'https://tls.example/x'
fresh(TLSURL)
mode['kind'] = 'raise'
mode['exc'] = T.TlsError('证书不对')
for _ in range(DEFAULT_FAIL_THRESHOLD + 2):
    try:
        T.get(TLSURL)
    except T.TlsError:
        pass
    except T.BreakerOpenError:
        check('TlsError 不该触发熔断', False)
check('TlsError 不累计失败',
      int(Breaker(TLSURL)._load().get('fails', 0)) == 0)

# ── 4. 成功清零 ─────────────────────────────────────────────────
OKURL = 'https://ok2.example/y'
fresh(OKURL)
mode['kind'] = 'raise'
mode['exc'] = RuntimeError('一时抽风')
for _ in range(3):
    try:
        T.get(OKURL)
    except RuntimeError:
        pass
check('失败已累计', int(Breaker(OKURL)._load().get('fails', 0)) == 3)
mode['kind'] = 'ok'
T.get(OKURL)
check('成功清零连败', int(Breaker(OKURL)._load().get('fails', 0)) == 0)

# ── 5. 域隔离 ───────────────────────────────────────────────────
A, B = 'https://iso-a.example/a', 'https://iso-b.example/b'
fresh(A); fresh(B)
mode['kind'] = 'raise'
mode['exc'] = RuntimeError('a 站挂了')
for _ in range(DEFAULT_FAIL_THRESHOLD):
    try:
        T.get(A)
    except (RuntimeError, T.BreakerOpenError):
        pass
try:
    T.get(A)
except T.BreakerOpenError:
    pass
mode['kind'] = 'ok'
try:
    r = T.get(B)
    check('另一个站不受影响', r[0] == 'body')
except Exception as e:
    check('另一个站不受影响', False)

# ── 6. 非幂等通道 (request) 共用同一套熔断 ──────────────────────
import inspect
REQURL = 'https://brk.example/req'
fresh(REQURL)
br = Breaker(REQURL)
for _ in range(DEFAULT_FAIL_THRESHOLD):
    br.record(False)
try:
    T._breaker_guard(REQURL)
    check('共用 helper: 已打开的熔断对 request 通道同样生效', False)
except T.BreakerOpenError:
    check('共用 helper: 已打开的熔断对 request 通道同样生效', True)
check('request 通道确实走同一个熔断 helper',
      '_breaker_guard(' in inspect.getsource(T.request) and
      '_count_failure(' in inspect.getsource(T._guarded))

print()
if fails:
    print('FAILED: %d 项 -> %s' % (len(fails), ', '.join(fails)))
    sys.exit(1)
print('ALL PASS')
