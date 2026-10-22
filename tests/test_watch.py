"""watch 增量监控的离线测试: 把 _fetch_items 打桩, 不碰网络"""
import io
import os
import sys
import tempfile
from contextlib import redirect_stdout
from types import SimpleNamespace

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from webtool.cli import watch as W  # noqa: E402

_fails = []

def check(cond, name):
    if cond:
        print('PASS ' + name)
    else:
        print('FAIL ' + name)
        _fails.append(name)

_TMP = tempfile.mkdtemp(prefix='watchtest-')
W.WATCH_STATE_FILE = os.path.join(_TMP, 'watch_state.json')

_feed = {'items': []}

def _fake_fetch(args, target):
    return list(_feed['items']), '', getattr(args, 'kind', 'search')

W._fetch_items = _fake_fetch

def _args(**kw):
    base = dict(target='测试词', kind='search', num=10, engine=None, preset=None,
                since=None, until=None, name=None, list=False, reset=False,
                max_seen=500, format='text', no_proxy=True, no_cache=True)
    base.update(kw)
    return SimpleNamespace(**base)

def _run(**kw):
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = W.do_watch(_args(**kw), {})
    return rc, buf.getvalue()

def _items(*pairs):
    return [{'title': t, 'url': u} for t, u in pairs]

check(W._item_key({'url': 'https://a/1'}) == 'u:https://a/1', 'key 优先 url')
check(W._item_key({'title': 'T'}) == 't:T', '无 url 时用标题')
check(W._item_key({'title': 'T', 'source': 'zhihu'}) == 't:zhihu:T',
      'rank 条目带源名, 跨平台同名不互相吞')
check(W._item_key({}) == '', '空条目没有 key')

b1 = W._bucket_name(_args(), '甲')
b2 = W._bucket_name(_args(engine='bing'), '甲')
check(b1 != b2, '换引擎是另一个桶')
check(b1 == W._bucket_name(_args(), '甲'), '同参数桶名稳定')
check(W._bucket_name(_args(name='自定义'), '甲') == '自定义', '--name 优先')

_feed['items'] = _items(('A', 'https://a.com/1'), ('B', 'https://a.com/2'))
rc, out = _run()
check(rc == 1, '首次运行: 有内容 → 退出码 1')
check('新增 2 条' in out, '首次运行列出全部')

rc, out = _run()
check(rc == 0, '同结果再跑: 退出码 0')
check('无新增' in out, '同结果再跑: 说无新增')

_feed['items'] = _items(('A', 'https://a.com/1'), ('C', 'https://a.com/3'))
rc, out = _run()
check(rc == 1, '出现新条目 → 退出码 1')
check('新增 1 条' in out, '只报差集')
check('C' in out and 'B' not in out, '旧条目不再重复出现')

_feed['items'] = _items(('A改个标题', 'https://a.com/1'))
rc, out = _run()
check(rc == 0, '同 url 改标题不算新增')

# ── --reset / --list / json / 上限 ──────────────────────
_feed['items'] = _items(('A', 'https://a.com/1'))
rc, out = _run()
check(rc == 0, 'reset 前: 无新增')

rc, out = _run(reset=True)
check(rc == 1, 'reset 后同一批又算新增')
check('新增 1 条' in out, 'reset 后重新报')

rc, out = _run(list=True)
check('search-' in out and '已见' in out, '--list 列出桶')
check(rc == 0, '--list 退出码 0')

_feed['items'] = _items(('A', 'https://a.com/1'), ('D', 'https://a.com/4'))
rc, out = _run(format='json')
data = __import__('json').loads(out)
check(data['new_count'] == 1, 'json new_count')
check(data['new'][0]['url'] == 'https://a.com/4', 'json 带新增条目 url')
check(data['bucket'].startswith('search-'), 'json 带桶名')
check(data['exit'] == 1, 'json 里说明该不该通知')

# 状态上限: 记的条数不超过 max_seen
_feed['items'] = _items(*[('T%d' % i, 'https://a.com/%d' % i) for i in range(8)])
_run(max_seen=50)
raw = __import__('json').load(open(W.WATCH_STATE_FILE))
bid = W._bucket_name(_args(), '测试词')
check(len(raw[bid]['seen']) <= 50, '已见条数受 max_seen 限制')
check(raw[bid]['last_run'] > 0, '记录了上次运行时间')

# 空结果不改状态 (抓取失败不该把已见清空)
before = len(raw[bid]['seen'])
_feed['items'] = []
rc, out = _run()
after = len(__import__('json').load(open(W.WATCH_STATE_FILE))[bid]['seen'])
check(rc == 2, '取不到条目 → 退出码 2')
check(before == after, '空结果不动状态')

print('')
if _fails:
    print('FAILED: %d 项' % len(_fails))
    sys.exit(1)
print('ALL PASS')
