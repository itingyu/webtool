# -*- coding: utf-8 -*-
"""多引擎并发抓取: 又快、又不乱序

`webtool search` 一次要打五六个引擎, 串行时墙钟=各家之和 (google 一个就能拖
十几秒)。并发是必须的, 但并发很容易顺手把两个东西搞坏:

  1. **结果顺序**: merge 的排序对并列项是稳定的, 回填顺序一变, 同一 query
     两次跑出不同排名 —— 没法交代, 也没法复现;
  2. **错误顺序**: 哪个引擎挂了会随线程完成顺序变, 日志不可比对。

这个测试用假引擎 (可控耗时) 把这两条钉住, 顺带确认"真的在并发"。

跑法: python3 tests/test_search_parallel.py
"""
import os
import sys
import tempfile
import time
import types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'src'))

TMP = tempfile.mkdtemp(prefix='webtool-search-par-')
os.environ['WEBTOOL_DIR'] = TMP

from webtool.pipeline import search as S            # noqa: E402

fails = []


def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + ('' if cond else '  ' + detail))
    if not cond:
        fails.append(name)


# ── 1. 并发度解析 ───────────────────────────────────────────────────────
_j = lambda a, c, n: S._jobs(types.SimpleNamespace(jobs=a), c, n)
check('不给 --jobs → 自动取引擎数, 上限 6', _j(None, {}, 9) == 6 and _j(None, {}, 3) == 3)
check('配置里的 jobs 生效', _j(None, {'jobs': 2}, 5) == 2)
check('--jobs 覆盖配置', _j(4, {'jobs': 2}, 5) == 4)
check('--jobs 1 表示串行', _j(1, {}, 5) == 1)
check('乱值 / 越界都钳住', _j('abc', {}, 5) == 5 and _j(99, {}, 5) == 5
      and _j(0, {}, 0) == 1)

# ── 假引擎: 可控耗时, 慢的排前面 ────────────────────────────────────────
SLEEP = {'slow': 0.5, 'mid': 0.35, 'fast': 0.1, 'boom': 0.05}


def _fake_fn(name, delay):
    def fn(q, max_results=10, proxy=None, timeout=15, market=None):
        time.sleep(delay)
        if name == 'boom':
            raise RuntimeError('引擎自己炸了')
        # 标题/URL 都造得互不相干: 假数据太像会被 merge 正确地去重/聚类,
        # 那就测不出"顺序"了
        return [{'title': '%sUNIQUEWORD' % name.upper(),
                 'url': 'https://example.com/%s/1' % name,
                 'snippet': 's', 'score': 1.0}]
    return fn


_FAKE = {n: {'fn': _fake_fn(n, d), 'enabled_by_default': True}
         for n, d in SLEEP.items()}
_real_engines = S._engines
S._engines = lambda: _FAKE

_captured = {}
import webtool.render.render as _rr                    # noqa: E402
_real_render = _rr.render
_rr.render = lambda out, fmt, kind: _captured.update(out, _kind=kind)


def run(engines, jobs=None):
    _captured.clear()
    args = types.SimpleNamespace(
        query='测试', engine=','.join(engines), preset=None, max=10,
        operators='passthrough', blocklist='', format='json',
        no_cache=True, no_proxy=True, jobs=jobs)
    t0 = time.time()
    rc = S.do_search(args, {'cache_dir': TMP, 'timeout': 5, 'market': 'zh-CN'})
    return rc, time.time() - t0, dict(_captured)


# 先热身一次: 首次调用要付模块导入的账 (约 0.5s), 记到并发头上会冤枉它
run(['fast'])

ORDER = ['slow', 'mid', 'fast']
rc, took, out = run(ORDER)
check('并发: 4 个假引擎 (含 1 个报错) 能跑完', rc == 0, 'rc=%s' % rc)
check('并发: 墙钟接近最慢那个 (串行要 %ss, 并发 <0.9s)' % sum(SLEEP[e] for e in ORDER),
      took < 0.9, '实际 %.2fs' % took)
check('并发: 结果按 --engine 声明顺序回填 (慢的排前, 不随完成顺序)',
      [r['engines'] for r in out['results']] == [['slow'], ['mid'], ['fast']],
      str([r.get('engines') for r in out['results']]))

rc, took_serial, out_s = run(ORDER, jobs=1)
check('--jobs 1: 退回串行 (墙钟 >= 各自之和的 80%)', took_serial >= 0.8,
      '%.2fs' % took_serial)
check('串行与并发结果顺序一致',
      [r['engines'] for r in out['results']] ==
      [r['engines'] for r in out_s['results']])

rc, _t, out_e = run(['boom', 'fast', 'mid'])
check('并发: 报错引擎不影响其它引擎 (仍拿到 2 条)', rc == 0 and out_e['total'] == 2,
      str(out_e.get('total')))
check('并发: 错误也按声明序报 (boom 在最前)', [e['engine'] for e in out_e['errors']]
      == ['boom'], str(out_e.get('errors')))

rc, _t, out_u = run(['zzz', 'fast', 'yyy'])
check('未知引擎仍逐个报 (按声明序), 已知引擎照跑',
      [e['engine'] for e in out_u['errors']] == ['zzz', 'yyy']
      and out_u['total'] == 1, str(out_u.get('errors')))

# ── 收尾: 假引擎一个都不该漏掉 ──────────────────────────────────────────
check('每个引擎都有 cache 状态 (fresh)', out['cache'] ==
      {'slow': 'fresh', 'mid': 'fresh', 'fast': 'fresh'}, str(out['cache']))

S._engines = _real_engines
_rr.render = _real_render

print()
if fails:
    print('FAILED: %s' % ', '.join(fails))
    sys.exit(1)
print('ALL PASS')
