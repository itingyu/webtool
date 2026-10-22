"""免 key 降级链的离线测试: 打桩引擎表与渲染, 不碰网络"""
import os
import sys
from types import SimpleNamespace

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from webtool.pipeline import search as S       # noqa: E402
from webtool.pipeline import fallback as F     # noqa: E402
import webtool.render.render as R              # noqa: E402

_fails = []

def check(cond, name):
    if cond:
        print('PASS ' + name)
    else:
        print('FAIL ' + name)
        _fails.append(name)

# ---- 纯选择逻辑 ----

_TABLE = {
    'main':  {'fn': lambda *a, **k: [], 'params': {}},
    'k2':    {'fn': lambda *a, **k: [], 'params': {'keyless': True, 'fallback_rank': 2}},
    'k1':    {'fn': lambda *a, **k: [], 'params': {'keyless': True, 'fallback_rank': 1}},
    'kimg':  {'fn': None, 'params': {'keyless': True, 'fallback_rank': 0}},
}

check(F.chain(_TABLE) == ['k1', 'k2'], 'chain 按 fallback_rank 排序, 跳过无 fn 的')
check(F.chain({}) == [], 'chain 空表返回空')
check(F.needed(0, 8) and F.needed(2, 8), 'needed: 少于 3 条要降级')
check(not F.needed(3, 8), 'needed: 够 3 条不降级')
check(F.needed(0, 1) and not F.needed(1, 1), 'needed: 只要 1 条时 1 条就够')
check(F.select(_TABLE, ['k1'], 3) == ['k2'], 'select 跳过已试过的')
check(F.select(_TABLE, [], 1) == ['k1'], 'select 尊重 limit')

# ---- 调度集成: 主引擎失败 → 免 key 引擎兜底 ----

_calls = []

def _mk(prefix, n):
    return [{'url': f'https://{prefix}/{i}', 'title': f'{prefix} {i}',
             'snippet': 'x', 'engine': prefix} for i in range(n)]

def _fake_engine_fail(*a, **k):
    _calls.append('main')
    raise RuntimeError('blocked 403')

def _fake_engine_ok(*a, **k):
    _calls.append('k1')
    return _mk('k1', 5)

def _engines():
    return {
        'main': {'fn': _fake_engine_fail, 'params': {'enabled_by_default': True}},
        'k1':   {'fn': _fake_engine_ok,
                 'params': {'keyless': True, 'fallback_rank': 1}},
    }

_captured = {}
R.render = lambda out, fmt, kind: _captured.update(out)
S._engines = _engines

def _args(**kw):
    base = dict(query='测试', engine='main', preset=None, max=5, blocklist='',
                no_cache=True, no_proxy=True, no_ad=True, operators='passthrough',
                jobs=1, since=None, until=None, date_strict=False,
                no_fallback=False, format='json')
    base.update(kw)
    return SimpleNamespace(**base)

_rc = S.do_search(_args(), {'timeout': 5})
check(_rc == 0, '集成: do_search 返回 0')
check(_captured.get('total') == 5, '集成: 降级后拿到 5 条')
check([f['engine'] for f in _captured.get('fallback') or []] == ['k1'],
      '集成: fallback 记录 k1')
check(all(r.get('fallback') for r in _captured.get('results') or []),
      '集成: 降级结果带 fallback 标记')
check(any('兜底' in d for d in _captured.get('degraded') or []),
      '集成: degraded 里有兜底提示')

_calls.clear()
_captured.clear()
S.do_search(_args(no_fallback=True), {'timeout': 5})
check(_captured.get('total') == 0, '集成: --no-fallback 时 0 条')
check('k1' not in _calls, '集成: --no-fallback 不跑免 key 引擎')

_calls.clear()
_captured.clear()
S.do_search(_args(engine='k1'), {'timeout': 5})
check(_captured.get('total') == 5, '集成: 指定免 key 引擎时正常出结果')
check(not _captured.get('fallback'), '集成: 结果够时不再降级')

print('')
if _fails:
    print('FAILED: %d 项' % len(_fails))
    sys.exit(1)
print('ALL PASS')
